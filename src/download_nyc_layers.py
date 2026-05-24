"""Download NYC constraint layers for Manhattan and save to data/raw/."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import Point, shape

# Manhattan bounding box (WGS84)
LON_MIN, LON_MAX = -74.0479, -73.9067
LAT_MIN, LAT_MAX = 40.6829, 40.8820
TARGET_CRS = "EPSG:2263"
WGS84 = "EPSG:4326"

DATASETS = {
    "bus_stops": {
        "url": "https://data.cityofnewyork.us/resource/t4f2-8md7.json",
        "filename": "bus_stops.gpkg",
        "note": "NYC Bus Stop Shelters (replaces MTA 2ucp-7wg5 / legacy erm2-nwe9)",
    },
    "hydrants": {
        "url": "https://data.cityofnewyork.us/resource/5bgh-vtsn.json",
        "filename": "hydrants.gpkg",
    },
    "bike_lanes": {
        "url": "https://data.cityofnewyork.us/resource/mzxg-pwib.json",
        "filename": "bike_lanes.gpkg",
        "note": "NYC Bike Routes (replaces retired dataset s5uu-3ajy)",
    },
    "loading_zones": {
        "url": "https://data.cityofnewyork.us/resource/nfid-uabd.json",
        "filename": "loading_zones.gpkg",
        "note": "Parking Regulation Locations and Signs (replaces pvqr-7yc4 violations dataset)",
    },
}


def _fetch_socrata(url: str, params: dict[str, Any] | None = None, page_size: int = 50_000) -> list[dict]:
    """Paginate through a Socrata JSON endpoint."""
    rows: list[dict] = []
    offset = 0
    base_params = dict(params or {})

    while True:
        query = {**base_params, "$limit": page_size, "$offset": offset}
        request_url = f"{url}?{urllib.parse.urlencode(query)}"
        with urllib.request.urlopen(request_url, timeout=180) as response:
            batch = json.load(response)

        if isinstance(batch, dict) and batch.get("error"):
            raise RuntimeError(f"Socrata error for {url}: {batch.get('message', batch)}")

        if not batch:
            break

        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    return rows


def _print_summary(name: str, gdf: gpd.GeoDataFrame) -> None:
    print(f"\n=== {name} ===")
    print(f"shape: {gdf.shape}")
    print(f"crs: {gdf.crs}")
    print(f"geometry type: {gdf.geometry.geom_type.value_counts().to_dict()}")
    print(gdf.head(2))


def filter_manhattan_bbox(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf_wgs84 = gdf.to_crs(WGS84) if gdf.crs and gdf.crs.to_string() != WGS84 else gdf
    bounds = gdf_wgs84.geometry.bounds
    in_bbox = (
        bounds["minx"].between(LON_MIN, LON_MAX)
        & bounds["maxx"].between(LON_MIN, LON_MAX)
        & bounds["miny"].between(LAT_MIN, LAT_MAX)
        & bounds["maxy"].between(LAT_MIN, LAT_MAX)
    )
    return gdf_wgs84.loc[in_bbox].copy()


def load_bus_stops() -> gpd.GeoDataFrame:
    where = "boro_name = 'Manhattan'"
    rows = _fetch_socrata(DATASETS["bus_stops"]["url"], {"$where": where})

    features = []
    for row in rows:
        geom = row.get("the_geom")
        if geom:
            geometry = shape(geom)
        elif row.get("latitude") and row.get("longitude"):
            geometry = Point(float(row["longitude"]), float(row["latitude"]))
        else:
            continue
        props = {k: v for k, v in row.items() if k != "the_geom"}
        features.append({"geometry": geometry, **props})

    gdf = gpd.GeoDataFrame(features, geometry="geometry", crs=WGS84)
    return gdf.to_crs(TARGET_CRS)


def load_hydrants() -> gpd.GeoDataFrame:
    where = (
        f"latitude between '{LAT_MIN}' and '{LAT_MAX}' "
        f"and longitude between '{LON_MIN}' and '{LON_MAX}'"
    )
    rows = _fetch_socrata(DATASETS["hydrants"]["url"], {"$where": where})

    features = []
    for row in rows:
        geom = row.get("the_geom")
        if geom:
            geometry = shape(geom)
        elif row.get("latitude") and row.get("longitude"):
            geometry = Point(float(row["longitude"]), float(row["latitude"]))
        else:
            continue
        props = {k: v for k, v in row.items() if k != "the_geom"}
        features.append({"geometry": geometry, **props})

    gdf = gpd.GeoDataFrame(features, geometry="geometry", crs=WGS84)
    return gdf.to_crs(TARGET_CRS)


def load_bike_lanes() -> gpd.GeoDataFrame:
    rows = _fetch_socrata(DATASETS["bike_lanes"]["url"])

    features = []
    for row in rows:
        geom = row.get("the_geom")
        if not geom:
            continue
        props = {k: v for k, v in row.items() if k != "the_geom"}
        features.append({"geometry": shape(geom), **props})

    gdf = gpd.GeoDataFrame(features, geometry="geometry", crs=WGS84)
    return filter_manhattan_bbox(gdf).to_crs(TARGET_CRS)


def load_loading_zones() -> gpd.GeoDataFrame:
    where = (
        "upper(sign_description) like '%LOADING%' "
        "OR upper(sign_description) like '%NO STANDING%'"
    )
    rows = _fetch_socrata(DATASETS["loading_zones"]["url"], {"$where": where})

    features = []
    for row in rows:
        x, y = row.get("sign_x_coord"), row.get("sign_y_coord")
        if x in (None, "") or y in (None, ""):
            continue
        props = {k: v for k, v in row.items() if k not in ("sign_x_coord", "sign_y_coord")}
        features.append(
            {
                "geometry": Point(float(x), float(y)),
                **props,
            }
        )

    gdf = gpd.GeoDataFrame(features, geometry="geometry", crs=TARGET_CRS)
    return filter_manhattan_bbox(gdf).to_crs(TARGET_CRS)


LOADERS = {
    "bus_stops": load_bus_stops,
    "hydrants": load_hydrants,
    "bike_lanes": load_bike_lanes,
    "loading_zones": load_loading_zones,
}


def download_all(raw_dir: Path | str = "data/raw") -> dict[str, gpd.GeoDataFrame]:
    raw_path = Path(raw_dir)
    raw_path.mkdir(parents=True, exist_ok=True)

    results: dict[str, gpd.GeoDataFrame] = {}
    for key, meta in DATASETS.items():
        note = meta.get("note")
        if note:
            print(f"\n[{key}] {note}")

        gdf = LOADERS[key]()
        _print_summary(key, gdf)

        out_path = raw_path / meta["filename"]
        gdf.to_file(out_path, driver="GPKG")
        print(f"Saved -> {out_path}")
        results[key] = gdf

    return results


if __name__ == "__main__":
    download_all()
