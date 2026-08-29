"""PDF report generator for the DTA physical-hydrologic characterization."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from api.services.characteristics_workbook import _parameter_rows


def _number(value: Any, digits: int = 2, decimal_separator: str = ",") -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
        abs_value = abs(number)
        display_digits = 3 if abs_value < 1 else 2 if abs_value < 10 else 1 if abs_value < 100 else 0
        text = f"{number:,.{display_digits}f}"
        if display_digits:
            text = text.rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)
    if decimal_separator == ",":
        return text.replace(",", "X").replace(".", ",").replace("X", ".")
    return text


def _safe_text(value: Any) -> str:
    """Normalize and escape dynamic text before passing it to ReportLab Paragraph."""
    normalized = str(value or "").replace("–", "-").replace("—", "-")
    for source, target in {
        "Recession limb": "Waktu surut", "baseflow": "aliran dasar", "floodplain": "dataran banjir",
        "confidence": "kepercayaan", "flowpath": "lintasan aliran", "junction": "percabangan",
        "upstream": "hulu", "raster": "data spasial", "DEM": "data ketinggian", "HEC-HMS": "metode hidrologi",
    }.items():
        normalized = normalized.replace(source, target).replace(source.lower(), target)
    return escape(normalized)


def create_characteristics_report(results: list[dict[str, Any]], output_path: Path, *, language: str = "id",
                                  decimal_separator: str = ",") -> Path:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import reportlab
        from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover - deployment dependency check
        raise RuntimeError("Pembuatan PDF memerlukan reportlab. Jalankan pip install -r requirements.txt.") from exc

    font_dir = Path(reportlab.__file__).resolve().parent / "fonts"
    pdfmetrics.registerFont(TTFont("DTARegular", str(font_dir / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("DTABold", str(font_dir / "VeraBd.ttf")))
    is_en = False
    labels = {
        "title": "Laporan Karakteristik Daerah Tangkapan Air",
        "summary": "Executive Summary" if is_en else "Ringkasan Eksekutif",
        "indicators": "Indikator Kunci",
        "technical": "Karakteristik Detail",
        "landcover": "Land Cover" if is_en else "Penutupan Lahan",
        "curve": "Curve Number and Runoff Potential" if is_en else "Curve Number dan Potensi Limpasan",
        "tc": "Time of Concentration" if is_en else "Waktu Konsentrasi",
        "limitations": "Limitations" if is_en else "Batasan Interpretasi",
        "parameter": "Parameter", "value": "Value" if is_en else "Nilai", "note": "Interpretation" if is_en else "Interpretasi",
    }
    styles = getSampleStyleSheet()
    title = ParagraphStyle("report-title", parent=styles["Title"], fontName="DTABold", fontSize=17,
                           leading=21, textColor=colors.HexColor("#223468"), alignment=TA_CENTER, spaceAfter=12)
    h2 = ParagraphStyle("report-h2", parent=styles["Heading2"], fontName="DTABold", fontSize=11,
                        leading=13, textColor=colors.HexColor("#223468"), spaceBefore=7, spaceAfter=4)
    body = ParagraphStyle("report-body", parent=styles["BodyText"], fontName="DTARegular", fontSize=8.2,
                          leading=10.5, spaceAfter=4, alignment=TA_JUSTIFY)
    small = ParagraphStyle("report-small", parent=body, fontSize=7.2, leading=8.5, textColor=colors.HexColor("#4d596b"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=1.55 * cm, rightMargin=1.55 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.0 * cm, title=labels["title"])
    story = []
    for index, result in enumerate(results):
        analysis = result.get("hydrologic_analysis") or {}
        summary = analysis.get("executive_summary") or {}
        terrain = analysis.get("terrain") or {}
        elevation = terrain.get("elevation") or {}
        slope = terrain.get("slope") or {}
        drainage = analysis.get("drainage") or {}
        morph = analysis.get("morphometry") or {}
        landcover = analysis.get("landcover") or {}
        landsystem = analysis.get("landsystem") or {}
        cn = analysis.get("curve_number") or {}
        tc = analysis.get("time_of_concentration") or {}
        name = result.get("label") or result.get("point_id") or f"DTA {index + 1}"
        story.extend([Paragraph(_safe_text(labels["title"]), title), Paragraph(_safe_text(name), ParagraphStyle("name", parent=styles["Heading1"], fontName="DTABold", alignment=TA_CENTER, fontSize=12, textColor=colors.HexColor("#3e506f"))), Spacer(1, 8)])
        story.append(Paragraph(labels["summary"], h2))
        response = summary.get("response_class") or ("Not available" if is_en else "Belum tersedia")
        response_label = "Hydrologic response" if is_en else "Respons hidrologi"
        story.append(Paragraph(
            f"<b>{_safe_text(response_label)}: {_safe_text(response)}</b><br/>{_safe_text(summary.get('narrative'))}",
            body,
        ))
        data = [[labels["parameter"], labels["value"]]]
        for item in analysis.get("key_indicator_items") or []:
            unit = _safe_text(item.get("unit") or "")
            data.append([_safe_text(item.get("label")), f"{_number(item.get('value'), decimal_separator=decimal_separator)}{(' ' + unit) if unit else ''}"])
        table = Table(data, colWidths=[8.8 * cm, 7.2 * cm], repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#223468")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                   ("FONTNAME", (0, 0), (-1, 0), "DTABold"), ("FONTNAME", (0, 1), (-1, -1), "DTARegular"),
                                   ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#cbd3df")),
                                   ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f7f9fc")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(KeepTogether([Paragraph(labels["indicators"], h2), table]))
        story.append(Paragraph("Karakteristik Wilayah", h2))
        for paragraph in analysis.get("territory_paragraphs") or []:
            story.append(Paragraph(_safe_text(paragraph), body))
        story.append(PageBreak())
        technical = [[labels["parameter"], labels["value"], labels["note"]]]
        detail_cell = ParagraphStyle("report-detail-cell", parent=small, fontSize=6.8, leading=8.1, textColor=colors.HexColor("#182233"))
        detail_value = ParagraphStyle("report-detail-value", parent=detail_cell, fontName="DTABold")
        for parameter, value, unit, note in _parameter_rows(result)[1:]:
            unit_text = "" if unit in {None, "-"} else f" {_safe_text(unit)}"
            technical.append([
                Paragraph(_safe_text(parameter), detail_cell),
                Paragraph(f"{_number(value, decimal_separator=decimal_separator)}{unit_text}", detail_value),
                Paragraph(_safe_text(note), detail_cell),
            ])
        detail_table = Table(technical, colWidths=[5.8 * cm, 3.1 * cm, 7.0 * cm], repeatRows=1)
        detail_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#223468")),
                                          ("FONTNAME", (0, 0), (-1, 0), "DTABold"), ("FONTNAME", (0, 1), (-1, -1), "DTARegular"), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                                          ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#d4dbe5")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                          ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(KeepTogether([Paragraph(labels["technical"], h2), detail_table]))
        slope_names = {"Datar": "Datar (0-8%)", "Landai": "Landai (>8-15%)", "Agak curam": "Agak curam (>15-25%)", "Curam": "Curam (>25-40%)", "Sangat curam": "Sangat curam (>40%)"}
        slope_data = [["Kelas", "Persentase luas"]] + [[slope_names.get(item.get("class"), item.get("class")), _number(item.get("area_pct"), decimal_separator=decimal_separator) + " %"] for item in slope.get("distribution") or []]
        slope_table = Table(slope_data, colWidths=[11.0 * cm, 5.0 * cm], repeatRows=1)
        slope_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")), ("FONTNAME", (0, 0), (-1, 0), "DTABold"), ("FONTNAME", (0, 1), (-1, -1), "DTARegular"), ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#d4dbe5")), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(KeepTogether([Paragraph("Distribusi Kelas Lereng", h2), slope_table]))
        lc_lines = [_safe_text(f"{item.get('name')}: {_number(item.get('area_km2'), 2, decimal_separator)} km2 ({_number(item.get('area_pct'), 2, decimal_separator)} %)") for item in (landcover.get("classes") or [])[:8]]
        story.append(KeepTogether([Paragraph(labels["landcover"], h2), Paragraph("; ".join(lc_lines) if lc_lines else ("Not available" if is_en else "Belum tersedia"), body)]))
        ls_lines = [_safe_text(
            f"{item.get('land_type')}: {_number(item.get('area_pct'), 2, decimal_separator)} %"
            if item.get("land_type") == "Badan Air" else
            f"{item.get('land_type')}; fisiografi {item.get('physiography')}; relief {item.get('relief_class')}: {_number(item.get('area_pct'), 2, decimal_separator)} %"
        ) for item in (landsystem.get("classes") or [])[:5]]
        story.append(KeepTogether([Paragraph("Sistem Lahan", h2), Paragraph("; ".join(ls_lines) if ls_lines else "Belum tersedia", body)]))
        interpretations = cn.get("interpretations") or {}
        curve_summary = Paragraph(f"Curve Number Rata-rata Tertimbang (CN-II): <b>{_number(cn.get('weighted_cn_ii'), decimal_separator=decimal_separator)}</b> ({_safe_text(interpretations.get('weighted_cn'))}); "
                               f"Retensi Potensial (S): <b>{_number(cn.get('potential_retention_mm'), decimal_separator=decimal_separator)} mm</b> ({_safe_text(interpretations.get('retention'))}); "
                               f"Luas Area CN >= 80: <b>{_number(cn.get('high_cn_pct'), decimal_separator=decimal_separator)} %</b> ({_safe_text(interpretations.get('high_cn_area'))}).", body)
        story.append(KeepTogether([Paragraph(labels["curve"], h2), curve_summary]))
        cn_data = [["Kelas", "Persentase luas"]] + [[_safe_text(item.get("class")), _number(item.get("area_pct"), decimal_separator=decimal_separator) + " %"] for item in cn.get("distribution") or []]
        cn_table = Table(cn_data, colWidths=[11.0 * cm, 5.0 * cm], repeatRows=1)
        cn_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")), ("FONTNAME", (0, 0), (-1, 0), "DTABold"), ("FONTNAME", (0, 1), (-1, -1), "DTARegular"), ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#d4dbe5")), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(KeepTogether([Paragraph("Distribusi Curve Number", h2), cn_table]))
        tc_data = [["Metode", "Estimasi", "Keterangan"]]
        for item in tc.get("methods") or []:
            tc_data.append([_safe_text(item.get("label")), _number(item.get("value_hours"), decimal_separator=decimal_separator) + (" jam" if item.get("value_hours") is not None else ""), Paragraph(_safe_text(item.get("reason")), small)])
        tc_data.append(["Tc Representatif", _number(tc.get("representative_hours") or tc.get("recommended_hours"), decimal_separator=decimal_separator) + " jam", Paragraph(_safe_text(f"Dasar: {', '.join(tc.get('representative_methods') or tc.get('recommendation_methods') or [])}. Kesepakatan antar-metode {tc.get('method_agreement') or tc.get('confidence') or 'Rendah'}. {tc.get('representative_basis') or tc.get('recommendation_basis') or ''}"), small)])
        tc_table = Table(tc_data, colWidths=[4.0 * cm, 2.7 * cm, 9.3 * cm], repeatRows=1)
        tc_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")), ("FONTNAME", (0, 0), (-1, 0), "DTABold"), ("FONTNAME", (0, 1), (-1, -1), "DTARegular"), ("FONTSIZE", (0, 0), (-1, -1), 7.1), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#d4dbe5")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(KeepTogether([Paragraph(labels["tc"], h2), tc_table]))
        story.append(Paragraph(labels["limitations"], h2))
        for item in analysis.get("limitations") or []:
            story.append(Paragraph("- " + _safe_text(item), small))
        if index < len(results) - 1:
            story.append(PageBreak())
    doc.build(story)
    return output_path
