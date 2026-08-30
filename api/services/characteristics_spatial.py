"""Spatial export helpers for DTA Characteristic analysis."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape


_PARAMETER_LABELS = {
    "MAIN_CHANNEL": "Panjang sungai utama (Lm)",
    "L": "Lintasan aliran terpanjang (L)",
    "LCA": "Lintasan aliran melalui sentroid (Lca)",
    "L10_85": "Lintasan aliran 10–85 (L10–85)",
    "L10": "Titik 10% lintasan L",
    "L85": "Titik 85% lintasan L",
    "C": "Titik sentroid (C)",
}


def _drop_all_empty_columns(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
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
        "PARAM": parameter,
        "KETERANGAN": props.get("description") or _PARAMETER_LABELS.get(parameter, parameter),
        "NILAI": props.get("value"),
        "SATUAN": props.get("unit") or "",
        "SUMBER": source,
        "geometry": geometry,
    }
    frame = gpd.GeoDataFrame([row], geometry="geometry", crs=source_crs)
    if target_crs and str(frame.crs).upper() != str(target_crs).upper():
        frame = frame.to_crs(target_crs)
    return _source_last(_drop_all_empty_columns(frame))


def _merge(parts: list[gpd.GeoDataFrame]) -> gpd.GeoDataFrame | None:
    if not parts:
        return None
    frame = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True, sort=False), geometry="geometry", crs=parts[0].crs)
    return _source_last(_drop_all_empty_columns(frame))


def characteristic_spatial_frames(
    analysis: dict[str, Any] | None,
    *,
    point_id: str,
    label: str,
    source: str | None = None,
    target_crs: str = "EPSG:32749",
) -> dict[str, gpd.GeoDataFrame]:
    """Backward-compatible one-frame-per-parameter helper."""
    spatial = (analysis or {}).get("characteristic_spatial") or {}
    source_crs = spatial.get("crs") or "EPSG:4326"
    frames: dict[str, gpd.GeoDataFrame] = {}
    for parameter in ("MAIN_CHANNEL", "L", "LCA", "L10_85", "L10", "L85", "C"):
        frame = _feature_frame(spatial.get(parameter), point_id=point_id, label=label, source=source,
                               source_crs=source_crs, target_crs=target_crs, parameter=parameter)
        if frame is not None:
            frames[parameter] = frame
    return frames


def characteristic_grouped_frames(
    analysis: dict[str, Any] | None,
    *,
    point_id: str,
    label: str,
    source: str | None = None,
    target_crs: str = "EPSG:32749",
) -> dict[str, gpd.GeoDataFrame]:
    """Group Characteristic audit geometry into line and point layers."""
    frames = characteristic_spatial_frames(
        analysis, point_id=point_id, label=label, source=source, target_crs=target_crs,
    )
    lines = _merge([frames[key] for key in ("MAIN_CHANNEL", "L", "LCA", "L10_85") if key in frames])
    points = _merge([frames[key] for key in ("C", "L10", "L85") if key in frames])
    result: dict[str, gpd.GeoDataFrame] = {}
    if lines is not None and not lines.empty:
        result["GARIS"] = lines
    if points is not None and not points.empty:
        result["TITIK"] = points
    return result


def clipped_analysis_streams(
    stream_path: Path | None,
    dta_geometry,
    dta_crs: Any,
    *,
    target_crs: str = "EPSG:32749",
    source: str | None = None,
) -> gpd.GeoDataFrame | None:
    """Return ``streams_analysis`` clipped to the final DTA geometry.

    Source attributes, including ``strmOrder``, are preserved because this layer is
    the auditable Strahler network used by Characteristic calculations. ``SUMBER``
    is appended using the same copyright/processtime string as the DTA export.
    """
    if stream_path is None or not Path(stream_path).exists() or dta_geometry is None or dta_geometry.is_empty:
        return None
    frame = gpd.read_file(stream_path)
    if frame.empty or frame.crs is None:
        return None
    target = gpd.GeoSeries([dta_geometry], crs=dta_crs)
    if str(target.crs) != str(frame.crs):
        target = target.to_crs(frame.crs)
    geom = target.iloc[0]
    selected = frame.loc[frame.intersects(geom)].copy()
    if selected.empty:
        return None
    selected["geometry"] = selected.geometry.intersection(geom)
    selected = selected[selected.geometry.notna() & ~selected.geometry.is_empty].copy()
    if selected.empty:
        return None
    try:
        selected["CLIP_LEN_M"] = selected.geometry.length.astype(float)
    except Exception:
        pass
    if source:
        selected["SUMBER"] = source
    if target_crs and str(selected.crs).upper() != str(target_crs).upper():
        selected = selected.to_crs(target_crs)
    return _source_last(_drop_all_empty_columns(gpd.GeoDataFrame(selected, geometry="geometry", crs=selected.crs)))
