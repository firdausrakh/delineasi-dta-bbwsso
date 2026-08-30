"""Spatial helpers for auditable HSS Gama-I source parameters.

The web map consumes the exact Gama-I GeoJSON produced by the Characteristic
analysis.  Downloads are grouped by geometry type so one DTA produces a compact
set of audit layers instead of one file per parameter.
"""
from __future__ import annotations

from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape


_PARAMETER_LABELS = {
    "AU": "Luas bagian hulu (AU)",
    "WL": "Lebar DTA pada 1/4 L (WL)",
    "WU": "Lebar DTA pada 3/4 L (WU)",
    "A": "Titik A (0,25 L)",
    "B": "Titik B (0,75 L)",
    "C": "Titik C (ujung Lca)",
    "XA": "Garis X-A",
    "XB": "Garis X-B",
    "X_LCA": "Garis X-C",
}

# Legacy construction groups are retained for compatibility with callers/tests,
# while the download pipeline uses ``gama1_grouped_frames`` below.
_CONSTRUCTION_GROUPS = {
    "TITIK_KONTROL": ("X", "A", "B", "C"),
    "SUMBU_KONSTRUKSI": ("XA", "XB", "X_LCA"),
    "GARIS_TEGAK_LURUS": ("WL_PERP", "WU_PERP", "AU_DIVIDER"),
    "SIMBOL_TEGAK_LURUS": ("PERP_A", "PERP_B", "PERP_AU"),
}


def _drop_all_empty_columns(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Drop attributes that contain no usable value in the whole layer."""
    if frame is None or frame.empty:
        return frame
    keep: list[str] = []
    for column in frame.columns:
        if column == frame.geometry.name:
            keep.append(column)
            continue
        series = frame[column]
        useful = series.map(lambda value: value is not None and not (isinstance(value, float) and pd.isna(value)) and str(value).strip() != "").any()
        if useful:
            keep.append(column)
    return gpd.GeoDataFrame(frame[keep].copy(), geometry=frame.geometry.name, crs=frame.crs)



def _source_last(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Keep SUMBER as the last visible attribute (immediately before geometry)."""
    if frame is None or frame.empty or "SUMBER" not in frame.columns:
        return frame
    geom_col = frame.geometry.name
    attrs = [column for column in frame.columns if column not in {"SUMBER", geom_col}]
    ordered = attrs + ["SUMBER", geom_col]
    return gpd.GeoDataFrame(frame[ordered].copy(), geometry=geom_col, crs=frame.crs)

def _feature_frame(
    feature: dict[str, Any] | None,
    *,
    point_id: str,
    label: str,
    source: str | None,
    source_crs: str,
    target_crs: str,
    parameter: str,
    description: str | None = None,
    export_parameter: str | None = None,
) -> gpd.GeoDataFrame | None:
    geometry_payload = feature.get("geometry") if isinstance(feature, dict) else None
    if not geometry_payload:
        return None
    try:
        geometry = shape(geometry_payload)
    except (TypeError, ValueError):
        return None
    if geometry.is_empty:
        return None
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    row = {
        "ID": point_id,
        "NAMA": label,
        "PARAM": export_parameter or parameter,
        "KETERANGAN": props.get("description") or description or _PARAMETER_LABELS.get(parameter, parameter),
        "NILAI": props.get("value"),
        "SATUAN": props.get("unit") or "",
        "SUMBER": source,
        "geometry": geometry,
    }
    frame = gpd.GeoDataFrame([row], geometry="geometry", crs=source_crs)
    if target_crs and str(frame.crs).upper() != str(target_crs).upper():
        frame = frame.to_crs(target_crs)
    return _source_last(_drop_all_empty_columns(frame))


def _merge_frames(parts: list[gpd.GeoDataFrame]) -> gpd.GeoDataFrame | None:
    if not parts:
        return None
    crs = parts[0].crs
    merged = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True, sort=False), geometry="geometry", crs=crs)
    return _source_last(_drop_all_empty_columns(merged))


def gama1_spatial_frames(
    hss_payload: dict[str, Any] | None,
    *,
    point_id: str,
    label: str,
    source: str | None = None,
    target_crs: str = "EPSG:32749",
) -> dict[str, gpd.GeoDataFrame]:
    """Backward-compatible one-frame-per-result helper for AU/WL/WU."""
    payload = hss_payload or {}
    spatial = payload.get("gama1_spatial") or {}
    source_crs = spatial.get("crs") or "EPSG:4326"
    frames: dict[str, gpd.GeoDataFrame] = {}
    for parameter in ("AU", "WL", "WU"):
        frame = _feature_frame(
            spatial.get(parameter), point_id=point_id, label=label, source=source,
            source_crs=source_crs, target_crs=target_crs, parameter=parameter,
            description=_PARAMETER_LABELS[parameter],
        )
        if frame is not None:
            frames[parameter] = frame
    return frames


def gama1_construction_frames(
    hss_payload: dict[str, Any] | None,
    *,
    point_id: str,
    label: str,
    source: str | None = None,
    target_crs: str = "EPSG:32749",
) -> dict[str, gpd.GeoDataFrame]:
    """Backward-compatible grouped construction helper."""
    payload = hss_payload or {}
    spatial = payload.get("gama1_spatial") or {}
    construction = spatial.get("construction") or {}
    source_crs = spatial.get("crs") or "EPSG:4326"
    frames: dict[str, gpd.GeoDataFrame] = {}
    for group_name, parameters in _CONSTRUCTION_GROUPS.items():
        group_parts: list[gpd.GeoDataFrame] = []
        for parameter in parameters:
            frame = _feature_frame(
                construction.get(parameter), point_id=point_id, label=label, source=source,
                source_crs=source_crs, target_crs=target_crs, parameter=parameter,
            )
            if frame is not None:
                group_parts.append(frame)
        merged = _merge_frames(group_parts)
        if merged is not None:
            frames[group_name] = merged
    return frames


def gama1_grouped_frames(
    hss_payload: dict[str, Any] | None,
    *,
    point_id: str,
    label: str,
    source: str | None = None,
    target_crs: str = "EPSG:32749",
) -> dict[str, gpd.GeoDataFrame]:
    """Return exactly three compact Gama-I layers: area, line and point.

    * ``AREA``: AU.
    * ``GARIS``: WL, WU and the three reference axes X-A, X-B, X-C.
    * ``TITIK``: A, B and C.  Outlet X is already exported as the DTA outlet.

    Perpendicular helper lines/symbols are intentionally not exported because WL,
    WU and the AU divider already encode those results and the user requested the
    visible construction to consist only of X-A, X-B and X-C.
    """
    payload = hss_payload or {}
    spatial = payload.get("gama1_spatial") or {}
    construction = spatial.get("construction") or {}
    source_crs = spatial.get("crs") or "EPSG:4326"

    area_parts: list[gpd.GeoDataFrame] = []
    line_parts: list[gpd.GeoDataFrame] = []
    point_parts: list[gpd.GeoDataFrame] = []

    au = _feature_frame(spatial.get("AU"), point_id=point_id, label=label, source=source,
                        source_crs=source_crs, target_crs=target_crs, parameter="AU",
                        description=_PARAMETER_LABELS["AU"])
    if au is not None:
        area_parts.append(au)

    for parameter in ("WL", "WU"):
        frame = _feature_frame(spatial.get(parameter), point_id=point_id, label=label, source=source,
                               source_crs=source_crs, target_crs=target_crs, parameter=parameter,
                               description=_PARAMETER_LABELS[parameter])
        if frame is not None:
            line_parts.append(frame)
    for parameter, export_parameter in (("XA", "XA"), ("XB", "XB"), ("X_LCA", "XC")):
        frame = _feature_frame(construction.get(parameter), point_id=point_id, label=label, source=source,
                               source_crs=source_crs, target_crs=target_crs, parameter=parameter,
                               export_parameter=export_parameter)
        if frame is not None:
            line_parts.append(frame)

    for parameter in ("A", "B", "C"):
        frame = _feature_frame(construction.get(parameter), point_id=point_id, label=label, source=source,
                               source_crs=source_crs, target_crs=target_crs, parameter=parameter)
        if frame is not None:
            point_parts.append(frame)

    result: dict[str, gpd.GeoDataFrame] = {}
    for name, parts in (("AREA", area_parts), ("GARIS", line_parts), ("TITIK", point_parts)):
        merged = _merge_frames(parts)
        if merged is not None and not merged.empty:
            result[name] = merged
    return result
