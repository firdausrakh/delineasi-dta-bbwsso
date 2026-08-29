"""A4 PDF export for one DTA synthetic unit hydrograph analysis.

The layout mirrors the web UI: white page, navy headings, subtle table borders,
and compact method cards. Calculations are read from the same HSS payload used
by the interactive Chart.js view and Excel workbook.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


def _num(value: Any, digits: int = 3) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _safe(value: Any) -> str:
    return escape(str(value or "").replace("–", "-").replace("—", "-"))


def _chart(methods: list[dict[str, Any]], *, normalized: bool = False):
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
    from reportlab.lib import colors

    width, height = 480, 205
    left, right, top, bottom = 48, 10, 12, 32
    plot_w, plot_h = width - left - right, height - top - bottom
    series = []
    for method in methods:
        if not method.get("available"):
            continue
        pts = []
        for row in method.get("ordinates") or []:
            try:
                x = float(row.get("time_hours"))
                y = float(row.get("normalized_discharge_m3s") if normalized else row.get("discharge_m3s"))
            except (TypeError, ValueError):
                continue
            if x >= 0 and y >= 0:
                pts.append((x, y))
        if pts:
            series.append((method.get("label") or method.get("method"), pts))
    drawing = Drawing(width, height)
    drawing.add(Rect(left, bottom, plot_w, plot_h, fillColor=colors.HexColor("#FBFCFE"), strokeColor=colors.HexColor("#DCE2EA"), strokeWidth=.5))
    if not series:
        drawing.add(String(width/2, height/2, "Kurva HSS belum tersedia", textAnchor="middle", fontSize=8, fillColor=colors.HexColor("#667085")))
        return drawing
    max_x = max(p[0] for _, pts in series for p in pts) or 1.0
    max_y = max(p[1] for _, pts in series for p in pts) or 1.0
    palette = ["#223468", "#D97706", "#16836B", "#7C4D9A", "#B64E58", "#2678B2", "#697B2B"]
    for i in range(6):
        x = left + plot_w * i / 5
        y = bottom + plot_h * i / 5
        drawing.add(Line(x, bottom, x, bottom + plot_h, strokeColor=colors.HexColor("#E9EDF3"), strokeWidth=.4))
        drawing.add(Line(left, y, left + plot_w, y, strokeColor=colors.HexColor("#E9EDF3"), strokeWidth=.4))
        drawing.add(String(x, bottom - 12, _num(max_x*i/5, 1), textAnchor="middle", fontSize=6.5, fillColor=colors.HexColor("#667085")))
        drawing.add(String(left - 5, y - 2, _num(max_y*i/5, 2), textAnchor="end", fontSize=6.5, fillColor=colors.HexColor("#667085")))
    drawing.add(Line(left, bottom, left + plot_w, bottom, strokeColor=colors.HexColor("#98A2B3"), strokeWidth=.7))
    drawing.add(Line(left, bottom, left, bottom + plot_h, strokeColor=colors.HexColor("#98A2B3"), strokeWidth=.7))
    drawing.add(String(left + plot_w/2, 4, "Waktu (jam)", textAnchor="middle", fontSize=7, fillColor=colors.HexColor("#475467")))
    drawing.add(String(4, bottom + plot_h/2, "Debit", textAnchor="start", fontSize=7, fillColor=colors.HexColor("#475467")))
    for index, (label, pts) in enumerate(series):
        color = colors.HexColor(palette[index % len(palette)])
        coords = []
        for x, y in pts:
            coords.extend([left + (x/max_x)*plot_w, bottom + (y/max_y)*plot_h])
        if len(coords) >= 4:
            drawing.add(PolyLine(coords, strokeColor=color, strokeWidth=1.35, fillColor=None))
    # compact legend on top
    x0, y0 = left, height - 4
    for index, (label, _) in enumerate(series):
        color = colors.HexColor(palette[index % len(palette)])
        drawing.add(Line(x0, y0, x0 + 10, y0, strokeColor=color, strokeWidth=2))
        drawing.add(String(x0 + 13, y0 - 2.5, str(label)[:21], fontSize=5.8, fillColor=colors.HexColor("#475467")))
        x0 += 68
        if x0 > width - 70:
            x0 = left
            y0 -= 10
    return drawing


def create_hss_report(payload: dict[str, Any], output_path: Path) -> Path:
    if not payload or not payload.get("methods"):
        raise ValueError("Hasil HSS belum tersedia")
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import reportlab
        from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pembuatan PDF memerlukan reportlab.") from exc

    font_dir = Path(reportlab.__file__).resolve().parent / "fonts"
    pdfmetrics.registerFont(TTFont("DTARegular", str(font_dir / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("DTABold", str(font_dir / "VeraBd.ttf")))
    primary = colors.HexColor("#223468")
    accent = colors.HexColor("#D97706")
    border = colors.HexColor("#D8DEE8")
    soft = colors.HexColor("#F7F9FC")
    muted = colors.HexColor("#667085")

    styles = getSampleStyleSheet()
    title = ParagraphStyle("hss-title", parent=styles["Title"], fontName="DTABold", fontSize=16, leading=20, textColor=primary, alignment=TA_CENTER, spaceAfter=5)
    name_style = ParagraphStyle("hss-name", parent=styles["Heading2"], fontName="DTABold", fontSize=10.5, leading=13, textColor=colors.HexColor("#344054"), alignment=TA_CENTER, spaceAfter=10)
    h2 = ParagraphStyle("hss-h2", parent=styles["Heading2"], fontName="DTABold", fontSize=10.2, leading=12, textColor=primary, spaceBefore=7, spaceAfter=4)
    body = ParagraphStyle("hss-body", parent=styles["BodyText"], fontName="DTARegular", fontSize=7.5, leading=9.2, textColor=colors.HexColor("#344054"))
    small = ParagraphStyle("hss-small", parent=body, fontSize=6.5, leading=8, textColor=muted)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=1.35*cm, rightMargin=1.35*cm, topMargin=1.15*cm, bottomMargin=1.05*cm, title="Analisis Hidrograf Satuan Sintetis")
    story = [Paragraph("ANALISIS HIDROGRAF SATUAN SINTETIS", title), Paragraph(_safe(payload.get("label") or payload.get("point_id") or "DTA"), name_style)]
    info = Table([
        ["Hujan efektif satuan", f"{_num(payload.get('unit_runoff_mm',1),3)} mm", "Durasi hujan efektif global (Tr)", f"{_num(payload.get('global_tr_hours',1),3)} jam"],
        ["Profil persamaan", str(payload.get("formula_profile") or "-"), "Metode tersedia", str(payload.get("available_method_count") or 0)],
    ], colWidths=[3.2*cm, 2.8*cm, 5.6*cm, 4.4*cm])
    info.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),soft),("BOX",(0,0),(-1,-1),.5,border),("INNERGRID",(0,0),(-1,-1),.35,border),("FONTNAME",(0,0),(-1,-1),"DTARegular"),("FONTNAME",(0,0),(0,-1),"DTABold"),("FONTNAME",(2,0),(2,-1),"DTABold"),("FONTSIZE",(0,0),(-1,-1),7),("TEXTCOLOR",(0,0),(-1,-1),colors.HexColor("#344054")),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    story.extend([
        info, Spacer(1,7), Paragraph("Perbandingan HSS", h2), _chart(payload.get("methods") or [])
    ])

    summary_rows = [["Metode","Tp (jam)","Qp (m3/s)","Tb (jam)","Limpasan (mm)","Error volume"]]
    for method in payload.get("methods") or []:
        if method.get("available"):
            err = method.get("volume_error_pct")
            summary_rows.append([method.get("label"),_num(method.get("Tp_hours")),_num(method.get("Qp_m3s")),_num(method.get("Tb_hours")),_num(method.get("equivalent_runoff_mm"),4),("+" if isinstance(err,(int,float)) and err>=0 else "")+_num(err,2)+" %"])
        else:
            summary_rows.append([method.get("label"),"-","-","-","-","Belum tersedia"])
    summary = Table(summary_rows, colWidths=[4.1*cm,2.1*cm,2.5*cm,2.1*cm,2.5*cm,2.7*cm], repeatRows=1)
    summary.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),primary),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"DTABold"),("FONTNAME",(0,1),(-1,-1),"DTARegular"),("FONTSIZE",(0,0),(-1,-1),6.6),("GRID",(0,0),(-1,-1),.35,border),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,soft]),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story.extend([Spacer(1,5), summary])

    for method in payload.get("methods") or []:
        if not method.get("available"):
            continue
        story.append(PageBreak())
        story.append(Paragraph(f"HSS {_safe(method.get('label'))}", h2))
        # blue/orange metric cards as a compact 4-column table
        tp_label = "Waktu naik / puncak (TR = Tp)" if method.get("method") == "gama1" else "Waktu puncak (Tp)"
        metrics = [[tp_label,"Debit puncak (Qp)","Waktu dasar (Tb)","Limpasan ekuivalen"],[_num(method.get("Tp_hours"))+" jam",_num(method.get("Qp_m3s"))+" m3/s",_num(method.get("Tb_hours"))+" jam",_num(method.get("equivalent_runoff_mm"),4)+" mm"]]
        metric_table = Table(metrics, colWidths=[4*cm]*4)
        metric_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),soft),("TEXTCOLOR",(0,0),(-1,0),muted),("TEXTCOLOR",(0,1),(-1,1),primary),("FONTNAME",(0,0),(-1,0),"DTARegular"),("FONTNAME",(0,1),(-1,1),"DTABold"),("FONTSIZE",(0,0),(-1,0),6.2),("FONTSIZE",(0,1),(-1,1),8),("BOX",(0,0),(-1,-1),.5,border),("INNERGRID",(0,0),(-1,-1),.35,border),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        story.extend([metric_table, Spacer(1,5), _chart([method])])

        input_rows=[["Parameter DTA","Nilai"]]+[[k,_num(v,5)] for k,v in (method.get("inputs") or {}).items() if v is not None]
        if method.get("method") == "gama1":
            derived = method.get("derived") or {}
            param_rows=[["Parameter Gama I","Nilai"],["TR = Tp (jam)",_num(derived.get("TR_hours"),5)],["K (jam)",_num(derived.get("K_hours"),5)]]
        else:
            param_rows=[["Koefisien kalibrasi","Nilai"]]+[[k,_num(v,5)] for k,v in (method.get("parameters") or {}).items()]
        max_len=max(len(input_rows),len(param_rows));input_rows += [["",""]]*(max_len-len(input_rows));param_rows += [["",""]]*(max_len-len(param_rows))
        combined=[[Paragraph(_safe(a[0]),small),Paragraph(_safe(a[1]),small),Paragraph(_safe(b[0]),small),Paragraph(_safe(b[1]),small)] for a,b in zip(input_rows,param_rows)]
        details=Table(combined,colWidths=[4.5*cm,2.5*cm,4.5*cm,2.5*cm])
        details.setStyle(TableStyle([("BACKGROUND",(0,0),(1,0),primary),("BACKGROUND",(2,0),(3,0),primary),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"DTABold"),("GRID",(0,0),(-1,-1),.3,border),("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),3.5),("BOTTOMPADDING",(0,0),(-1,-1),3.5)]))
        story.extend([Spacer(1,6),details,Spacer(1,6)])

        ordinates=[["Waktu (jam)","t/Tp","Q/Qp","Debit asli","Debit normalisasi"]]
        for row in method.get("ordinates") or []:
            ordinates.append([_num(row.get("time_hours"),4),_num(row.get("t_over_tp"),5),_num(row.get("q_over_qp"),5),_num(row.get("discharge_m3s"),5),_num(row.get("normalized_discharge_m3s"),5)])
        ord_table=Table(ordinates,colWidths=[3.1*cm,3.1*cm,3.1*cm,3.4*cm,3.4*cm],repeatRows=1)
        ord_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),primary),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"DTABold"),("FONTNAME",(0,1),(-1,-1),"DTARegular"),("FONTSIZE",(0,0),(-1,-1),6.2),("GRID",(0,0),(-1,-1),.25,border),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,soft]),("ALIGN",(1,1),(-1,-1),"RIGHT"),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
        story.extend([Paragraph("Ordinat HSS", h2), ord_table])
        if method.get("warnings"):
            story.extend([Spacer(1,5),Paragraph("Catatan",h2),Paragraph("; ".join(_safe(x) for x in method.get("warnings") or []),small)])

    doc.build(story)
    return output_path
