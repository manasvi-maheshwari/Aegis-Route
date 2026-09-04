"""
Builds the road-network graph the whole app routes on.
"""

import hashlib
import networkx as nx


def _seeded_length(u, v, low=350.0, high=650.0):
    """
    Deterministic 'random' road length for the edge (u, v).

    WHY THIS EXISTS: in the very first version every road segment was
    exactly 500m. That made every zig-zag route between two points come
    out to EXACTLY the same total distance (a property of grid graphs --
    any monotonic staircase path has the same length). The side effect
    was that "shortest" and "safest" routes were always tied on distance,
    which made the multi-objective algorithm (NSGA-II) look pointless --
    there was nothing to trade off.

    Real streets are not all identical lengths. So each edge gets a
    realistic length in the 350m-650m range. It's seeded off the edge's
    own coordinates (not Python's random module), so the SAME graph is
    produced every time the app restarts -- results stay reproducible
    for the demo and the benchmark script.
    """
    key = f"{u}-{v}".encode()
    h = int(hashlib.md5(key).hexdigest(), 16)
    span = high - low
    return low + (h % 1000) / 1000.0 * span


def build_city_graph(grid_size=15):
    """
    Builds a grid network representing city streets and intersections, and
    maps every intersection to a real-looking latitude/longitude so it can
    be drawn straight onto a Leaflet map.
    """
    G = nx.grid_2d_graph(grid_size, grid_size)

    base_lat, base_lng = 12.9716, 79.1594
    scale = 0.005  # spacing between adjacent intersections, in degrees

    for node in G.nodes():
        x, y = node
        G.nodes[node]['lat'] = base_lat + (x * scale)
        G.nodes[node]['lng'] = base_lng + (y * scale)
        G.nodes[node]['risk_score'] = 0.0

    for u, v in G.edges():
        a, b = sorted([u, v])  # sort so (u,v) and (v,u) get the same length
        G[u][v]['distance'] = round(_seeded_length(a, b), 1)
        G[u][v]['risk'] = 0.0
        G[u][v]['blocked'] = False

    return G
