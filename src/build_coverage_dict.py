"""Rebuild data/processed/coverage_dict.pkl from the pandana network.

Replicates the exact logic from notebook 04 Steps 2-3 so that notebook 05
can load the coverage dict without re-running the full optimization notebook.
"""
import pickle
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pandana
from scipy.spatial import cKDTree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_CRS = "EPSG:32618"
OUT_PATH = PROJECT_ROOT / "data" / "processed" / "coverage_dict.pkl"

print("Loading candidates, nodes, edges...")
candidates = gpd.read_file(PROJECT_ROOT / "data/processed/candidate_sites_filtered.gpkg").to_crs(TARGET_CRS)
nodes = gpd.read_file(PROJECT_ROOT / "data/raw/manhattan_nodes.gpkg").to_crs(TARGET_CRS)
edges = gpd.read_file(PROJECT_ROOT / "data/raw/manhattan_roads.gpkg").to_crs(TARGET_CRS)
print(f"  Candidates: {len(candidates):,}  Nodes: {len(nodes):,}  Edges: {len(edges):,}")

# Build pandana network (same as notebook 04)
nodes["node_id"] = np.arange(len(nodes), dtype=np.int32)
osmid_to_nodeid = dict(zip(nodes["osmid"], nodes["node_id"]))
nodes = nodes.set_index("node_id")
nodes["x"] = nodes.geometry.x
nodes["y"] = nodes.geometry.y

edges["length_m"] = edges.geometry.length
edges["from_id"] = edges["u"].map(osmid_to_nodeid)
edges["to_id"] = edges["v"].map(osmid_to_nodeid)
edges = edges.dropna(subset=["from_id", "to_id"])
edges["from_id"] = edges["from_id"].astype(np.int32)
edges["to_id"] = edges["to_id"].astype(np.int32)

network = pandana.Network(
    node_x=nodes["x"],
    node_y=nodes["y"],
    edge_from=edges["from_id"],
    edge_to=edges["to_id"],
    edge_weights=edges[["length_m"]],
)
print(f"  Network: {len(nodes):,} nodes, {len(edges):,} edges")

# Coverage dict (identical to notebook 04 Steps 2-3)
t0 = time.time()
N_POIS = 200

x_s = pd.Series(candidates.geometry.x.values)
y_s = pd.Series(candidates.geometry.y.values)
network.set_pois("cand", maxdist=700, maxitems=N_POIS, x_col=x_s, y_col=y_s)

combined = network.nearest_pois(500, "cand", num_pois=N_POIS, include_poi_ids=True)

dist_cols = list(range(1, N_POIS + 1))
id_cols = [f"poi{k}" for k in range(1, N_POIS + 1)]

raw_nodes = network.get_node_ids(candidates.geometry.x, candidates.geometry.y)
node_arr = raw_nodes.reindex(candidates.index, fill_value=-1).astype(int).values

coverage = {}
for i in range(len(candidates)):
    nd = node_arr[i]
    if nd < 0 or nd not in combined.index:
        coverage[i] = [i]
        continue
    row = combined.loc[nd]
    dists = row[dist_cols]
    ids = row[id_cols]
    valid = dists.notna() & (dists <= 500)
    js = ids[valid.values].dropna().astype(int).tolist()
    coverage[i] = js if js else [i]

elapsed = time.time() - t0
sizes = [len(v) for v in coverage.values()]
print(f"Coverage dict: {len(coverage):,} demand points  (built in {elapsed:.1f}s)")
print(f"  Mean covering sites per point: {np.mean(sizes):.1f}  max={max(sizes)}  min={min(sizes)}")

with open(OUT_PATH, "wb") as f:
    pickle.dump(coverage, f)
print(f"Saved -> {OUT_PATH}")
