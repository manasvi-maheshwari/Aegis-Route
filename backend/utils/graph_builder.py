"""
Builds the road-network graph the whole app routes on.
"""

import hashlib
import math
import os
import shutil
import tempfile
import networkx as nx

BASE_LAT = 23.2599   # Bhopal, India
BASE_LNG = 77.4126

# A local OSM data extract, read directly from disk -- NOT a live API call.
# This is what makes routing fast and reliable: no network round-trip, no
# shared rate-limited third-party service (Overpass), just reading data we
# already have. One-time setup: download this file once (see README).
OSM_PBF_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'india-central-zone.osm.pbf'
)

# Cap on how far apart two routing points can be before we refuse to build a
# network for them -- without this, two points far enough apart would ask
# pyrosm to extract an enormous, slow-to-process bounding box.
MAX_ROUTE_SPAN_M = 50_000


def _haversine_m(lat1, lng1, lat2, lng2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


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


def _bbox_for(center, radius_m):
    """[west, south, east, north] degrees for a center point and radius in meters."""
    lat, lng = center
    lat_delta = radius_m / 111_320
    lng_delta = radius_m / (111_320 * math.cos(math.radians(lat)))
    return [lng - lng_delta, lat - lat_delta, lng + lng_delta, lat + lat_delta]


def _run_osmium_extract(bbox, output_path):
    """
    Runs `osmium extract` via os.posix_spawn rather than subprocess.run.

    WHY: subprocess.run()'s fork+exec reliably SEGFAULTs here on the 2nd+
    call within the live Flask server process (never on the 1st call, and
    never when the same code runs as a short-lived script). The process has
    by then loaded pyrosm's native deps (geopandas/shapely/pyproj, which
    pull in GEOS/PROJ/GDAL) from the 1st request's OSM(...).get_network()
    call -- those libraries can spawn their own native (non-Python) threads
    that fork() is unsafe to duplicate into a child process. posix_spawn
    doesn't fork the parent at all (it's a direct exec via the OS, not
    fork-then-exec), so it isn't exposed to that hazard.
    """
    west, south, east, north = bbox
    osmium_bin = shutil.which("osmium")
    stderr_fd, stderr_path = tempfile.mkstemp(suffix=".stderr")
    os.close(stderr_fd)
    try:
        with open(stderr_path, "wb") as stderr_file:
            pid = os.posix_spawn(
                osmium_bin,
                [osmium_bin, "extract", "--bbox", f"{west},{south},{east},{north}",
                 "-o", output_path, "--overwrite", OSM_PBF_PATH],
                os.environ,
                file_actions=[(os.POSIX_SPAWN_DUP2, stderr_file.fileno(), 2)],
            )
        _, status = os.waitpid(pid, 0)
        if os.WIFSIGNALED(status):
            raise RuntimeError(f"osmium extract crashed with signal {os.WTERMSIG(status)}")
        if os.WEXITSTATUS(status) != 0:
            with open(stderr_path) as f:
                stderr_text = f.read().strip()
            raise RuntimeError(f"osmium extract failed: {stderr_text}")
    finally:
        os.remove(stderr_path)


def build_real_road_graph(center=(BASE_LAT, BASE_LNG), radius_m=5000):
    """
    Builds a real road network around `center` from the local OSM_PBF_PATH
    file -- not a live API call. Requires that file to exist (see README's
    one-time setup step); raises a clear error naming exactly what's
    missing if it doesn't.

    Two steps, not one: `osmium extract` first clips a small bounding-box
    slice of the (few-hundred-MB) regional file down to a temporary file,
    THEN pyrosm parses that small file. Asking pyrosm to filter the big
    file directly via its own bounding_box option was measured taking
    70+ SECONDS regardless of how small the requested area was -- it
    doesn't skip irrelevant data while parsing, so cost scales with the
    whole file's size, not the query. osmium (a dedicated, highly optimized
    C++ tool) clipping first, then pyrosm parsing only the small result,
    measured taking well under 3 seconds combined for the same area.
    """
    if not os.path.exists(OSM_PBF_PATH):
        raise FileNotFoundError(
            f"Missing OSM data file at {OSM_PBF_PATH}. Download it once (see README setup "
            "instructions) -- routing reads from this local file instead of a live API, "
            "which is what makes it fast and not dependent on a shared internet service."
        )
    if shutil.which("osmium") is None:
        raise RuntimeError(
            "build_real_road_graph requires the 'osmium' command-line tool. "
            "Install it with: brew install osmium-tool (macOS) or see "
            "https://osmcode.org/osmium-tool/ for other platforms."
        )

    try:
        from pyrosm import OSM
    except ImportError as e:
        raise ImportError(
            "build_real_road_graph requires pyrosm. Run: pip install -r requirements.txt"
        ) from e

    bbox = _bbox_for(center, radius_m)
    fd, clipped_path = tempfile.mkstemp(suffix=".osm.pbf")
    os.close(fd)
    try:
        _run_osmium_extract(bbox, clipped_path)
        osm = OSM(clipped_path)
        nodes, edges = osm.get_network(network_type='driving', nodes=True)
    finally:
        os.remove(clipped_path)

    if nodes is None or edges is None or len(nodes) == 0:
        raise ValueError(f"No road data found in this area (center={center}, radius_m={radius_m}).")

    return _normalize_pyrosm_graph(nodes, edges)


def build_graph_for_route(start_lat, start_lng, end_lat, end_lng, padding_m=1500):
    """
    Builds a real road network sized and centered to cover two arbitrary
    points, with padding so routing isn't forced through a razor-thin
    corridor and hazards near the endpoints still have surrounding roads to
    reroute through. Raises ValueError if the two points are implausibly
    far apart (see MAX_ROUTE_SPAN_M).
    """
    span_m = _haversine_m(start_lat, start_lng, end_lat, end_lng)
    if span_m > MAX_ROUTE_SPAN_M:
        raise ValueError(
            f"Rescue base and disaster site are {span_m / 1000:.0f}km apart -- "
            f"max supported distance is {MAX_ROUTE_SPAN_M / 1000:.0f}km."
        )

    center = ((start_lat + end_lat) / 2, (start_lng + end_lng) / 2)
    radius_m = span_m / 2 + padding_m
    return build_real_road_graph(center=center, radius_m=radius_m)


def _normalize_pyrosm_graph(nodes, edges):
    """
    Converts pyrosm's (nodes, edges) GeoDataFrame pair into the same plain
    undirected nx.Graph shape build_city_graph produces. pyrosm's driving
    network is already effectively undirected for our purposes (it doesn't
    split two-way streets into separate directed edges the way raw OSM
    data/osmnx do), so there's no parallel-edge collapsing needed here --
    just a straight attribute copy, keeping the shorter of any duplicate
    u/v pair as a simple safeguard.

    Clipping a bounding box out of a larger region can slice through roads
    right at the edge, leaving small disconnected fragments attached to
    nothing else inside the box. Keeping only the largest connected
    component discards those -- they're unusable for routing anyway, and
    an isolated fragment landing under a hazard or an endpoint pick would
    otherwise surface as a confusing "no path" error.
    """
    G = nx.Graph()
    for row in nodes.itertuples():
        G.add_node(int(row.id), lat=float(row.lat), lng=float(row.lon), risk_score=0.0)

    for row in edges.itertuples():
        u, v = int(row.u), int(row.v)
        if u == v or u not in G or v not in G:
            continue
        length = float(row.length)
        if length != length:  # NaN guard
            continue
        length = round(length, 1)
        if G.has_edge(u, v) and length >= G[u][v]['distance']:
            continue
        G.add_edge(u, v, distance=length, risk=0.0, blocked=False)

    if G.number_of_nodes() > 0 and not nx.is_connected(G):
        largest = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest).copy()

    return G
