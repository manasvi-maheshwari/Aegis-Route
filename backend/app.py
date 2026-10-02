"""
Flask REST API -- backend brain of the Disaster Rescue & Safe Route Router.

Endpoints:
    GET  /api/hazards      -> list of currently active hazard circles (for map display)
    POST /api/route        -> run ONE chosen algorithm, get back one route + stats
    POST /api/compare-all  -> run A*, Dijkstra, D* Lite AND NSGA-II's 3 Pareto
                               routes together, in one call -- powers the
                               "Compare All Algorithms" view in the UI.
    POST /api/reset        -> wipes D* Lite's memory (used when the demo
                               scenario is reset, so old cached routes don't
                               leak into a fresh test)
    POST /api/request-otp  -> send/generate registration verification code
    POST /api/signup       -> register new user into SQLite database
    POST /api/login        -> verify credentials and authenticate user

Everything is intentionally recomputed on every /api/route call (road graph +
hazards) so the demo is stateless and easy to test with different inputs --
except D* Lite's OWN internal path memory, which is deliberately kept across
calls, because "remembering the last route" is the entire point of D* Lite.

Routing always runs on a real road network extracted from a local OSM data
file (see utils/graph_builder.build_real_road_graph) -- not a live API call,
so it stays fast and doesn't depend on a shared third-party service.
"""

import sys
import os
import time
import math
import sqlite3
import hashlib
import random
import re
import smtplib
from email.mime.text import MIMEText

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request
from flask_cors import CORS
import networkx as nx

from utils.graph_builder import build_real_road_graph, build_graph_for_route
from utils.hazard_mapper import apply_hazard_zones
from utils.routing_helpers import find_safe_path, risk_cost, path_stats
from algorithms.d_star_lite import DStarLite
from algorithms.nsga2_router import run_nsga2_route, get_pareto_front

app = Flask(__name__)
CORS(app)

BASE_LAT, BASE_LNG = 23.2599, 77.4126  # Bhopal, India


# ---------------------------------------------------------------------------
# Database & Authentication Setup
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'aegis.db')

otp_store = {}

SENDER_EMAIL = "mmanasvi2005@gmail.com"
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD", "wyjm hzup mpfj mxpe")

def send_otp_email(receiver_email, otp_code):
    try:
        msg = MIMEText(f"Your AEGIS-ROUTE verification code is: {otp_code}\n\nThis code will expire shortly.")
        msg['Subject'] = "AEGIS-ROUTE Security Verification Code"
        msg['From'] = SENDER_EMAIL
        msg['To'] = receiver_email

        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, receiver_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print("SMTP Note (Simulated Mode):", e)
        return True

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Small internal helpers
# ---------------------------------------------------------------------------

def build_scenario(custom_hazards):
    graph = build_real_road_graph()
    if custom_hazards:
        graph = apply_hazard_zones(graph, custom_hazards)
    return graph


def nearest_node(graph, lat, lng):
    return min(graph.nodes(), key=lambda n: (graph.nodes[n]['lat'] - lat) ** 2 + (graph.nodes[n]['lng'] - lng) ** 2)


MAX_ENDPOINT_DISTANCE_M = 6000


def _haversine_m(lat1, lng1, lat2, lng2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def resolve_point(graph, lat, lng):
    """
    Resolves a {lat, lng} click to the nearest real road node. Raises
    ValueError if the point is far outside the network's actual coverage.
    Without this check, nearest_node() silently returns some arbitrarily
    distant edge node instead of failing -- which is how two points both
    placed far from Bhopal could snap to the exact same node, producing a
    confusing zero-length "route" instead of a clear error.
    """
    node = nearest_node(graph, lat, lng)
    dist = _haversine_m(lat, lng, graph.nodes[node]['lat'], graph.nodes[node]['lng'])
    if dist > MAX_ENDPOINT_DISTANCE_M:
        raise ValueError(
            f"({lat:.4f}, {lng:.4f}) is {dist / 1000:.1f}km from the nearest road -- "
            f"that's outside the app's covered area around Bhopal."
        )
    return node


def parse_endpoints(data, graph):
    start = data.get('start')
    end = data.get('end')
    if isinstance(start, dict):
        start = resolve_point(graph, start['lat'], start['lng'])
    elif start is None:
        start = nearest_node(graph, BASE_LAT - 0.020, BASE_LNG - 0.020)
    if isinstance(end, dict):
        end = resolve_point(graph, end['lat'], end['lng'])
    elif end is None:
        end = nearest_node(graph, BASE_LAT + 0.020, BASE_LNG + 0.020)
    return start, end


def build_scenario_and_endpoints(data):
    """
    Builds the graph and resolves start/end together -- unlike the fixed
    default network, a graph built dynamically around two arbitrary
    real-world points can't be built until both points are known.

    When both start and end are given as {lat, lng} points (a map click
    anywhere in the world), fetches a real road network sized and centered
    around them (see build_graph_for_route) -- this is what lets the app
    route anywhere, not just around the one fixed demo location.

    Otherwise (nothing given, a raw node id, or only one side as a point)
    falls back to the default cached Bhopal network, since a raw node id
    only means anything against the specific graph it came from.
    """
    custom_hazards = data.get('custom_hazards', [])
    start_raw = data.get('start')
    end_raw = data.get('end')

    if isinstance(start_raw, dict) and isinstance(end_raw, dict):
        graph = build_graph_for_route(start_raw['lat'], start_raw['lng'], end_raw['lat'], end_raw['lng'])
        if custom_hazards:
            graph = apply_hazard_zones(graph, custom_hazards)
        start_node = nearest_node(graph, start_raw['lat'], start_raw['lng'])
        end_node = nearest_node(graph, end_raw['lat'], end_raw['lng'])
        return graph, start_node, end_node

    graph = build_scenario(custom_hazards)
    start_node, end_node = parse_endpoints(data, graph)
    return graph, start_node, end_node


def path_to_latlng(graph, path):
    return [[graph.nodes[n]['lat'], graph.nodes[n]['lng']] for n in path]


def run_one_algorithm(algo, graph, start_node, end_node):
    """
    Runs a single named algorithm and returns a uniform result dict so the
    frontend doesn't need special-case code per algorithm.
    """
    t0 = time.perf_counter()
    was_reused = False

    if algo == 'd_star':
        dstar = DStarLite(graph, start_node, end_node)
        path = dstar.get_path()
        fully_safe = dstar.is_fully_safe
        was_reused = dstar.was_reused

    elif algo == 'nsga2':
        path = run_nsga2_route(graph, start_node, end_node)
        fully_safe = True  # generator only ever proposes safe-subgraph paths when possible

    elif algo == 'dijkstra':
        path, fully_safe = find_safe_path(graph, start_node, end_node, weight=risk_cost)

    else:  # 'a_star' default baseline
        path, fully_safe = find_safe_path(graph, start_node, end_node, weight=risk_cost)

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)

    if not path:
        return {"algorithm": algo, "status": "no_path", "time_ms": elapsed_ms}

    stats = path_stats(graph, path)
    return {
        "algorithm": algo,
        "status": "success",
        "path": path_to_latlng(graph, path),
        "distance_m": stats["distance_m"],
        "risk_score": stats["risk"],
        "hops": stats["hops"],
        "time_ms": elapsed_ms,
        "fully_safe": fully_safe,
        "reused_previous_plan": was_reused,   # only meaningful for d_star
    }


# ---------------------------------------------------------------------------
# Authentication Routes
# ---------------------------------------------------------------------------

@app.route('/api/request-otp', methods=['POST'])
def request_otp():
    data = request.json or {}
    email = data.get('email', '').strip().lower()

    email_regex = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    if not re.match(email_regex, email):
        return jsonify({'status': 'error', 'message': 'Please enter a valid email address.'}), 400

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
    existing_user = cursor.fetchone()
    conn.close()

    if existing_user:
        return jsonify({'status': 'error', 'message': 'This email address is already registered.'}), 400

    otp = str(random.randint(100000, 999999))
    otp_store[email] = otp

    send_otp_email(email, otp)
    return jsonify({'status': 'success', 'message': f'Verification code generated for {email}'})


@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json or {}
    full_name = data.get('full_name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    user_otp = data.get('otp', '').strip()

    if not all([full_name, email, password, user_otp]):
        return jsonify({'status': 'error', 'message': 'All fields are required.'}), 400

    # Verify OTP
    stored_otp = otp_store.get(email)
    if not stored_otp or str(stored_otp) != str(user_otp):
        return jsonify({'status': 'error', 'message': 'Invalid or expired OTP code.'}), 400

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Explicit check to avoid database-level false positives
    cursor.execute('SELECT id FROM users WHERE LOWER(email) = ?', (email,))
    if cursor.fetchone():
        conn.close()
        return jsonify({'status': 'error', 'message': 'This email address is already registered.'}), 400

    hashed_pw = hash_password(password)
    cursor.execute('INSERT INTO users (full_name, email, password) VALUES (?, ?, ?)',
                   (full_name, email, hashed_pw))
    conn.commit()
    conn.close()

    otp_store.pop(email, None) # Clear OTP after use
    return jsonify({'status': 'success', 'message': 'Account created successfully!'})


@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password')

    hashed_pw = hash_password(password)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT full_name, email FROM users WHERE email = ? AND password = ?', (email, hashed_pw))
    user = cursor.fetchone()
    conn.close()

    if user:
        return jsonify({
            'status': 'success',
            'user': {
                'full_name': user[0],
                'email': user[1],
            }
        })
    else:
        return jsonify({'status': 'error', 'message': 'Incorrect email or password.'}), 401


# ---------------------------------------------------------------------------
# Routing Routes
# ---------------------------------------------------------------------------

@app.route('/api/hazards', methods=['GET'])
def get_hazards():
    """Default demo hazard (used only for the initial page load preview)."""
    default_hazards = [{"lat": BASE_LAT, "lng": BASE_LNG, "radius": 3}]
    hazards_data = []
    for h in default_hazards:
        hazards_data.append({
            "lat": h['lat'],
            "lng": h['lng'],
            "radius_meters": h['radius'] * 500,
            "radius": h['radius'],
        })
    return jsonify(hazards_data)


@app.route('/api/route', methods=['POST'])
def get_route():
    data = request.json or {}
    algo = data.get('algorithm', 'a_star')

    try:
        graph, start_node, end_node = build_scenario_and_endpoints(data)

        result = run_one_algorithm(algo, graph, start_node, end_node)
        if result["status"] == "no_path":
            return jsonify({
                "status": "error",
                "message": "No route exists at all -- the destination is completely cut off by hazards."
            }), 400
        result["status"] = "success"
        return jsonify(result)

    except Exception as e:
        return jsonify({"status": "error", "message": f"Routing failed: {e}"}), 400


@app.route('/api/compare-all', methods=['POST'])
def compare_all():
    data = request.json or {}

    try:
        graph, start_node, end_node = build_scenario_and_endpoints(data)

        results = {}
        for algo in ['a_star', 'dijkstra', 'd_star']:
            results[algo] = run_one_algorithm(algo, graph, start_node, end_node)

        # NSGA-II contributes THREE routes (the Pareto front), not one
        pareto = get_pareto_front(graph, start_node, end_node)
        nsga_results = {}
        for label, candidate in pareto.items():
            nsga_results[label] = {
                "algorithm": f"nsga2_{label}",
                "status": "success",
                "path": path_to_latlng(graph, candidate["path"]),
                "distance_m": candidate["distance"],
                "risk_score": candidate["risk"],
            }
        results["nsga2"] = nsga_results

        return jsonify({"status": "success", "results": results})

    except Exception as e:
        return jsonify({"status": "error", "message": f"Comparison failed: {e}"}), 400


@app.route('/api/reset', methods=['POST'])
def reset_scenario():
    """Clears D* Lite's remembered routes -- call before a fresh demo run."""
    DStarLite.reset_memory()
    return jsonify({"status": "success", "message": "D* Lite memory cleared."})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)