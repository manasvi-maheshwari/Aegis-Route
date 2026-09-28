import os
import sys
import networkx as nx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.graph_builder import build_real_road_graph, build_city_graph, REAL_GRAPH_CACHE_PATH
from utils.routing_helpers import find_safe_path, path_stats

failures = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        failures.append(label)


print("Fetching/loading real road network (uses cache if present)...")
G = build_real_road_graph()

check("graph has a reasonable number of nodes", 50 <= G.number_of_nodes() <= 5000)
check("graph has at least as many edges as nodes (not a bunch of isolated points)",
      G.number_of_edges() >= G.number_of_nodes())
check("graph is a plain undirected nx.Graph (not Multi/Directed)", type(G) is nx.Graph)
check("graph is connected (no isolated islands to strand a route)", nx.is_connected(G))

sample_node, sample_node_data = next(iter(G.nodes(data=True)))
check("nodes carry lat/lng/risk_score", {'lat', 'lng', 'risk_score'} <= set(sample_node_data.keys()))
check("node lat looks like a real latitude near the app's base coords",
      abs(sample_node_data['lat'] - 12.9716) < 0.1)
check("risk_score starts at 0.0 (no hazards applied yet)", sample_node_data['risk_score'] == 0.0)

sample_u, sample_v, sample_edge_data = next(iter(G.edges(data=True)))
check("edges carry distance/risk/blocked", {'distance', 'risk', 'blocked'} <= set(sample_edge_data.keys()))
check("edge distance is a real, positive, non-uniform street length",
      sample_edge_data['distance'] > 0)
distances = [d['distance'] for _, _, d in G.edges(data=True)]
check("edge distances are NOT all identical (real street data, not synthetic)", len(set(distances)) > 10)
check("no blocked/risk state before any hazard is applied",
      all(d['risk'] == 0.0 and d['blocked'] is False for _, _, d in G.edges(data=True)))

check("attribute contract matches build_city_graph exactly (drop-in compatible)",
      set(sample_node_data.keys()) == set(next(iter(build_city_graph().nodes(data=True)))[1].keys())
      and {'distance', 'risk', 'blocked'} == set(sample_edge_data.keys()))

check("cache file was written to disk", os.path.exists(REAL_GRAPH_CACHE_PATH))

# A second call must hit the cache (fast), not re-fetch from the network every time
import time
t0 = time.time()
G2 = build_real_road_graph()
cached_call_ms = (time.time() - t0) * 1000
check(f"second call reuses the cache (took {cached_call_ms:.1f}ms, expected < 500ms)",
      cached_call_ms < 500)
check("cached reload produces the same node/edge counts",
      G2.number_of_nodes() == G.number_of_nodes() and G2.number_of_edges() == G.number_of_edges())

# Sanity: routing_helpers (used by every algorithm) works unmodified on this graph
nodes = list(G.nodes())
start, end = nodes[0], nodes[-1]
path, is_safe = find_safe_path(G, start, end)
stats = path_stats(G, path)
check("routing_helpers.find_safe_path works on the real graph's node IDs",
      path is not None)
print(f"    -> sample path stats: {stats}")

print()
if failures:
    print(f"{len(failures)} CHECK(S) FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All checks passed.")
