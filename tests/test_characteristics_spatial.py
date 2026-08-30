from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point, box, mapping
from shapely.ops import transform
from pyproj import Transformer

from api.services.characteristics_spatial import characteristic_grouped_frames
from api.services.hydrologic_analysis import analysis_stream_metrics, build_hydrologic_analysis


def test_characteristic_line_export_includes_main_channel():
    analysis = {
        "characteristic_spatial": {
            "crs": "EPSG:4326",
            "MAIN_CHANNEL": {
                "type": "Feature",
                "properties": {
                    "parameter": "MAIN_CHANNEL",
                    "label": "Panjang sungai utama (Lm)",
                    "description": "Panjang sungai utama (Lm) dari outlet ke hulu",
                    "value": 38.8,
                    "unit": "km",
                },
                "geometry": mapping(LineString([(110.0, -7.0), (110.2, -6.9)])),
            },
            "L": {
                "type": "Feature",
                "properties": {
                    "parameter": "L",
                    "label": "L",
                    "value": 42.2,
                    "unit": "km",
                },
                "geometry": mapping(LineString([(110.0, -7.0), (110.25, -6.85)])),
            },
        }
    }
    frames = characteristic_grouped_frames(
        analysis,
        point_id="O1",
        label="Kranggan",
        target_crs="EPSG:4326",
    )
    lines = frames["GARIS"]
    assert set(lines["PARAM"]) == {"MAIN_CHANNEL", "L"}
    main = lines.loc[lines["PARAM"] == "MAIN_CHANNEL"].iloc[0]
    assert main["KETERANGAN"] == "Panjang sungai utama (Lm) dari outlet ke hulu"
    assert float(main["NILAI"]) == 38.8


def test_analysis_stream_metrics_exposes_main_channel_spatial(tmp_path: Path):
    stream_path = tmp_path / "streams.gpkg"
    streams = gpd.GeoDataFrame(
        [
            {
                "LINKNO": 1,
                "USLINKNO1": 2,
                "USLINKNO2": -1,
                "DSLINKNO": -1,
                "strmOrder": 2,
                "Slope": 0.01,
                "geometry": LineString([(0.0, 0.0), (1000.0, 0.0)]),
            },
            {
                "LINKNO": 2,
                "USLINKNO1": -1,
                "USLINKNO2": -1,
                "DSLINKNO": 1,
                "strmOrder": 1,
                "Slope": 0.02,
                "geometry": LineString([(1000.0, 0.0), (2000.0, 0.0)]),
            },
        ],
        crs="EPSG:32749",
    )
    streams.to_file(stream_path, driver="GPKG")

    result = analysis_stream_metrics(
        box(-10.0, -100.0, 2010.0, 100.0),
        Point(0.0, 0.0),
        "EPSG:32749",
        stream_path,
        area_km2=2.0,
    )
    feature = result["main_channel_spatial"]
    assert result["main_channel_length_km"] == 2.0
    assert feature is not None
    assert feature["properties"]["parameter"] == "MAIN_CHANNEL"
    assert feature["properties"]["value"] == 2.0
    assert feature["geometry"]["type"] == "LineString"



def test_main_channel_prefers_branch_aligned_with_canonical_l(tmp_path: Path):
    """A longer tributary must not steal Lm when canonical L follows another branch."""
    stream_path = tmp_path / "streams-branch.gpkg"
    streams = gpd.GeoDataFrame(
        [
            {"LINKNO": 1, "USLINKNO1": 2, "USLINKNO2": 3, "DSLINKNO": -1, "strmOrder": 2, "Slope": 0.01,
             "geometry": LineString([(0.0, 0.0), (1000.0, 0.0)])},
            # Canonical-L branch: slightly shorter overall but follows L eastward.
            {"LINKNO": 2, "USLINKNO1": 4, "USLINKNO2": -1, "DSLINKNO": 1, "strmOrder": 1, "Slope": 0.01,
             "geometry": LineString([(1000.0, 0.0), (2500.0, 0.0)])},
            {"LINKNO": 4, "USLINKNO1": -1, "USLINKNO2": -1, "DSLINKNO": 2, "strmOrder": 1, "Slope": 0.01,
             "geometry": LineString([(2500.0, 0.0), (3500.0, 0.0)])},
            # Longer competing tributary diverges north at the confluence.
            {"LINKNO": 3, "USLINKNO1": -1, "USLINKNO2": -1, "DSLINKNO": 1, "strmOrder": 1, "Slope": 0.01,
             "geometry": LineString([(1000.0, 0.0), (1000.0, 3000.0)])},
        ],
        crs="EPSG:32749",
    )
    streams.to_file(stream_path, driver="GPKG")

    canonical_l_metric = LineString([(0.0, 0.0), (3800.0, 0.0)])
    to_wgs84 = Transformer.from_crs("EPSG:32749", "EPSG:4326", always_xy=True)
    canonical_l_web = transform(to_wgs84.transform, canonical_l_metric)
    characteristic_spatial = {
        "L": {
            "type": "Feature",
            "properties": {"parameter": "L", "value": 3.8, "unit": "km"},
            "geometry": mapping(canonical_l_web),
        }
    }

    result = analysis_stream_metrics(
        box(-50.0, -100.0, 3900.0, 3100.0),
        Point(0.0, 0.0),
        "EPSG:32749",
        stream_path,
        area_km2=10.0,
        gama_reference_spatial=characteristic_spatial,
    )

    assert result["main_channel_linknos"] == [1, 2, 4]
    assert result["main_channel_length_km"] == 3.5
    assert result["main_channel_reference_aligned"] is True
    assert result["main_channel_reference_fit"] > 0.7


def test_main_channel_progress_ignores_far_tributary_projection(tmp_path: Path):
    """A far tributary must not win merely because its XY projection reaches far along L."""
    stream_path = tmp_path / "streams-far-projection.gpkg"
    streams = gpd.GeoDataFrame(
        [
            {"LINKNO": 1, "USLINKNO1": 2, "USLINKNO2": 3, "DSLINKNO": -1, "strmOrder": 2, "Slope": 0.01,
             "geometry": LineString([(0.0, 0.0), (1000.0, 0.0)])},
            # Correct branch is slightly offset from raster L but keeps advancing along it.
            {"LINKNO": 2, "USLINKNO1": 4, "USLINKNO2": -1, "DSLINKNO": 1, "strmOrder": 1, "Slope": 0.01,
             "geometry": LineString([(1000.0, 0.0), (1400.0, 600.0), (2800.0, 600.0)])},
            {"LINKNO": 4, "USLINKNO1": -1, "USLINKNO2": -1, "DSLINKNO": 2, "strmOrder": 1, "Slope": 0.01,
             "geometry": LineString([(2800.0, 600.0), (3800.0, 600.0)])},
            # Wrong branch is much longer and its far endpoint projects near the head of L,
            # but most of the reach is kilometres away from the canonical corridor.
            {"LINKNO": 3, "USLINKNO1": -1, "USLINKNO2": -1, "DSLINKNO": 1, "strmOrder": 1, "Slope": 0.01,
             "geometry": LineString([(1000.0, 0.0), (1600.0, 0.0), (1600.0, 4000.0), (3600.0, 4000.0)])},
        ],
        crs="EPSG:32749",
    )
    streams.to_file(stream_path, driver="GPKG")

    canonical_l_metric = LineString([(0.0, 0.0), (4000.0, 0.0)])
    to_wgs84 = Transformer.from_crs("EPSG:32749", "EPSG:4326", always_xy=True)
    canonical_l_web = transform(to_wgs84.transform, canonical_l_metric)
    characteristic_spatial = {
        "L": {
            "type": "Feature",
            "properties": {"parameter": "L", "value": 4.0, "unit": "km"},
            "geometry": mapping(canonical_l_web),
        }
    }

    result = analysis_stream_metrics(
        box(-50.0, -100.0, 4100.0, 4200.0),
        Point(0.0, 0.0),
        "EPSG:32749",
        stream_path,
        area_km2=10.0,
        gama_reference_spatial=characteristic_spatial,
    )

    assert result["main_channel_linknos"] == [1, 2, 4]
    assert result["main_channel_reference_aligned"] is True
    assert result["main_channel_reference_progress"] > 0.85


def test_build_analysis_merges_main_channel_into_characteristic_spatial(tmp_path: Path):
    stream_path = tmp_path / "streams-analysis.gpkg"
    analysis_streams = gpd.GeoDataFrame(
        [
            {"LINKNO": 1, "USLINKNO1": 2, "USLINKNO2": -1, "DSLINKNO": -1, "strmOrder": 2, "Slope": 0.01,
             "geometry": LineString([(0.0, 0.0), (1000.0, 0.0)])},
            {"LINKNO": 2, "USLINKNO1": -1, "USLINKNO2": -1, "DSLINKNO": 1, "strmOrder": 1, "Slope": 0.02,
             "geometry": LineString([(1000.0, 0.0), (2000.0, 0.0)])},
        ], crs="EPSG:32749",
    )
    analysis_streams.to_file(stream_path, driver="GPKG")
    base_streams = gpd.GeoDataFrame(
        [{"linkno": 1, "length_m": 1000.0, "slope": 0.01, "strm_order": 1,
          "geometry": LineString([(0.0, 0.0), (1000.0, 0.0)])}],
        crs="EPSG:32749",
    )
    result = build_hydrologic_analysis(
        geom=box(-10.0, -100.0, 2010.0, 100.0), outlet=Point(0.0, 0.0),
        source_crs="EPSG:32749", area_km2=2.0, streams=base_streams,
        upstream_ids={1}, upstream_by_downstream={}, outlet_linkno=1,
        dem_path=None, plen_path=None, analysis_stream_path=stream_path,
    )
    spatial = result["characteristic_spatial"]
    assert spatial is not None
    assert spatial["crs"] == "EPSG:4326"
    assert spatial["MAIN_CHANNEL"]["properties"]["parameter"] == "MAIN_CHANNEL"
    assert "main_channel_spatial" not in result["drainage"]


def test_raster_main_channel_is_thresholded_subset_of_plen_flowpath(tmp_path: Path):
    """Lm follows canonical plen/D8 L and stops at the 0.15 km² channel threshold."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from api.services.hydrologic_analysis import _main_channel_from_plen_threshold

    fdir_path = tmp_path / "flowdir.tif"
    plen_path = tmp_path / "plen.tif"
    transform_grid = from_origin(0.0, 30.0, 30.0, 30.0)
    width = 200
    flowdir = np.ones((1, width), dtype=np.uint8)  # every cell drains east
    plen = (np.arange(1, width + 1, dtype=np.float32) * 30.0).reshape(1, width)
    profile = {
        "driver": "GTiff", "height": 1, "width": width, "count": 1,
        "crs": "EPSG:32749", "transform": transform_grid,
    }
    with rasterio.open(fdir_path, "w", dtype="uint8", nodata=0, **profile) as ds:
        ds.write(flowdir, 1)
    with rasterio.open(plen_path, "w", dtype="float32", nodata=-9999.0, **profile) as ds:
        ds.write(plen, 1)

    # Cell area = 900 m², therefore ceil(150,000 / 900) = 167 cells.
    geom = box(0.0, 0.0, 6000.0, 30.0)
    outlet = Point(5985.0, 15.0)
    result = _main_channel_from_plen_threshold(
        geom, outlet, "EPSG:32749", fdir_path, plen_path, None, threshold_km2=0.15,
    )

    assert result is not None
    assert result["main_channel_threshold_cells"] == 167
    assert result["main_channel_threshold_km2"] == 0.15
    # Full L is ~5.97 km, while the channelized part begins at the 167-cell threshold.
    assert 0.95 <= result["main_channel_length_km"] <= 1.05
    assert result["main_channel_method"] == "plen + D8 dengan ambang luas kontribusi"
    assert result["main_channel_spatial"]["properties"]["threshold_cells"] == 167
