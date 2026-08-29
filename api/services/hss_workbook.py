"""Excel export for one DTA synthetic unit hydrograph analysis.

The workbook is intentionally auditable: source morphometry and calibration values are
kept as editable numeric cells, while dependent morphometric parameters and the main
HSS equations are exported as real Excel formulas with cached backend values.
"""
from __future__ import annotations

import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from api.services.characteristics_workbook import ExcelFormula, _worksheet_xml
from api.services.hss_analysis import SCS_Q_RATIO, SCS_T_RATIO


METHOD_ORDER = ["scs", "nakayasu", "snyder_alexeyev", "gama1", "limantara", "itb1b", "itb2b"]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_sheet_name(value: Any, used: set[str]) -> str:
    text = str(value or "HSS")
    for char in "[]:*?/\\":
        text = text.replace(char, "-")
    text = " ".join(text.split()).strip(" '") or "HSS"
    base = text[:31]
    name = base
    suffix = 2
    while name.lower() in used:
        tail = f"-{suffix}"
        name = f"{base[:31-len(tail)]}{tail}"
        suffix += 1
    used.add(name.lower())
    return name


def _sheet_formula_name(name: str) -> str:
    return "'" + str(name).replace("'", "''") + "'"


@dataclass
class _BuiltMethodSheet:
    name: str
    rows: list[list[Any]]
    refs: dict[str, int]
    method: dict[str, Any]


class _Rows:
    def __init__(self) -> None:
        self.rows: list[list[Any]] = []
        self.refs: dict[str, int] = {}

    def add(self, label: Any = None, *values: Any, ref: str | None = None) -> int:
        row = [label, *values] if label is not None else []
        self.rows.append(row)
        idx = len(self.rows)
        key = ref or (str(label) if isinstance(label, str) and label else None)
        if key:
            self.refs[key] = idx
        return idx

    def blank(self) -> int:
        return self.add(None)

    def b(self, key: str, *, absolute: bool = True) -> str | None:
        row = self.refs.get(key)
        if not row:
            return None
        return f"$B${row}" if absolute else f"B{row}"

    def set_b_formula(self, key: str, expression: str | None, cached: Any) -> None:
        row = self.refs.get(key)
        if not row or not expression:
            return
        while len(self.rows[row - 1]) < 2:
            self.rows[row - 1].append(None)
        self.rows[row - 1][1] = ExcelFormula(expression, _finite(cached))


def _source_values(payload: dict[str, Any], method: dict[str, Any]) -> dict[str, float | None]:
    """Return editable morphometric source values, reconstructing only safe identities."""
    raw = payload.get("input_overrides") or {}
    inputs = method.get("inputs") or payload.get("inputs") or {}

    def raw_or(key: str, fallback: Any = None) -> float | None:
        value = _finite(raw.get(key))
        return value if value is not None else _finite(fallback)

    A = raw_or("A", inputs.get("A"))
    L = raw_or("L", inputs.get("L"))
    Lc = raw_or("Lc", inputs.get("Lc"))
    S_pct = raw_or("S_pct", (_finite(inputs.get("S")) or 0.0) * 100.0 if _finite(inputs.get("S")) is not None else None)
    JN = raw_or("JN", inputs.get("JN"))
    Lt = raw_or("Lt", inputs.get("Lt"))
    D = _finite(inputs.get("D"))
    if Lt is None and A is not None and D is not None:
        Lt = A * D
    L1 = raw_or("L1", inputs.get("L1"))
    SF = _finite(inputs.get("SF"))
    if L1 is None and Lt is not None and SF is not None:
        L1 = Lt * SF
    N = raw_or("N", inputs.get("N"))
    N1 = raw_or("N1", inputs.get("N1"))
    SN = _finite(inputs.get("SN"))
    if N1 is None and N is not None and SN is not None:
        N1 = N * SN
    WU = raw_or("WU", inputs.get("WU"))
    WL = raw_or("WL", inputs.get("WL"))
    AU = raw_or("AU", inputs.get("AU"))
    RUA = _finite(inputs.get("RUA"))
    if AU is None and A is not None and RUA is not None:
        AU = A * RUA
    return {
        "A": A, "L": L, "Lc": Lc, "S_pct": S_pct, "Lt": Lt, "L1": L1,
        "N": N, "N1": N1, "JN": JN, "WU": WU, "WL": WL, "AU": AU,
    }


def _sheet_styles(rows: list[list[Any]]) -> dict[int, int]:
    styles = {1: 3}
    sections = {
        "Parameter Morfometri Sumber", "Parameter Turunan Otomatis", "Koefisien / Parameter Metode",
        "Parameter Perhitungan", "Hasil Utama", "Catatan", "Ordinat HSS", "Ringkasan Metode",
        "Kurva Tak Berdimensi SCS", "Metode yang Belum Dapat Dihitung",
    }
    headers = {"Parameter", "Metode", "Waktu (jam)"}
    for idx, row in enumerate(rows, 1):
        if row and row[0] in sections:
            styles[idx] = 1
        elif row and row[0] in headers:
            styles[idx] = 1
    return styles


def _build_method_sheet(payload: dict[str, Any], method: dict[str, Any], sheet_name: str) -> _BuiltMethodSheet:
    b = _Rows()
    inputs = method.get("inputs") or {}
    params = method.get("parameters") or {}
    derived = method.get("derived") or {}
    source = _source_values(payload, method)
    unit_runoff = _finite(payload.get("unit_runoff_mm")) or _finite(method.get("unit_runoff_mm")) or 1.0
    global_tr = _finite(payload.get("global_tr_hours")) or 1.0
    method_id = str(method.get("method") or "")

    b.add(f"HSS {method.get('label') or method.get('method')}")
    b.add("Profil persamaan", method.get("formula_profile") or payload.get("formula_profile"))
    b.add("Hujan efektif satuan", ExcelFormula("'Ringkasan'!$B$3", unit_runoff), "mm", ref="UnitRunoff")
    if method_id == "gama1":
        b.add("Durasi hujan efektif global (Tr)", ExcelFormula("'Ringkasan'!$B$4", global_tr), "jam", "Informasi global; tidak digunakan dalam persamaan HSS Gama I")
    else:
        b.add("Durasi hujan efektif global (Tr)", ExcelFormula("'Ringkasan'!$B$4", global_tr), "jam", ref="Tr")
    b.blank()
    b.add("Parameter Morfometri Sumber")
    b.add("Parameter", "Nilai", "Satuan", "Keterangan")
    source_rows = [
        ("A", "Luas DTA (A)", "km²", "Luas DTA yang digunakan pada HSS"),
        ("L", "Panjang alur utama (L)", "km", "Panjang alur utama untuk perhitungan HSS"),
        ("Lc", "Panjang alur menuju sentroid (Lc)", "km", "Panjang alur dari outlet menuju proyeksi sentroid"),
        ("S_pct", "Kemiringan alur utama (%)", "%", "Kemiringan dalam persen; S desimal dihitung otomatis"),
        ("Lt", "Panjang total sungai (Lt)", "km", "Nilai sumber kerapatan drainase dan faktor sumber"),
        ("L1", "Panjang sungai orde 1 (L1)", "km", "Nilai sumber faktor sumber Gama I"),
        ("N", "Jumlah segmen sungai (N)", "segmen", "Nilai sumber frekuensi sumber Gama I"),
        ("N1", "Jumlah sungai orde 1 (N1)", "segmen", "Nilai sumber frekuensi sumber Gama I"),
        ("JN", "Jumlah percabangan (JN)", "percabangan", "Jumlah pertemuan jaringan sungai"),
        ("WU", "Lebar DTA pada 3/4 L (WU)", "km", "Nilai sumber faktor lebar Gama I"),
        ("WL", "Lebar DTA pada 1/4 L (WL)", "km", "Nilai sumber faktor lebar Gama I"),
        ("AU", "Luas bagian hulu (AU)", "km²", "Nilai sumber luas relatif hulu Gama I"),
    ]
    for key, label, unit, note in source_rows:
        b.add(label, source.get(key), unit, note, ref=key)

    b.blank()
    b.add("Parameter Turunan Otomatis")
    b.add("Parameter", "Nilai", "Satuan", "Rumus")
    b.add("Kemiringan alur utama (S)", inputs.get("S"), "-", "S(%) / 100", ref="S")
    b.add("Kerapatan drainase (D)", inputs.get("D"), "km/km²", "Lt / A", ref="D")
    b.add("Faktor sumber (SF)", inputs.get("SF"), "-", "L1 / Lt", ref="SF")
    b.add("Frekuensi sumber (SN)", inputs.get("SN"), "-", "N1 / N", ref="SN")
    b.add("Faktor lebar (WF)", inputs.get("WF"), "-", "WU / WL", ref="WF")
    b.add("Luas relatif hulu (RUA)", inputs.get("RUA"), "-", "AU / A", ref="RUA")
    b.add("Faktor simetri (SIM)", inputs.get("SIM"), "-", "WF x RUA", ref="SIM")
    b.set_b_formula("S", f"{b.b('S_pct')}/100" if b.b("S_pct") else None, inputs.get("S"))
    b.set_b_formula("D", f"{b.b('Lt')}/{b.b('A')}" if b.b("Lt") and b.b("A") else None, inputs.get("D"))
    b.set_b_formula("SF", f"{b.b('L1')}/{b.b('Lt')}" if b.b("L1") and b.b("Lt") else None, inputs.get("SF"))
    b.set_b_formula("SN", f"{b.b('N1')}/{b.b('N')}" if b.b("N1") and b.b("N") else None, inputs.get("SN"))
    b.set_b_formula("WF", f"{b.b('WU')}/{b.b('WL')}" if b.b("WU") and b.b("WL") else None, inputs.get("WF"))
    b.set_b_formula("RUA", f"{b.b('AU')}/{b.b('A')}" if b.b("AU") and b.b("A") else None, inputs.get("RUA"))
    b.set_b_formula("SIM", f"{b.b('WF')}*{b.b('RUA')}" if b.b("WF") and b.b("RUA") else None, inputs.get("SIM"))

    b.blank()
    b.add("Koefisien / Parameter Metode")
    b.add("Parameter", "Nilai", "Satuan", "Keterangan")
    param_refs: dict[str, str] = {}
    for key, value in params.items():
        if key == "Tr":
            continue
        row = b.add(str(key), value, "-", "Koefisien/parameter metode", ref=f"param:{key}")
        param_refs[key] = f"$B${row}"

    b.blank()
    b.add("Parameter Perhitungan")
    b.add("Parameter", "Nilai", "Satuan", "Keterangan")

    A, L, Lc, S = b.b("A"), b.b("L"), b.b("Lc"), b.b("S")
    D, JN, SF, SN, RUA, SIM = b.b("D"), b.b("JN"), b.b("SF"), b.b("SN"), b.b("RUA"), b.b("SIM")
    Tr, Re = b.b("Tr"), b.b("UnitRunoff")

    def add_calc(ref: str, label: str, cached: Any, unit: str, expr: str | None, note: str = "") -> None:
        b.add(label, cached, unit, note, ref=ref)
        b.set_b_formula(ref, expr, cached)

    # Method-specific intermediate equations. These mirror hss_analysis.py; the backend
    # remains authoritative and supplies the cached values stored with each formula.
    scs_table_rows: tuple[int, int] | None = None
    if method_id == "scs":
        Ct = param_refs.get("Ct")
        add_calc("lag", "Waktu lag (TL)", derived.get("lag_hours"), "jam", f"{Ct}*({L}*{Lc})^0.3" if Ct and L and Lc else None)
    elif method_id == "nakayasu":
        alpha = param_refs.get("alpha")
        add_calc("Tg", "Waktu lag (Tg)", derived.get("Tg_hours"), "jam", f"IF({L}>=15,0.5279+0.058*{L},0.21*{L}^0.7)" if L else None)
        add_calc("T03", "Waktu resesi T0.3", derived.get("T0_3_hours"), "jam", f"{alpha}*{b.b('Tg')}" if alpha and b.b("Tg") else None)
    elif method_id == "snyder_alexeyev":
        Ct = param_refs.get("Ct")
        add_calc("lag", "Waktu lag Snyder", derived.get("lag_hours"), "jam", f"{Ct}*({L}*{Lc})^0.3" if Ct and L and Lc else None)
        add_calc("Te", "Durasi hujan standar (Te)", derived.get("standard_rain_duration_hours"), "jam", f"{b.b('lag')}/5.5" if b.b("lag") else None)
        # These two depend on Qp/Tp, which are defined in the next section. Keep the
        # rows here for readable layout and attach their formulas after Qp/Tp refs exist.
        add_calc("lambda", "Parameter Alexeyev lambda", derived.get("alexeyev_lambda"), "-", None)
        add_calc("alex_a", "Parameter Alexeyev a", derived.get("alexeyev_a"), "-", None)
    elif method_id == "gama1":
        add_calc("TR", "Waktu naik / waktu puncak (TR = Tp)", derived.get("TR_hours"), "jam", f"0.43*({L}/(100*{SF}))^3+1.0665*{SIM}+1.2775" if L and SF and SIM else None)
        add_calc("K", "Koefisien tampungan (K)", derived.get("K_hours"), "jam", f"0.5617*{A}^0.1798*{S}^-0.1446*{SF}^-1.0897*{D}^0.0452" if A and S and SF and D else None)
    elif method_id == "limantara":
        add_calc("Tg", "Waktu lag (Tg)", derived.get("Tg_hours"), "jam", f"IF({L}>=15,0.5279+0.058*{L},0.21*{L}^0.7)" if L else None)
    elif method_id == "itb1b":
        Ct, Cp, alpha = param_refs.get("Ct"), param_refs.get("Cp"), param_refs.get("alpha")
        add_calc("lag", "Waktu lag (TL)", derived.get("lag_hours"), "jam", f"{Ct}*0.81225*{L}^0.6" if Ct and L else None)
        add_calc("shape", "Eksponen bentuk (m)", derived.get("shape_exponent"), "-", f"{alpha}*{Cp}" if alpha and Cp else None)
        add_calc("AHSS", "Luas kurva tak berdimensi", derived.get("dimensionless_area"), "-", f"EXP({b.b('shape')}+GAMMALN({b.b('shape')}+1)-({b.b('shape')}+1)*LN({b.b('shape')}))" if b.b("shape") else None)
        add_calc("Kp", "Faktor debit puncak (Kp)", derived.get("peak_rate_factor"), "-", f"1/(3.6*{b.b('AHSS')})" if b.b("AHSS") else None)
    elif method_id == "itb2b":
        Ct, Cp, beta, alpha = param_refs.get("Ct"), param_refs.get("Cp"), param_refs.get("beta"), param_refs.get("alpha")
        add_calc("lag", "Waktu lag (TL)", derived.get("lag_hours"), "jam", f"{Ct}*(0.0394*{L}+0.201*SQRT({L}))" if Ct and L else None)
        add_calc("nshape", "Eksponen resesi", derived.get("recession_exponent"), "-", f"{beta}*{Cp}" if beta and Cp else None)
        add_calc("AHSS", "Luas kurva tak berdimensi", derived.get("dimensionless_area"), "-", f"1/({alpha}+1)+1/{b.b('nshape')}" if alpha and b.b("nshape") else None)
        add_calc("Kp", "Faktor debit puncak (Kp)", derived.get("peak_rate_factor"), "-", f"1/(3.6*{b.b('AHSS')})" if b.b("AHSS") else None)

    if method_id == "scs":
        # Keep the SNI dimensionless source curve inside the workbook so each SCS ordinate
        # can remain a real interpolation formula rather than a pasted backend number.
        b.blank()
        b.add("Kurva Tak Berdimensi SCS")
        b.add("t/Tp", "Q/Qp")
        scs_first = len(b.rows) + 1
        for x_value, y_value in zip(SCS_T_RATIO.tolist(), SCS_Q_RATIO.tolist()):
            b.rows.append([float(x_value), float(y_value)])
        scs_last = len(b.rows)
        scs_table_rows = (scs_first, scs_last)

    b.blank()
    b.add("Hasil Utama")
    b.add("Parameter", "Nilai", "Satuan", "Rumus")
    b.add("Waktu puncak (Tp)", method.get("Tp_hours"), "jam", "", ref="Tp")
    b.add("Debit puncak (Qp)", method.get("Qp_m3s"), "m³/s", "", ref="Qp")
    b.add("Waktu dasar (Tb)", method.get("Tb_hours"), "jam", "", ref="Tb")
    b.add("Interval ordinat", method.get("dt_hours"), "jam", "", ref="dt")
    b.add("Volume teoritis", method.get("volume_target_m3"), "m³", "", ref="Vtarget")
    b.add("Volume HSS", method.get("volume_m3"), "m³", "integrasi trapesium ordinat", ref="Vhss")
    b.add("Limpasan ekuivalen", method.get("equivalent_runoff_mm"), "mm", "Volume HSS / (A x 1000)", ref="Runoff")
    b.add("Error volume", method.get("volume_error_pct"), "%", "(Volume HSS - Volume teoritis) / Volume teoritis x 100", ref="Error")
    b.add("Faktor normalisasi 1 mm", method.get("normalization_factor"), "-", "Volume teoritis / Volume HSS", ref="Norm")

    # Main HSS equations.
    tp_expr = qp_expr = tb_expr = None
    if method_id == "scs":
        tp_expr = f"{b.b('lag')}+0.5*{Tr}" if b.b("lag") and Tr else None
        qp_expr = f"0.2083*{A}*{Re}/{b.b('Tp')}" if A and Re and b.b("Tp") else None
        tb_expr = f"5*{b.b('Tp')}" if b.b("Tp") else None
    elif method_id == "nakayasu":
        tp_expr = f"{b.b('Tg')}+0.8*{Tr}" if b.b("Tg") and Tr else None
        qp_expr = f"{A}*{Re}/(3.6*(0.3*{b.b('Tp')}+{b.b('T03')}))" if A and Re and b.b("Tp") and b.b("T03") else None
        tb_expr = f"{b.b('Tp')}+8.5*{b.b('T03')}" if b.b("Tp") and b.b("T03") else None
    elif method_id == "snyder_alexeyev":
        Cp = param_refs.get("Cp")
        tp_expr = f"MAX(0.05,IF({b.b('Te')}>{Tr},{b.b('lag')}+0.25*({Tr}-{b.b('Te')}),{b.b('lag')}+0.5*{Tr}))" if b.b("Te") and b.b("lag") and Tr else None
        qp_expr = f"0.275*{Cp}*{A}*{Re}/{b.b('Tp')}" if Cp and A and Re and b.b("Tp") else None
        tb_expr = f"10*{b.b('Tp')}" if b.b("Tp") else None
        b.set_b_formula("lambda", f"{b.b('Qp')}*{b.b('Tp')}*3600/({A}*{Re}*1000)" if b.b("Qp") and b.b("Tp") and A and Re else None, derived.get("alexeyev_lambda"))
        b.set_b_formula("alex_a", f"1.32*{b.b('lambda')}^2+0.15*{b.b('lambda')}+0.045" if b.b("lambda") else None, derived.get("alexeyev_a"))
    elif method_id == "gama1":
        tp_expr = b.b("TR")
        qp_expr = f"0.1836*{A}^0.5886*{JN}^0.2381*{b.b('TR')}^-0.4008" if A and JN and b.b("TR") else None
        tb_expr = f"MAX(27.4132*{b.b('TR')}^0.1457*{S}^-0.0986*{SN}^0.7344*{RUA}^0.2574,{b.b('TR')}+0.05)" if b.b("TR") and S and SN and RUA else None
    elif method_id == "limantara":
        n = param_refs.get("n")
        tp_expr = f"{b.b('Tg')}+0.8*{Tr}" if b.b("Tg") and Tr else None
        qp_expr = f"0.042*{A}^0.451*{L}^0.497*{Lc}^0.356*{S}^-0.131*{n}^0.168" if A and L and Lc and S and n else None
        tb_expr = f"{b.b('Tp')}+3/0.175" if b.b("Tp") else None
    elif method_id == "itb1b":
        k = param_refs.get("k")
        tp_expr = f"{b.b('lag')}+0.5*{Tr}" if b.b("lag") and Tr else None
        qp_expr = f"{b.b('Kp')}*{Re}*{A}/{b.b('Tp')}" if b.b("Kp") and Re and A and b.b("Tp") else None
        tb_expr = f"{k}*{b.b('Tp')}" if k and b.b("Tp") else None
    elif method_id == "itb2b":
        k = param_refs.get("k")
        tp_expr = f"{b.b('lag')}+0.5*{Tr}" if b.b("lag") and Tr else None
        qp_expr = f"{b.b('Kp')}*{Re}*{A}/{b.b('Tp')}" if b.b("Kp") and Re and A and b.b("Tp") else None
        tb_expr = f"{k}*{b.b('Tp')}" if k and b.b("Tp") else None

    b.set_b_formula("Tp", tp_expr, method.get("Tp_hours"))
    b.set_b_formula("Qp", qp_expr, method.get("Qp_m3s"))
    b.set_b_formula("Tb", tb_expr, method.get("Tb_hours"))
    if b.b("Tp"):
        if method_id == "gama1":
            b.set_b_formula("dt", f"MAX(0.05,MIN(1,{b.b('Tp')}/20))", method.get("dt_hours"))
        elif Tr:
            b.set_b_formula("dt", f"MAX(0.05,MIN(1,{Tr},{b.b('Tp')}/20))", method.get("dt_hours"))
    if A and Re:
        b.set_b_formula("Vtarget", f"{A}*{Re}*1000", method.get("volume_target_m3"))

    warnings = method.get("warnings") or []
    if warnings:
        b.blank(); b.add("Catatan")
        for warning in warnings:
            b.add(str(warning))

    b.blank()
    b.add("Ordinat HSS")
    b.add("Waktu (jam)", "t/Tp", "Q/Qp", "Debit asli (m³/s)", "Debit ternormalisasi 1 mm (m³/s)")
    first_ord = len(b.rows) + 1
    ordinates = method.get("ordinates") or []
    for item in ordinates:
        row_no = len(b.rows) + 1
        time_value = _finite(item.get("time_hours"))
        ratio_cached = _finite(item.get("q_over_qp"))
        t_ratio_cached = _finite(item.get("t_over_tp"))
        discharge_cached = _finite(item.get("discharge_m3s"))
        normalized_cached = _finite(item.get("normalized_discharge_m3s"))
        time_cell = f"$A${row_no}"
        tratio_cell = f"$B${row_no}"
        ratio_expr: str | None = None
        if method_id == "scs" and scs_table_rows is not None:
            table_first, table_last = scs_table_rows
            xr = f"$A${table_first}:$A${table_last}"
            yr = f"$B${table_first}:$B${table_last}"
            last_y = f"$B${table_last}"
            match = f"MATCH({tratio_cell},{xr},1)"
            x0 = f"INDEX({xr},{match})"
            x1 = f"INDEX({xr},{match}+1)"
            y0 = f"INDEX({yr},{match})"
            y1 = f"INDEX({yr},{match}+1)"
            interp = f"{y0}+({tratio_cell}-{x0})/({x1}-{x0})*({y1}-{y0})"
            ratio_expr = f"IF({tratio_cell}<0,0,IF({tratio_cell}>=5,IF({tratio_cell}=5,{last_y},0),{interp}))"
        elif method_id == "nakayasu" and b.b("Tp") and b.b("T03"):
            ratio_expr = (
                f"IF({time_cell}<={b.b('Tp')},({time_cell}/{b.b('Tp')})^2.4,"
                f"IF({time_cell}<={b.b('Tp')}+{b.b('T03')},0.3^(({time_cell}-{b.b('Tp')})/{b.b('T03')}),"
                f"IF({time_cell}<={b.b('Tp')}+2.5*{b.b('T03')},0.3^(({time_cell}-{b.b('Tp')}+0.5*{b.b('T03')})/(1.5*{b.b('T03')})),"
                f"0.3^(({time_cell}-{b.b('Tp')}+1.5*{b.b('T03')})/(2*{b.b('T03')})))))"
            )
        elif method_id == "snyder_alexeyev" and b.b("alex_a"):
            ratio_expr = f"IF({tratio_cell}<=0,0,10^(-{b.b('alex_a')}*(1-{tratio_cell})^2/{tratio_cell}))"
        elif method_id == "gama1" and b.b("TR") and b.b("K"):
            tail_start = f"MAX({b.b('TR')},{b.b('Tb')}-1)"
            ratio_expr = (
                f"IF({time_cell}<={b.b('TR')},{time_cell}/{b.b('TR')},"
                f"IF({time_cell}<{tail_start},EXP(-({time_cell}-{b.b('TR')})/{b.b('K')}),"
                f"IF({time_cell}<={b.b('Tb')},EXP(-({tail_start}-{b.b('TR')})/{b.b('K')})*"
                f"({b.b('Tb')}-{time_cell})/({b.b('Tb')}-{tail_start}),0)))"
            )
        elif method_id == "limantara" and b.b("Tp"):
            ratio_expr = f"IF({time_cell}<={b.b('Tp')},({time_cell}/{b.b('Tp')})^1.107,10^(0.175*({b.b('Tp')}-{time_cell})))"
        elif method_id == "itb1b" and b.b("shape"):
            ratio_expr = f"({tratio_cell}*EXP(1-{tratio_cell}))^{b.b('shape')}"
        elif method_id == "itb2b" and param_refs.get("alpha") and b.b("nshape"):
            ratio_expr = f"IF({tratio_cell}<=1,{tratio_cell}^{param_refs['alpha']},EXP((1-{tratio_cell})*{b.b('nshape')}))"

        ratio_cell: Any = ExcelFormula(ratio_expr, ratio_cached) if ratio_expr else ratio_cached
        b.rows.append([
            time_value,
            ExcelFormula(f"{time_cell}/{b.b('Tp')}", t_ratio_cached) if b.b("Tp") else t_ratio_cached,
            ratio_cell,
            ExcelFormula(f"$C${row_no}*{b.b('Qp')}", discharge_cached) if b.b("Qp") else discharge_cached,
            ExcelFormula(f"$D${row_no}*{b.b('Norm')}", normalized_cached) if b.b("Norm") else normalized_cached,
        ])
    last_ord = len(b.rows)

    if ordinates and last_ord > first_ord:
        # Trapezoidal integration of the formula-driven discharge ordinates.
        volume_expr = (
            f"SUMPRODUCT(($D${first_ord+1}:$D${last_ord}+$D${first_ord}:$D${last_ord-1})/2,"
            f"($A${first_ord+1}:$A${last_ord}-$A${first_ord}:$A${last_ord-1}))*3600"
        )
        b.set_b_formula("Vhss", volume_expr, method.get("volume_m3"))
    if b.b("Vhss") and A:
        b.set_b_formula("Runoff", f"{b.b('Vhss')}/({A}*1000)", method.get("equivalent_runoff_mm"))
    if b.b("Vhss") and b.b("Vtarget"):
        b.set_b_formula("Error", f"({b.b('Vhss')}-{b.b('Vtarget')})/{b.b('Vtarget')}*100", method.get("volume_error_pct"))
        b.set_b_formula("Norm", f"{b.b('Vtarget')}/{b.b('Vhss')}", method.get("normalization_factor"))

    return _BuiltMethodSheet(sheet_name, b.rows, b.refs, method)


def _summary_rows(payload: dict[str, Any], built: list[_BuiltMethodSheet]) -> list[list[Any]]:
    b = _Rows()
    b.add("ANALISIS HIDROGRAF SATUAN SINTETIS")
    b.add(payload.get("label") or payload.get("point_id") or "DTA")
    b.add("Hujan efektif satuan", payload.get("unit_runoff_mm", 1.0), "mm")
    b.add("Durasi hujan efektif global (Tr)", payload.get("global_tr_hours", 1.0), "jam")
    b.add("Profil persamaan", payload.get("formula_profile"))
    b.blank(); b.add("Ringkasan Metode")
    b.add("Metode", "Tp (jam)", "Qp (m³/s)", "Tb (jam)", "Volume HSS (m³)", "Limpasan ekuivalen (mm)", "Error volume (%)")
    for sheet in built:
        method = sheet.method
        q = _sheet_formula_name(sheet.name)
        refs = sheet.refs
        def f(key: str, cached: Any) -> Any:
            row = refs.get(key)
            return ExcelFormula(f"{q}!$B${row}", _finite(cached)) if row else cached
        b.rows.append([
            method.get("label"), f("Tp", method.get("Tp_hours")), f("Qp", method.get("Qp_m3s")),
            f("Tb", method.get("Tb_hours")), f("Vhss", method.get("volume_m3")),
            f("Runoff", method.get("equivalent_runoff_mm")), f("Error", method.get("volume_error_pct")),
        ])
    unavailable = [m for m in payload.get("methods") or [] if not m.get("available")]
    if unavailable:
        b.blank(); b.add("Metode yang Belum Dapat Dihitung"); b.add("Metode", "Keterangan")
        for method in unavailable:
            b.rows.append([method.get("label"), "; ".join(method.get("warnings") or [])])
    return b.rows


def create_hss_workbook(payload: dict[str, Any], output_path: Path) -> Path:
    """Create one workbook per DTA, with Ringkasan + one sheet per calculated method."""
    if not payload or not payload.get("methods"):
        raise ValueError("Hasil HSS belum tersedia")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    available = [m for m in payload.get("methods") or [] if m.get("available")]
    available.sort(key=lambda item: METHOD_ORDER.index(item.get("method")) if item.get("method") in METHOD_ORDER else 999)
    used = {"ringkasan"}
    built: list[_BuiltMethodSheet] = []
    for method in available:
        name = _safe_sheet_name(method.get("label") or method.get("method") or "HSS", used)
        built.append(_build_method_sheet(payload, method, name))

    summary = _summary_rows(payload, built)
    sheets: list[tuple[str, str]] = [
        ("Ringkasan", _worksheet_xml(summary, widths=[38, 18, 18, 18, 22, 24, 20], row_styles=_sheet_styles(summary), freeze_row=2))
    ]
    for item in built:
        sheets.append((item.name, _worksheet_xml(item.rows, widths=[42, 24, 18, 48, 30], row_styles=_sheet_styles(item.rows), freeze_row=2)))

    content_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    sheet_entries = "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1))
    relationships = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    styles_id = len(sheets) + 1
    styles_xml = '<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="0.0000"/></numFmts><fonts count="3"><font><sz val="10"/><name val="Aptos"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Aptos"/></font><font><b/><color rgb="FF223468"/><sz val="15"/><name val="Aptos Display"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF223468"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="2"><border/><border><bottom style="thin"><color rgb="FFD5DCE8"/></bottom></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/><xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="left" vertical="top" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", f'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{content_overrides}</Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{sheet_entries}</sheets><calcPr calcId="191029" fullCalcOnLoad="1" forceFullCalc="1"/></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relationships}<Relationship Id="rId{styles_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        archive.writestr("xl/styles.xml", styles_xml)
        for index, (_, xml) in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", xml)
    return output_path
