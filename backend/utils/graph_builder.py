"""
Builds the road-network graph the whole app routes on.
"""

import hashlib
import os
import networkx as nx

BASE_LAT = 12.9716
BASE_LNG = 79.1594

REAL_GRAPH_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'road_network.graphml'
)


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
    Builds a synthetic grid network representing city streets and
    intersections, and maps every intersection to a real-looking
    latitude/longitude so it can be drawn straight onto a Leaflet map.
    """
    G = nx.grid_2d_graph(grid_size, grid_size)

    scale = 0.005  # spacing between adjacent intersections, in degrees

    for node in G.nodes():
        x, y = node
        G.nodes[node]['lat'] = BASE_LAT + (x * scale)
        G.nodes[node]['lng'] = BASE_LNG + (y * scale)
        G.nodes[node]['risk_score'] = 0.0

    for u, v in G.edges():
        a, b = sorted([u, v])  # sort so (u,v) and (v,u) get the same length
        G[u][v]['distance'] = round(_seeded_length(a, b), 1)
        G[u][v]['risk'] = 0.0
        G[u][v]['blocked'] = False

    return G


def build_real_road_graph(center=(BASE_LAT, BASE_LNG), radius_m=5000, cache_path=REAL_GRAPH_CACHE_PATH):
    try:
        import osmnx as ox
    except ImportError as e:
        raise ImportError(
            "build_real_road_graph requires osmnx. Run: pip install -r requirements.txt"
        ) from e

    if os.path.exists(cache_path):
        raw = ox.load_graphml(cache_path)
    else:
        raw = ox.graph_from_point(center, dist=radius_m, network_type='drive', simplify=True)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        ox.save_graphml(raw, cache_path)

    return _normalize_osm_graph(raw)


def _normalize_osm_graph(raw):
    G = nx.Graph()
    for node, data in raw.nodes(data=True):
        G.add_node(node, lat=float(data['y']), lng=float(data['x']), risk_score=0.0)

    for u, v, data in raw.edges(data=True):
        if u == v:
            continue
        length = round(float(data.get('length', 0.0)), 1)
        if G.has_edge(u, v) and length >= G[u][v]['distance']:
            continue
        G.add_edge(u, v, distance=length, risk=0.0, blocked=False)

    return G
