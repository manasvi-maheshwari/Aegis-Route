import os
import sys
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.graph_builder import build_city_graph
from utils.hazard_mapper import apply_hazard_zones, CORE_RISK, DANGER_RISK, DANGER_BUFFER_MULT

BASE_LAT, BASE_LNG, SCALE = 12.9716, 79.1594, 0.005

failures = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        failures.append(label)


# 1. Graph structure
G = build_city_graph(grid_size=15)
check("grid has 225 nodes", G.number_of_nodes() == 225)
check("grid has 2*15*14=420 edges", G.number_of_edges() == 420)
check("node (0,0) maps to base lat/lng", G.nodes[(0, 0)]['lat'] == BASE_LAT and G.nodes[(0, 0)]['lng'] == BASE_LNG)
check("node (1,0) shifts lat by scale", math.isclose(G.nodes[(1, 0)]['lat'], BASE_LAT + SCALE))
check("node (0,1) shifts lng by scale", math.isclose(G.nodes[(0, 1)]['lng'], BASE_LNG + SCALE))

lengths = [d['distance'] for _, _, d in G.edges(data=True)]
check("all edge lengths in [350, 650]m", all(350.0 <= L <= 650.0 for L in lengths))
check("edge lengths are NOT all identical (real trade-off exists)", len(set(lengths)) > 50)

a, b = (3, 3), (3, 4)
d1 = build_city_graph(15)[a][b]['distance']
d2 = build_city_graph(15)[a][b]['distance']
check("edge length is deterministic across rebuilds (seeded, not random)", d1 == d2)

check("no risk/blocked state before hazards applied",
      all(d['risk'] == 0.0 and d['blocked'] is False for _, _, d in G.edges(data=True)))

# 2. Hazard core ring -> impassable
G2 = build_city_graph(15)
hazard = {"grid_x": 7, "grid_y": 7, "radius": 2}
G2 = apply_hazard_zones(G2, [hazard])

center = (7, 7)
check(f"core node {center} risk_score == CORE_RISK",
      G2.nodes[center]['risk_score'] == CORE_RISK)
core_edges = list(G2.edges(center, data=True))
check("all edges touching core node are blocked with CORE_RISK",
      all(d['blocked'] is True and d['risk'] == CORE_RISK for _, _, d in core_edges))

# 3. Danger buffer ring -> risky but passable
core_radius_deg = hazard['radius'] * SCALE
danger_radius_deg = core_radius_deg * DANGER_BUFFER_MULT

buffer_node = None
for node in G2.nodes():
    n_lat, n_lng = G2.nodes[node]['lat'], G2.nodes[node]['lng']
    h_lat = BASE_LAT + hazard['grid_x'] * SCALE
    h_lng = BASE_LNG + hazard['grid_y'] * SCALE
    dist = math.sqrt((n_lat - h_lat) ** 2 + (n_lng - h_lng) ** 2)
    if core_radius_deg < dist <= danger_radius_deg:
        buffer_node = node
        break

check("found a node strictly inside the danger buffer ring", buffer_node is not None)
if buffer_node:
    check(f"buffer node {buffer_node} risk_score == DANGER_RISK",
          G2.nodes[buffer_node]['risk_score'] == DANGER_RISK)
    buffer_edges = [d for _, _, d in G2.edges(buffer_node, data=True)]
    check("buffer-ring edges are NOT blocked",
          all(d['blocked'] is False for d in buffer_edges))
    check("buffer-ring edges get DANGER_RISK cost (or more, from overlap)",
          all(d['risk'] >= DANGER_RISK for d in buffer_edges))

# 4. Overlap handling: a second, weaker hazard must not downgrade a core node
G3 = build_city_graph(15)
G3 = apply_hazard_zones(G3, [
    {"grid_x": 7, "grid_y": 7, "radius": 2},   # strong hazard -> core at (7,7)
    {"grid_x": 8, "grid_y": 7, "radius": 1},   # overlapping weaker hazard nearby
])
check("node (7,7) stays at CORE_RISK after an overlapping weaker hazard",
      G3.nodes[(7, 7)]['risk_score'] == CORE_RISK)

# 5. get_safe_subgraph actually removes blocked edges (not just penalizes)
from utils.routing_helpers import get_safe_subgraph, risk_cost, find_safe_path, path_stats

safe = get_safe_subgraph(G2)
check("safe subgraph has fewer edges than full graph (blocked edges removed)",
      safe.number_of_edges() < G2.number_of_edges())
check("safe subgraph contains zero blocked edges",
      all(not d.get('blocked', False) for _, _, d in safe.edges(data=True)))

path, is_safe = find_safe_path(G2, (0, 0), (14, 14))
stats = path_stats(G2, path)
check("a safe path around the hazard is found and reported as fully safe",
      path is not None and is_safe is True)
print(f"    -> path stats: {stats}")

print()
if failures:
    print(f"{len(failures)} CHECK(S) FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All checks passed.")
