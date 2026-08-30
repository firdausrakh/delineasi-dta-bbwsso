"""Dependency-free Office Open XML export for DTA characteristics.

The workbook keeps analytical values numeric and applies four-decimal display
precision, while narrative and overlay attributes remain auditable text.
"""

from __future__ import annotations

import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape



@dataclass(frozen=True)
class ExcelFormula:
    """Excel formula with a cached numeric value for non-calculating readers."""

    expression: str
    cached: float | None = None

def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell(ref: str, value: Any, style: int = 0) -> str:
    if isinstance(value, ExcelFormula):
        cached = value.cached
        cached_xml = f"<v>{float(cached):.10g}</v>" if cached is not None and math.isfinite(float(cached)) else "<v/>"
        return f'<c r="{ref}" s="{style or 2}"><f>{escape(value.expression)}</f>{cached_xml}</c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return f'<c r="{ref}" s="{style or 2}"><v>{float(value):.10g}</v></c>'
    text = "—" if value is None else str(value)
    replacements = {
        "Recession limb": "Waktu surut", "baseflow": "aliran dasar", "floodplain": "dataran banjir",
        "confidence": "kepercayaan", "flowpath": "lintasan aliran", "junction": "percabangan",
        "upstream": "hulu", "raster": "data spasial", "DEM": "data ketinggian", "HEC-HMS": "metode hidrologi",
    }
    for source, target in replacements.items():
        text = text.replace(source, target).replace(source.lower(), target)
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _worksheet_xml(rows: list[list[Any]], *, widths: list[float], row_styles: dict[int, int] | None = None,
                   freeze_row: int | None = None, autofilter: bool = False) -> str:
    row_styles = row_styles or {}
    xml_rows = []
    for row_index, row in enumerate(rows, 1):
        style = row_styles.get(row_index, 0)
        cells = [_cell(f"{_column_name(column_index)}{row_index}", value, style) for column_index, value in enumerate(row, 1)]
        height = ' ht="34" customHeight="1"' if style in {3, 4} else ""
        xml_rows.append(f'<row r="{row_index}"{height}>{"".join(cells)}</row>')
    columns = "".join(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths, 1))
    pane = f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{freeze_row}" topLeftCell="A{freeze_row + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>' if freeze_row else '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
    dimension = f"A1:{_column_name(max(len(row) for row in rows))}{len(rows)}"
    filter_xml = f'<autoFilter ref="A1:{_column_name(max(len(row) for row in rows))}{len(rows)}"/>' if autofilter else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension}"/>{pane}<sheetFormatPr defaultRowHeight="15"/><cols>{columns}</cols>'
        f'<sheetData>{"".join(xml_rows)}</sheetData>{filter_xml}</worksheet>'
    )


def _parameter_rows(result: dict[str, Any]) -> list[list[Any]]:
    analysis = result.get("hydrologic_analysis") or {}
    morph = analysis.get("morphometry") or {}
    terrain = analysis.get("terrain") or {}
    elevation = terrain.get("elevation") or {}
    slope = terrain.get("slope") or {}
    drainage = analysis.get("drainage") or {}
    cn = analysis.get("curve_number") or {}
    tc = analysis.get("time_of_concentration") or {}
    flow_slope = terrain.get("flowpath_slope") or {}
    hi = terrain.get("hypsometry") or {}
    rb_by_order = drainage.get("bifurcation_ratios_by_order") or {}
    order_counts = drainage.get("order_counts") or {}
    values = [
        ("Luas DTA (A)", morph.get("area_km2"), "km²", "Luas wilayah tangkapan pada batas DTA"),
        ("Keliling (P)", morph.get("perimeter_km"), "km", "Keliling batas DTA yang telah diperhalus"),
        ("Lintasan aliran terpanjang (L)", terrain.get("longest_flow_path_km") or morph.get("basin_length_km"), "km", "Lintasan aliran terpanjang dari outlet ke hulu"),
        ("Lintasan aliran melalui sentroid (Lca)", terrain.get("centroidal_flowpath_km"), "km", "Lintasan outlet melalui titik terdekat sentroid"),
        ("Lintasan aliran 10-85 (L10-85)", terrain.get("flowpath_10_85_km"), "km", "Panjang geometri lintasan antara posisi 10% dan 85%"),
        ("Elevasi minimum", elevation.get("min_m"), "mdpl", "Titik ketinggian terendah dalam DTA"),
        ("Elevasi rata-rata", elevation.get("mean_m"), "mdpl", "Rata-rata ketinggian seluruh wilayah DTA"),
        ("Elevasi median", elevation.get("median_m") if elevation.get("median_m") is not None else ((hi.get("elevation_percentiles_m") or {}).get("50")), "mdpl", "Nilai tengah distribusi ketinggian wilayah DTA"),
        ("Elevasi maksimum", elevation.get("max_m"), "mdpl", "Titik ketinggian tertinggi dalam DTA"),
        ("Elevasi batas tertinggi", elevation.get("divide_max_m"), "mdpl", "Titik tertinggi sepanjang batas DTA"),
        ("Elevasi outlet", elevation.get("outlet_m"), "mdpl", "Ketinggian pada titik outlet DTA"),
        ("Relief DTA (R)", elevation.get("relief_m"), "m", "Selisih batas tertinggi terhadap elevasi outlet"),
        ("Rentang elevasi (ΔZ)", elevation.get("elevation_range_m"), "m", "Selisih elevasi maksimum dan minimum DTA"),
        ("Tinggi rata-rata di atas outlet (Hm)", elevation.get("mean_height_above_outlet_m"), "m", "Elevasi rata-rata dikurangi elevasi outlet"),
        ("Kemiringan rata-rata DTA (S)", slope.get("mean_pct"), "%", "Rata-rata kemiringan permukaan seluruh DTA"),
        ("Kemiringan maksimum", slope.get("p95_pct"), "%", "Nilai tinggi representatif kemiringan permukaan DTA"),
        ("Faktor bentuk (Ff)", morph.get("form_factor"), "-", "Luas dibandingkan kuadrat panjang DTA"),
        ("Rasio elongasi (Re)", morph.get("elongation_ratio"), "-", "Diameter setara dibandingkan panjang DTA"),
        ("Rasio kebulatan (Rc)", morph.get("circularity_ratio"), "-", "Luas dibandingkan kuadrat keliling DTA"),
        ("Rasio relief (RR)", morph.get("relief_ratio"), "-", "Relief dibagi lintasan aliran terpanjang"),
        ("Integral hipsometrik (HI)", hi.get("integral"), "-", f"Tahap perkembangan: {hi.get('stage') or 'belum tersedia'}"),
        ("Panjang total sungai (Lt)", drainage.get("total_stream_length_km"), "km", "Jumlah panjang seluruh sungai dalam DTA"),
        ("Panjang sungai utama", drainage.get("main_channel_length_km"), "km", "Panjang jaringan sungai utama dari outlet menuju hulu"),
        ("Kemiringan sungai utama (Sc)", drainage.get("main_channel_slope_pct"), "%", "Beda elevasi dibagi panjang sungai utama"),
        ("Kemiringan rata-rata jaringan", drainage.get("network_mean_slope_pct"), "%", "Rata-rata kemiringan ruas berbobot panjang"),
        ("Sinuositas sungai utama", drainage.get("channel_sinuosity"), "-", "Panjang sungai utama dibagi jarak lurus ujungnya"),
        ("Kemiringan lintasan aliran terpanjang (SL)", flow_slope.get("longest_flowpath_pct"), "%", "Beda elevasi dibagi panjang lintasan terpanjang"),
        ("Kemiringan lintasan melalui sentroid (Sca)", flow_slope.get("centroidal_flowpath_pct"), "%", "Beda elevasi dibagi panjang lintasan melalui sentroid"),
        ("Kemiringan lintasan 10-85 (S10-85)", flow_slope.get("flowpath_10_85_pct"), "%", "Beda elevasi dibagi panjang lintasan 10-85"),
        ("Kerapatan drainase (Dd)", drainage.get("drainage_density_km_per_km2"), "km/km²", "Panjang sungai per luas DTA"),
        ("Frekuensi sungai (Fs)", drainage.get("stream_frequency_per_km2"), "sungai/km²", "Jumlah sungai Strahler per luas DTA"),
        ("Rasio percabangan (Rb)", drainage.get("bifurcation_ratio"), "-", "Rata-rata rasio jumlah sungai antar orde berurutan"),
        ("Tekstur drainase (Dt)", drainage.get("drainage_texture_per_km"), "sungai/km", "Jumlah sungai per keliling DTA"),
        ("Jumlah percabangan", drainage.get("junction_count"), "percabangan", "Titik pertemuan sedikitnya dua ruas sungai"),
        ("Kerapatan percabangan", drainage.get("junction_density_per_km2"), "percabangan/km²", "Jumlah percabangan per luas DTA"),
        ("Orde sungai maksimum (Strahler)", drainage.get("stream_order_max"), "-", "Orde Strahler tertinggi dalam DTA"),
        ("Jumlah sungai (Nu)", drainage.get("stream_count"), "sungai", "Jumlah sungai Strahler dalam DTA"),
        ("Panjang sungai rata-rata (Lm)", drainage.get("mean_stream_length_km"), "km", "Panjang total dibagi jumlah sungai"),
    ]
    # Tampilkan jumlah ruas per orde sebagai nilai sumber agar rasio percabangan di Excel dapat diaudit.
    def _order_key(value: Any) -> int:
        text = str(value).strip()
        # Pair keys are stored as ``1-2``, ``2-3``, etc.  For a bifurcation ratio
        # the row label must use the first order only, not concatenate both digits.
        head = text.split("-", 1)[0]
        digits = "".join(ch for ch in head if ch.isdigit())
        if not digits:
            digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits or 0)
    for order, count in sorted(order_counts.items(), key=lambda item: _order_key(item[0])):
        values.append((f"Jumlah sungai orde {_order_key(order)}", count, "sungai", "Jumlah sungai Strahler pada orde tersebut"))
    for pair, ratio in sorted(rb_by_order.items(), key=lambda item: _order_key(item[0])):
        first = _order_key(pair)
        values.append((f"Rasio percabangan orde {first}", ratio, "-", f"Jumlah sungai orde {first} dibagi orde {first + 1}"))
    values.extend([
        ("CN rata-rata tertimbang (CN-II)", cn.get("weighted_cn_ii"), "-", (cn.get("interpretations") or {}).get("weighted_cn")),
        ("Retensi potensial (S)", cn.get("potential_retention_mm"), "mm", (cn.get("interpretations") or {}).get("retention")),
        ("Luas area CN ≥ 80", cn.get("high_cn_pct"), "%", (cn.get("interpretations") or {}).get("high_cn_area")),
        ("Nilai CN tidak valid", cn.get("invalid_pct"), "%", "Nilai di luar rentang CN yang digunakan"),
    ])
    return [["Parameter", "Nilai", "Satuan", "Interpretasi"], *[list(item) for item in values]]


def create_characteristics_workbook(results: list[dict[str, Any]], output_path: Path) -> Path:
    if not results:
        raise ValueError("Tidak ada hasil DTA untuk diekspor")
    if len(results) != 1:
        raise ValueError("Satu workbook hanya boleh memuat satu DTA")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = results[0]
    analysis = result.get("hydrologic_analysis") or {}
    summary = analysis.get("executive_summary") or {}
    name = result.get("label") or result.get("point_id") or "DTA"
    rows: list[list[Any]] = [
        ["KARAKTERISTIK DAERAH TANGKAPAN AIR"],
        [name],
        ["Kelas respons", summary.get("response_class")],
        ["Ringkasan Eksekutif", summary.get("narrative")],
        [], ["Indikator Kunci"], ["Parameter", "Nilai", "Satuan"],
    ]
    rows.extend([[item.get("label"), item.get("value"), item.get("unit")] for item in analysis.get("key_indicator_items") or []])
    rows.extend([[], ["Karakteristik Wilayah"]])
    rows.extend([[f"Paragraf {index}", paragraph] for index, paragraph in enumerate(analysis.get("territory_paragraphs") or [], 1)])
    rows.extend([[], ["Topografi, Morfometri, Jaringan Drainase, CN, dan Waktu Konsentrasi"], _parameter_rows(result)[0]])
    rows.extend(_parameter_rows(result)[1:])
    rows.extend([[], ["Distribusi Kelas Lereng"], ["Kelas", "Persentase luas (%)"]])
    slope_labels = {"Datar": "Datar (0–8%)", "Landai": "Landai (>8–15%)", "Agak curam": "Agak curam (>15–25%)", "Curam": "Curam (>25–40%)", "Sangat curam": "Sangat curam (>40%)"}
    rows.extend([[slope_labels.get(item.get("class"), item.get("class")), item.get("area_pct")] for item in ((analysis.get("terrain") or {}).get("slope") or {}).get("distribution") or []])
    rows.extend([[], ["Penutupan Lahan"], ["Kode PL", "Kelas penggunaan lahan", "Luas (km²)", "Persentase luas (%)"]])
    rows.extend([[str(item.get("code") or ""), item.get("name"), item.get("area_km2"), item.get("area_pct")] for item in (analysis.get("landcover") or {}).get("classes") or []])
    rows.extend([[], ["Sistem Lahan"], ["Tipe sistem lahan", "Fisiografi", "Relief", "Luas (km²)", "Persentase luas (%)"]])
    rows.extend([[item.get("land_type"), item.get("physiography"), item.get("relief_class"), item.get("area_km2"), item.get("area_pct")] for item in (analysis.get("landsystem") or {}).get("classes") or []])
    rows.extend([[], ["Distribusi Curve Number"], ["Kelas", "Persentase luas (%)"]])
    rows.extend([[item.get("class"), item.get("area_pct")] for item in (analysis.get("curve_number") or {}).get("distribution") or []])
    rows.extend([[], ["Waktu Konsentrasi"], ["Metode", "Estimasi (jam)", "Keterangan"]])
    tc = analysis.get("time_of_concentration") or {}
    rows.extend([[item.get("label"), item.get("value_hours"), item.get("reason")] for item in tc.get("methods") or [] if isinstance(item.get("value_hours"), (int, float)) and math.isfinite(float(item.get("value_hours"))) and float(item.get("value_hours")) > 0])
    rows.append(["Tc Representatif", tc.get("representative_hours") or tc.get("recommended_hours"), f"Dasar: {', '.join(tc.get('representative_methods') or tc.get('recommendation_methods') or [])}. Kesepakatan antar-metode: {tc.get('method_agreement') or tc.get('confidence') or 'Rendah'}. {tc.get('representative_basis') or tc.get('recommendation_basis') or ''}"])

    # Pertahankan hubungan perhitungan utama sebagai formula Excel, bukan hanya angka hasil.
    row_by_label = {str(row[0]): idx for idx, row in enumerate(rows, 1) if row and isinstance(row[0], str)}
    def ref(label: str, column: str = "B") -> str | None:
        row_no = row_by_label.get(label)
        return f"{column}{row_no}" if row_no else None
    def formula(label: str, expression: str | None) -> None:
        row_no = row_by_label.get(label)
        if not row_no or not expression:
            return
        current = rows[row_no - 1][1] if len(rows[row_no - 1]) > 1 else None
        cached = float(current) if isinstance(current, (int, float)) and math.isfinite(float(current)) else None
        rows[row_no - 1][1] = ExcelFormula(expression, cached)

    A, P, L = ref("Luas DTA (A)"), ref("Keliling (P)"), ref("Lintasan aliran terpanjang (L)")
    R = ref("Relief DTA (R)")
    Lt, Nu, JN = ref("Panjang total sungai (Lt)"), ref("Jumlah sungai (Nu)"), ref("Jumlah percabangan")
    if A and L:
        formula("Faktor bentuk (Ff)", f"{A}/({L}^2)")
        formula("Rasio elongasi (Re)", f"(2*SQRT({A}/PI()))/{L}")
    if A and P:
        formula("Rasio kebulatan (Rc)", f"4*PI()*{A}/({P}^2)")
    if R and L:
        formula("Rasio relief (RR)", f"{R}/({L}*1000)")
    if Lt and A:
        formula("Kerapatan drainase (Dd)", f"{Lt}/{A}")
    if Nu and A:
        formula("Frekuensi sungai (Fs)", f"{Nu}/{A}")
    if Nu and P:
        formula("Tekstur drainase (Dt)", f"{Nu}/{P}")
    if JN and A:
        formula("Kerapatan percabangan", f"{JN}/{A}")
    if Lt and Nu:
        formula("Panjang sungai rata-rata (Lm)", f"{Lt}/{Nu}")
    cn_ref = ref("CN rata-rata tertimbang (CN-II)")
    if cn_ref:
        formula("Retensi potensial (S)", f"25400/{cn_ref}-254")
    rb_formula_refs = []
    for label, row_no in list(row_by_label.items()):
        if not label.startswith("Rasio percabangan orde "):
            continue
        try:
            order = int(label.rsplit(" ", 1)[-1])
        except ValueError:
            continue
        n1 = ref(f"Jumlah sungai orde {order}")
        n2 = ref(f"Jumlah sungai orde {order + 1}")
        if n1 and n2:
            formula(label, f"{n1}/{n2}")
            rb_ref = ref(label)
            if rb_ref:
                rb_formula_refs.append(rb_ref)
    if rb_formula_refs:
        formula("Rasio percabangan (Rb)", f"AVERAGE({','.join(rb_formula_refs)})")

    section_titles = {1: 3, 2: 3}
    for row_index, row in enumerate(rows, 1):
        if row and row[0] in {"Indikator Kunci", "Karakteristik Wilayah", "Topografi, Morfometri, Jaringan Drainase, CN, dan Waktu Konsentrasi", "Distribusi Kelas Lereng", "Distribusi Curve Number", "Waktu Konsentrasi", "Sistem Lahan", "Penutupan Lahan"}:
            section_titles[row_index] = 1
        if row and row[0] in {"Parameter", "Kelas", "Metode", "Tipe sistem lahan", "Kode PL"}:
            section_titles[row_index] = 1
    sheets = [("Karakteristik DTA", _worksheet_xml(rows, widths=[54, 72, 24, 21, 23], row_styles=section_titles, freeze_row=2))]
    content_overrides = "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1))
    sheet_entries = "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1))
    relationships = "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
    styles_id = len(sheets) + 1
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", f'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{content_overrides}</Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{sheet_entries}</sheets><calcPr calcId="191029" fullCalcOnLoad="1" forceFullCalc="1"/></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relationships}<Relationship Id="rId{styles_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        archive.writestr("xl/styles.xml", '<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="0.0000"/></numFmts><fonts count="3"><font><sz val="10"/><name val="Aptos"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Aptos"/></font><font><b/><color rgb="FF223468"/><sz val="15"/><name val="Aptos Display"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF223468"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="2"><border/><border><bottom style="thin"><color rgb="FFD5DCE8"/></bottom></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="justify" vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/><xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="justify" vertical="top" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for index, (_, xml) in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", xml)
    return output_path
