"""Synthetic unit hydrograph (HSS) calculations for one delineated DTA.

The service consumes the already-computed hydrologic/morphometric analysis so HSS
calculation does not repeat watershed delineation or raster processing. All methods
return a common schema and include a 1 mm volume-conservation diagnostic.
"""
from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np

FORMULA_PROFILE = "SNI_2415_2026"
UNIT_RUNOFF_MM = 1.0

# SNI 2415:2026 Table 2: dimensionless SCS Curvilinear ordinates.
# Values between tabulated points are linearly interpolated for the adaptive time grid.
SCS_T_RATIO = np.asarray([
    0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9,
    1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0, 2.2,
    2.4, 2.6, 2.8, 3.0, 3.5, 4.0, 4.5, 5.0,
], dtype=float)
SCS_Q_RATIO = np.asarray([
    0.000, 0.015, 0.075, 0.160, 0.280, 0.430, 0.600, 0.770, 0.890, 0.970,
    1.000, 0.980, 0.920, 0.840, 0.750, 0.660, 0.560, 0.420, 0.320, 0.240,
    0.180, 0.130, 0.098, 0.075, 0.036, 0.018, 0.009, 0.004,
], dtype=float)

METHOD_LABELS = {
    "scs": "NRCS / SCS",
    "nakayasu": "Nakayasu",
    "snyder_alexeyev": "Snyder–Alexeyev",
    "gama1": "Gama I",
    "limantara": "Limantara",
    "itb1b": "ITB-1b",
    "itb2b": "ITB-2b",
}

DEFAULT_PARAMETERS: dict[str, dict[str, float]] = {
    "scs": {"Ct": 1.0},
    "nakayasu": {"alpha": 2.0},
    "snyder_alexeyev": {"Ct": 1.0, "Cp": 1.0},
    "gama1": {},
    "limantara": {"n": 0.05},
    "itb1b": {"Ct": 1.0, "Cp": 1.0, "alpha": 3.7, "k": 10.0},
    "itb2b": {"Ct": 1.0, "Cp": 1.0, "alpha": 1.7, "beta": 0.84, "k": 10.0},
}


def _finite(value: Any, *, positive: bool = False) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if positive and number <= 0:
        return None
    return number


def _param(params: dict[str, Any], key: str, default: float, *, lo: float | None = None,
           hi: float | None = None) -> float:
    value = _finite(params.get(key))
    if value is None:
        value = float(default)
    if lo is not None:
        value = max(float(lo), value)
    if hi is not None:
        value = min(float(hi), value)
    return value


def _inputs(analysis: dict[str, Any]) -> dict[str, float | None]:
    morph = analysis.get("morphometry") or {}
    terrain = analysis.get("terrain") or {}
    drainage = analysis.get("drainage") or {}
    flow_slope = terrain.get("flowpath_slope") or {}
    gama = drainage.get("gama1") or {}
    area = _finite(morph.get("area_km2"), positive=True)
    main_length = _finite(drainage.get("main_channel_length_km"), positive=True)
    longest = _finite(terrain.get("longest_flow_path_km"), positive=True)
    centroid = _finite(terrain.get("centroidal_flowpath_km"), positive=True)
    # L and Lc must refer to one consistent outlet-to-upstream path. Protect HSS from
    # stale/legacy analyses where a tiny clipped reach was stored as the main channel.
    use_flowpath_fallback = bool(longest and (main_length is None or (centroid and main_length < centroid)))
    if use_flowpath_fallback:
        main_length = longest
    slope_pct = _finite(drainage.get("main_channel_slope_pct"), positive=True)
    if slope_pct is None or use_flowpath_fallback:
        slope_pct = _finite(flow_slope.get("longest_flowpath_pct"), positive=True) or slope_pct
    return {
        "A": area,
        "L": main_length or longest,
        "Lc": centroid,
        "S": (slope_pct / 100.0) if slope_pct is not None else None,
        # Source morphometry retained explicitly for editable HSS inputs.
        "Lt": _finite(drainage.get("total_stream_length_km"), positive=True),
        "L1": _finite(gama.get("source_stream_length_km")),
        "N": _finite(drainage.get("stream_count"), positive=True),
        "N1": _finite(gama.get("source_stream_count")),
        "WU": _finite(gama.get("width_upstream_km"), positive=True),
        "WL": _finite(gama.get("width_lower_km"), positive=True),
        "AU": _finite(gama.get("upstream_area_km2"), positive=True),
        "D": _finite(drainage.get("drainage_density_km_per_km2"), positive=True),
        "JN": _finite(drainage.get("junction_count"), positive=True),
        "SF": _finite(gama.get("source_factor"), positive=True),
        "SN": _finite(gama.get("source_frequency"), positive=True),
        "WF": _finite(gama.get("width_factor"), positive=True),
        "RUA": _finite(gama.get("relative_upstream_area"), positive=True),
        "SIM": _finite(gama.get("symmetry_factor"), positive=True),
    }




def _apply_input_overrides(inputs: dict[str, float | None], overrides: dict[str, Any] | None) -> tuple[dict[str, float | None], dict[str, float]]:
    """Apply editable source metrics, then recompute dependent Gama-I parameters.

    Derived parameters (D, SF, SN, WF, RUA, SIM) are intentionally never accepted
    directly from the client. This keeps the UI auditable: users edit source metrics
    such as Lt, L1, WU, WL, AU, while dependent ratios follow automatically.
    """
    raw = overrides or {}
    clean: dict[str, float] = {}
    bounds = {
        "A": (1e-9, None), "L": (1e-9, None), "Lc": (1e-9, None), "S_pct": (1e-9, None),
        "Lt": (1e-9, None), "L1": (0.0, None), "N": (1.0, None), "N1": (0.0, None),
        "JN": (1e-9, None), "WU": (1e-9, None), "WL": (1e-9, None), "AU": (1e-9, None),
    }
    for key, (lo, hi) in bounds.items():
        value = _finite(raw.get(key))
        if value is None:
            continue
        if lo is not None and value < lo:
            continue
        if hi is not None and value > hi:
            continue
        clean[key] = float(value)

    result = dict(inputs)
    for key in ("A", "L", "Lc", "JN", "Lt", "L1", "N", "N1", "WU", "WL", "AU"):
        if key in clean:
            result[key] = clean[key]
    if "S_pct" in clean:
        result["S"] = clean["S_pct"] / 100.0

    area = _finite(result.get("A"), positive=True)
    # Prefer user-edited source measurements, otherwise use unmodified extracted source
    # measurements when available. If a legacy payload contains only the derived Gama-I
    # ratios, leave those ratios untouched rather than recomputing from rounded values.
    lt = _finite(result.get("Lt"), positive=True)
    l1 = _finite(result.get("L1"))
    n = _finite(result.get("N"), positive=True)
    n1 = _finite(result.get("N1"))
    wu = _finite(result.get("WU"), positive=True)
    wl = _finite(result.get("WL"), positive=True)
    au = _finite(result.get("AU"), positive=True)
    if area is not None and lt is not None:
        result["D"] = lt / area
    if lt is not None and lt > 0 and l1 is not None:
        result["SF"] = l1 / lt
    if n is not None and n > 0 and n1 is not None:
        result["SN"] = n1 / n
    wf_recomputed = False
    rua_recomputed = False
    if wu is not None and wl is not None and wl > 0:
        result["WF"] = wu / wl
        wf_recomputed = True
    if area is not None and area > 0 and au is not None:
        result["RUA"] = au / area
        rua_recomputed = True
    wf = _finite(result.get("WF"), positive=True)
    rua = _finite(result.get("RUA"), positive=True)
    if (wf_recomputed or rua_recomputed) and wf is not None and rua is not None:
        result["SIM"] = wf * rua
    return result, clean

def _adaptive_dt(tp: float, tr: float = 1.0) -> float:
    # At least ~20 samples to peak, while avoiding impractically fine output.
    return max(0.05, min(1.0, tr, tp / 20.0))


def _time_grid(t_end: float, dt: float, extras: tuple[float, ...] = ()) -> np.ndarray:
    if not math.isfinite(t_end) or t_end <= 0:
        return np.asarray([0.0], dtype=float)
    grid = np.arange(0.0, t_end + dt * 0.5, dt, dtype=float)
    values = [grid]
    for extra in extras:
        if math.isfinite(extra) and 0.0 < extra < t_end:
            values.append(np.asarray([extra], dtype=float))
    values.append(np.asarray([t_end], dtype=float))
    return np.unique(np.round(np.concatenate(values), 10))


def _volume(time_h: np.ndarray, discharge: np.ndarray) -> float:
    if len(time_h) < 2:
        return 0.0
    x_seconds = time_h * 3600.0
    trapezoid = getattr(np, "trapezoid", None)
    if trapezoid is not None:
        return float(trapezoid(discharge, x_seconds))
    return float(np.trapz(discharge, x_seconds))  # NumPy 1.26 compatibility


def _pack(method: str, inputs: dict[str, Any], params: dict[str, Any], time_h: np.ndarray,
          discharge: np.ndarray, *, tp: float, qp: float, tb: float | None,
          extra: dict[str, Any] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    area = float(inputs["A"])
    target_volume = area * UNIT_RUNOFF_MM * 1000.0
    volume = _volume(time_h, discharge)
    runoff = volume / (area * 1000.0) if area > 0 else None
    error = ((volume - target_volume) / target_volume * 100.0) if target_volume > 0 else None
    factor = (target_volume / volume) if volume > 0 else 1.0
    normalized = discharge * factor
    q_ratio = discharge / qp if qp > 0 else np.zeros_like(discharge)
    payload = {
        "method": method,
        "label": METHOD_LABELS[method],
        "formula_profile": FORMULA_PROFILE,
        "unit_runoff_mm": UNIT_RUNOFF_MM,
        "parameters": {k: round(float(v), 8) for k, v in params.items() if _finite(v) is not None},
        "inputs": {k: (round(float(v), 8) if _finite(v) is not None else None) for k, v in inputs.items()},
        "Tp_hours": round(float(tp), 6),
        "Qp_m3s": round(float(qp), 6),
        "Tb_hours": round(float(tb), 6) if tb is not None and math.isfinite(float(tb)) else None,
        "dt_hours": round(float(np.min(np.diff(time_h))), 6) if len(time_h) > 1 else None,
        "volume_target_m3": round(target_volume, 3),
        "volume_m3": round(volume, 3),
        "equivalent_runoff_mm": round(float(runoff), 6) if runoff is not None else None,
        "volume_error_pct": round(float(error), 4) if error is not None else None,
        "normalization_factor": round(float(factor), 8),
        "ordinates": [
            {
                "time_hours": round(float(t), 6),
                "t_over_tp": round(float(t / tp), 6) if tp > 0 else None,
                "q_over_qp": round(float(qr), 8),
                "discharge_m3s": round(float(q), 8),
                "normalized_discharge_m3s": round(float(qn), 8),
            }
            for t, q, qn, qr in zip(time_h, discharge, normalized, q_ratio)
        ],
        "warnings": list(warnings or []),
    }
    if extra:
        payload["derived"] = extra
    return payload


def _require(method: str, inputs: dict[str, Any], names: tuple[str, ...]) -> list[str]:
    missing = [name for name in names if _finite(inputs.get(name), positive=True) is None]
    return [f"Parameter {name} belum tersedia untuk {METHOD_LABELS[method]}." for name in missing]


def _scs(inputs: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    warnings = _require("scs", inputs, ("A", "L", "Lc"))
    if warnings:
        return {"method": "scs", "label": METHOD_LABELS["scs"], "available": False, "warnings": warnings}
    ct = _param(raw, "Ct", 1.0, lo=0.05, hi=10.0)
    tr = _param(raw, "Tr", 1.0, lo=0.05, hi=24.0)
    lag = ct * (float(inputs["L"]) * float(inputs["Lc"])) ** 0.3
    tp = lag + 0.5 * tr
    tb = 5.0 * tp
    qp = 0.2083 * float(inputs["A"]) * UNIT_RUNOFF_MM / tp
    dt = _adaptive_dt(tp, tr)
    t = _time_grid(tb, dt, (tp,))
    ratio = np.interp(t / tp, SCS_T_RATIO, SCS_Q_RATIO, left=0.0, right=0.0)
    result = _pack("scs", inputs, {"Ct": ct, "Tr": tr}, t, qp * ratio, tp=tp, qp=qp, tb=tb,
                   extra={"lag_hours": round(lag, 6)})
    result["available"] = True
    return result


def _nakayasu(inputs: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    warnings = _require("nakayasu", inputs, ("A", "L"))
    if warnings:
        return {"method": "nakayasu", "label": METHOD_LABELS["nakayasu"], "available": False, "warnings": warnings}
    alpha = _param(raw, "alpha", 2.0, lo=0.2, hi=10.0)
    tr = _param(raw, "Tr", 1.0, lo=0.05, hi=24.0)
    length = float(inputs["L"])
    tg = 0.5279 + 0.058 * length if length >= 15.0 else 0.21 * length ** 0.7
    tp = tg + 0.8 * tr
    t03 = alpha * tg
    qp = float(inputs["A"]) * UNIT_RUNOFF_MM / (3.6 * (0.3 * tp + t03))
    tb = tp + 8.5 * t03
    dt = _adaptive_dt(tp, tr)
    t = _time_grid(tb, dt, (tp, tp + t03, tp + 2.5 * t03))
    q = np.zeros_like(t)
    rise = t <= tp
    q[rise] = qp * np.power(np.clip(t[rise] / tp, 0.0, None), 2.4)
    r1 = (t > tp) & (t <= tp + t03)
    q[r1] = qp * np.power(0.3, (t[r1] - tp) / t03)
    r2 = (t > tp + t03) & (t <= tp + 2.5 * t03)
    q[r2] = qp * np.power(0.3, (t[r2] - tp + 0.5 * t03) / (1.5 * t03))
    r3 = t > tp + 2.5 * t03
    q[r3] = qp * np.power(0.3, (t[r3] - tp + 1.5 * t03) / (2.0 * t03))
    result = _pack("nakayasu", inputs, {"alpha": alpha, "Tr": tr}, t, q, tp=tp, qp=qp, tb=tb,
                   extra={"Tg_hours": round(tg, 6), "T0_3_hours": round(t03, 6)})
    result["available"] = True
    return result


def _snyder(inputs: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    warnings = _require("snyder_alexeyev", inputs, ("A", "L", "Lc"))
    if warnings:
        return {"method": "snyder_alexeyev", "label": METHOD_LABELS["snyder_alexeyev"], "available": False, "warnings": warnings}
    ct = _param(raw, "Ct", 1.0, lo=0.05, hi=10.0)
    cp = _param(raw, "Cp", 1.0, lo=0.05, hi=5.0)
    tr = _param(raw, "Tr", 1.0, lo=0.05, hi=24.0)
    lag = ct * (float(inputs["L"]) * float(inputs["Lc"])) ** 0.3
    te = lag / 5.5
    if te > tr:
        tp = lag + 0.25 * (tr - te)
        timing_case = "Te > Tr"
    else:
        tp = lag + 0.5 * tr
        timing_case = "Te <= Tr"
    tp = max(0.05, tp)
    qp = 0.275 * cp * float(inputs["A"]) * UNIT_RUNOFF_MM / tp
    target = float(inputs["A"]) * UNIT_RUNOFF_MM * 1000.0
    lam = qp * tp * 3600.0 / target
    a = 1.32 * lam * lam + 0.15 * lam + 0.045
    tb = 10.0 * tp
    dt = _adaptive_dt(tp, tr)
    t = _time_grid(tb, dt, (tp,))
    x = t / tp
    ratio = np.zeros_like(t)
    positive = x > 0
    ratio[positive] = np.power(10.0, -a * np.square(1.0 - x[positive]) / x[positive])
    q = qp * ratio
    result = _pack(
        "snyder_alexeyev", inputs, {"Ct": ct, "Cp": cp, "Tr": tr}, t, q, tp=tp, qp=qp, tb=tb,
        extra={"lag_hours": round(lag, 6), "standard_rain_duration_hours": round(te, 6),
               "timing_case": timing_case, "alexeyev_lambda": round(lam, 8),
               "alexeyev_a": round(a, 8)},
    )
    result["available"] = True
    return result


def _gama1(inputs: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    del raw
    required = ("A", "L", "S", "D", "JN", "SF", "SN", "WF", "RUA", "SIM")
    warnings = _require("gama1", inputs, required)
    if warnings:
        return {"method": "gama1", "label": METHOD_LABELS["gama1"], "available": False, "warnings": warnings}
    A, L, S, D = (float(inputs[k]) for k in ("A", "L", "S", "D"))
    JN, SF, SN, RUA, SIM = (float(inputs[k]) for k in ("JN", "SF", "SN", "RUA", "SIM"))
    trise = 0.43 * (L / (100.0 * SF)) ** 3 + 1.0665 * SIM + 1.2775
    qp = 0.1836 * A ** 0.5886 * JN ** 0.2381 * trise ** -0.4008
    tb = 27.4132 * trise ** 0.1457 * S ** -0.0956 * SN ** 0.7344 * RUA ** 0.2574
    k_storage = 0.5617 * A ** 0.1798 * S ** -0.1446 * SF ** -1.0897 * D ** 0.0452
    tb = max(tb, trise + 0.05)
    dt = _adaptive_dt(trise, 1.0)
    t = _time_grid(tb, dt, (trise,))
    q = np.zeros_like(t)
    rise = t <= trise
    q[rise] = qp * np.clip(t[rise] / trise, 0.0, 1.0)
    recession = t > trise
    q[recession] = qp * np.exp(-(t[recession] - trise) / k_storage)
    result = _pack(
        "gama1", inputs, {}, t, q, tp=trise, qp=qp, tb=tb,
        extra={
            "TR_hours": round(trise, 6),
            "TR_equals_Tp": True,
            "K_hours": round(k_storage, 6),
            "global_Tr_used": False,
        },
    )
    result["available"] = True
    return result


def _limantara(inputs: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    warnings = _require("limantara", inputs, ("A", "L", "Lc", "S"))
    if warnings:
        return {"method": "limantara", "label": METHOD_LABELS["limantara"], "available": False, "warnings": warnings}
    n = _param(raw, "n", 0.05, lo=0.005, hi=0.5)
    tr = _param(raw, "Tr", 1.0, lo=0.05, hi=24.0)
    A, L, Lc, S = (float(inputs[k]) for k in ("A", "L", "Lc", "S"))
    qp = 0.042 * A ** 0.451 * L ** 0.497 * Lc ** 0.356 * S ** -0.131 * n ** 0.168
    tg = 0.5279 + 0.058 * L if L >= 15.0 else 0.21 * L ** 0.7
    tp = tg + 0.8 * tr
    # q/Qp = 10^(0.175(Tp-t)); stop once q/Qp <= 0.001.
    recession_hours = 3.0 / 0.175
    tb = tp + recession_hours
    dt = _adaptive_dt(tp, tr)
    t = _time_grid(tb, dt, (tp,))
    q = np.zeros_like(t)
    rise = t <= tp
    q[rise] = qp * np.power(np.clip(t[rise] / tp, 0.0, None), 1.107)
    rec = t > tp
    q[rec] = qp * np.power(10.0, 0.175 * (tp - t[rec]))
    result = _pack("limantara", inputs, {"n": n, "Tr": tr}, t, q, tp=tp, qp=qp, tb=tb,
                   extra={"Tg_hours": round(tg, 6)})
    result["available"] = True
    return result


def _itb1b(inputs: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    warnings = _require("itb1b", inputs, ("A", "L"))
    if warnings:
        return {"method": "itb1b", "label": METHOD_LABELS["itb1b"], "available": False, "warnings": warnings}
    ct = _param(raw, "Ct", 1.0, lo=0.05, hi=10.0)
    cp = _param(raw, "Cp", 1.0, lo=0.05, hi=5.0)
    alpha = _param(raw, "alpha", 3.7, lo=0.1, hi=20.0)
    tr = _param(raw, "Tr", 1.0, lo=0.05, hi=24.0)
    k = _param(raw, "k", 10.0, lo=5.0, hi=20.0)
    lag = ct * 0.81225 * float(inputs["L"]) ** 0.6
    tp = lag + 0.5 * tr
    m = alpha * cp
    ahss = math.exp(m + math.lgamma(m + 1.0) - (m + 1.0) * math.log(m))
    kp = 1.0 / (3.6 * ahss)
    qp = kp * UNIT_RUNOFF_MM * float(inputs["A"]) / tp
    tb = k * tp
    dt = _adaptive_dt(tp, tr)
    t = _time_grid(tb, dt, (tp,))
    x = t / tp
    base = np.clip(x * np.exp(1.0 - x), 0.0, None)
    q = qp * np.power(base, m)
    result = _pack(
        "itb1b", inputs, {"Ct": ct, "Cp": cp, "alpha": alpha, "Tr": tr, "k": k}, t, q,
        tp=tp, qp=qp, tb=tb,
        extra={"lag_hours": round(lag, 6), "shape_exponent": round(m, 8),
               "dimensionless_area": round(ahss, 8), "peak_rate_factor": round(kp, 8)},
    )
    result["available"] = True
    return result


def _itb2b(inputs: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    warnings = _require("itb2b", inputs, ("A", "L"))
    if warnings:
        return {"method": "itb2b", "label": METHOD_LABELS["itb2b"], "available": False, "warnings": warnings}
    ct = _param(raw, "Ct", 1.0, lo=0.05, hi=10.0)
    cp = _param(raw, "Cp", 1.0, lo=0.05, hi=5.0)
    alpha = _param(raw, "alpha", 1.7, lo=0.1, hi=20.0)
    beta = _param(raw, "beta", 0.84, lo=0.05, hi=10.0)
    tr = _param(raw, "Tr", 1.0, lo=0.05, hi=24.0)
    k = _param(raw, "k", 10.0, lo=5.0, hi=20.0)
    length = float(inputs["L"])
    lag = ct * (0.0394 * length + 0.201 * math.sqrt(length))
    tp = lag + 0.5 * tr
    nshape = beta * cp
    ahss = 1.0 / (alpha + 1.0) + 1.0 / nshape
    kp = 1.0 / (3.6 * ahss)
    qp = kp * UNIT_RUNOFF_MM * float(inputs["A"]) / tp
    tb = k * tp
    dt = _adaptive_dt(tp, tr)
    t = _time_grid(tb, dt, (tp,))
    x = t / tp
    ratio = np.where(x <= 1.0, np.power(np.clip(x, 0.0, None), alpha), np.exp((1.0 - x) * nshape))
    q = qp * ratio
    result = _pack(
        "itb2b", inputs, {"Ct": ct, "Cp": cp, "alpha": alpha, "beta": beta, "Tr": tr, "k": k},
        t, q, tp=tp, qp=qp, tb=tb,
        extra={"lag_hours": round(lag, 6), "recession_exponent": round(nshape, 8),
               "dimensionless_area": round(ahss, 8), "peak_rate_factor": round(kp, 8)},
    )
    result["available"] = True
    return result


_CALCULATORS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "scs": _scs,
    "nakayasu": _nakayasu,
    "snyder_alexeyev": _snyder,
    "gama1": _gama1,
    "limantara": _limantara,
    "itb1b": _itb1b,
    "itb2b": _itb2b,
}


def calculate_hss(*, point_id: str, label: str | None, hydrologic_analysis: dict[str, Any],
                  methods: list[str] | None = None, parameters: dict[str, dict[str, Any]] | None = None,
                  input_overrides: dict[str, Any] | None = None, global_tr_hours: float = 1.0) -> dict[str, Any]:
    """Calculate selected HSS methods from one DTA analysis payload.

    The equations are unchanged from the previous engine. Global Tr is injected into
    every method that uses rainfall duration, while editable morphometric source
    parameters are applied before dependent Gama-I ratios are recomputed.
    """
    base_inputs = _inputs(hydrologic_analysis or {})
    inputs, clean_overrides = _apply_input_overrides(base_inputs, input_overrides)
    tr = _finite(global_tr_hours, positive=True) or 1.0
    tr = max(0.05, min(24.0, tr))
    method_keys = [m for m in (methods or list(_CALCULATORS)) if m in _CALCULATORS]
    if not method_keys:
        raise ValueError("Pilih minimal satu metode HSS.")
    parameter_map = parameters or {}
    results = []
    for method in method_keys:
        merged = dict(DEFAULT_PARAMETERS.get(method, {}))
        if isinstance(parameter_map.get(method), dict):
            merged.update({k: v for k, v in parameter_map[method].items() if k != "Tr"})
        if method != "gama1":
            merged["Tr"] = tr
        try:
            results.append(_CALCULATORS[method](inputs, merged))
        except (ArithmeticError, OverflowError, ValueError) as exc:
            results.append({
                "method": method, "label": METHOD_LABELS[method], "available": False,
                "warnings": [f"Perhitungan {METHOD_LABELS[method]} gagal: {exc}"],
            })
    available = [item for item in results if item.get("available")]
    return {
        "schema_version": 2,
        "point_id": point_id,
        "label": label or point_id,
        "formula_profile": FORMULA_PROFILE,
        "unit_runoff_mm": UNIT_RUNOFF_MM,
        "global_tr_hours": round(tr, 8),
        "input_overrides": clean_overrides,
        "inputs": inputs,
        "methods": results,
        "available_method_count": len(available),
        "requested_method_count": len(method_keys),
    }
