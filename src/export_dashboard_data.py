"""Export MCLP optimization outputs as GeoJSON for the web dashboard.

Reads .gpkg files from data/processed/ (projected CRS), reprojects to
EPSG:4326, strips all columns except geometry and nkde_score, and writes
GeoJSON to docs/data/. Also writes docs/data/stats.json.
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import shapely

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "processed"
OUT_DIR = PROJECT_ROOT / "docs" / "data"
WGS84 = "EPSG:4326"

MANHATTAN_P = [50, 75, 100, 125, 150]
PORTO_P = [20, 40, 55, 70, 85, 100]

LAYERS: list[tuple[Path, Path]] = (
    [(DATA_DIR / f"mclp_selected_p{p}.gpkg", OUT_DIR / f"manhattan_base_p{p}.geojson")
     for p in MANHATTAN_P]
    + [(DATA_DIR / f"mclp_equity_p{p}.gpkg", OUT_DIR / f"manhattan_equity_p{p}.geojson")
       for p in MANHATTAN_P]
    + [(DATA_DIR / f"porto_mclp_p{p}.gpkg", OUT_DIR / f"porto_base_p{p}.geojson")
       for p in PORTO_P]
)

NETWORK_SRC = DATA_DIR / "edges_with_nkde.gpkg"
NETWORK_DST = OUT_DIR / "manhattan_network.geojson"
SIMPLIFY_TOLERANCE_M = 5.0
COORD_DECIMALS = 6

_SHAPELY2 = int(shapely.__version__.split(".")[0]) >= 2


def _round_coords(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Round geometry coordinates to COORD_DECIMALS decimal places."""
    grid = 10 ** (-COORD_DECIMALS)
    gdf = gdf.copy()
    if _SHAPELY2:
        from shapely import set_precision
        gdf["geometry"] = [set_precision(g, grid_size=grid) for g in gdf.geometry]
    else:
        from shapely.wkt import dumps, loads
        gdf["geometry"] = [
            loads(dumps(g, rounding_precision=COORD_DECIMALS)) for g in gdf.geometry
        ]
    return gdf


def _keep_cols(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Retain only geometry and nkde_score (if present)."""
    cols = [c for c in ["nkde_score"] if c in gdf.columns]
    return gdf[cols + ["geometry"]]


def export_layer(src: Path, dst: Path) -> int:
    gdf = gpd.read_file(src)
    gdf = _keep_cols(gdf).to_crs(WGS84)
    gdf = _round_coords(gdf)
    gdf.to_file(dst, driver="GeoJSON")
    n = len(gdf)
    size_kb = dst.stat().st_size / 1024
    print(f"  {dst.name}: {n:,} sites  ({size_kb:.1f} KB)")
    return n


def export_network(src: Path, dst: Path) -> int:
    gdf = gpd.read_file(src)
    gdf = _keep_cols(gdf)
    # Simplify in projected CRS before reprojecting so tolerance is in metres.
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
    gdf = gdf.to_crs(WGS84)
    gdf = _round_coords(gdf)
    gdf.to_file(dst, driver="GeoJSON")
    n = len(gdf)
    size_mb = dst.stat().st_size / (1024 * 1024)
    print(f"  {dst.name}: {n:,} edges  ({size_mb:.2f} MB)")
    return n


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    stats: dict[str, int] = {}
    written: list[Path] = []

    print("Exporting point layers...")
    for src, dst in LAYERS:
        if not src.exists():
            print(f"  SKIP (not found): {src.name}")
            continue
        n = export_layer(src, dst)
        stats[dst.stem] = n
        written.append(dst)

    if NETWORK_SRC.exists():
        print("\nExporting network glow layer...")
        n = export_network(NETWORK_SRC, NETWORK_DST)
        stats[NETWORK_DST.stem] = n
        written.append(NETWORK_DST)
    else:
        print(f"\nSKIP network layer ({NETWORK_SRC.name} not found)")

    stats_path = OUT_DIR / "stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)
    written.append(stats_path)
    print(f"\nWrote stats.json  ({len(stats)} entries)")

    print("\n--- Files written ---")
    total_bytes = 0
    for path in written:
        size = path.stat().st_size
        total_bytes += size
        rel = path.relative_to(PROJECT_ROOT)
        if size >= 1_048_576:
            label = f"{size / 1_048_576:.2f} MB"
        else:
            label = f"{size / 1024:.1f} KB"
        print(f"  {rel}  ({label})")
    print(f"\n  Total: {total_bytes / 1_048_576:.2f} MB across {len(written)} files")


if __name__ == "__main__":
    main()
