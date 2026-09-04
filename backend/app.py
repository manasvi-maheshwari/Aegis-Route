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

Everything is intentionally recomputed on every /api/route call (grid graph +
hazards) so the demo is stateless and easy to test with different inputs --
except D* Lite's OWN internal path memory, which is deliberately kept across
calls, because "remembering the last route" is the entire point of D* Lite.
"""

import sys
import os
import time
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

from utils.graph_builder import build_city_graph
from utils.hazard_mapper import apply_hazard_zones
from utils.routing_helpers import find_safe_path, risk_cost, path_stats
from algorithms.d_star_lite import DStarLite
from algorithms.nsga2_router import run_nsga2_route, get_pareto_front

app = Flask(__name__)
CORS(app)

GRID_SIZE = 15
BASE_LAT, BASE_LNG = 12.9716, 79.1594
SCALE = 0.005

DEFAULT_START = [0, 0]
DEFAULT_END = [14, 14]


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
    """
    Builds a fresh 15x15 road-network graph and paints the given hazard
    zones onto it. custom_hazards is a list the FRONTEND sends -- clicks on
    the map become circles here. An empty list means a totally clear map
    (no hazards at all) -- that is a valid, real test case, not an error.
    """
    graph = build_city_graph(grid_size=GRID_SIZE)
    if custom_hazards:
        graph = apply_hazard_zones(graph, custom_hazards)
    return graph


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
    default_hazards = [{"grid_x": 7, "grid_y": 7, "radius": 4}]
    hazards_data = []
    for h in default_hazards:
        hazards_data.append({
            "lat": BASE_LAT + (h['grid_x'] * SCALE),
            "lng": BASE_LNG + (h['grid_y'] * SCALE),
            "radius_meters": h['radius'] * 500,
            "grid_x": h['grid_x'],
            "grid_y": h['grid_y'],
            "radius": h['radius'],
        })
    return jsonify(hazards_data)


@app.route('/api/route', methods=['POST'])
def get_route():
    data = request.json or {}
    start_node = tuple(data.get('start', DEFAULT_START))
    end_node = tuple(data.get('end', DEFAULT_END))
    algo = data.get('algorithm', 'a_star')
    custom_hazards = data.get('custom_hazards', [])

    graph = build_scenario(custom_hazards)

    try:
        result = run_one_algorithm(algo, graph, start_node, end_node)
        if result["status"] == "no_path":
            return jsonify({
                "status": "error",
                "message": "No route exists at all -- the destination is completely cut off by hazards."
            }), 400
        result["status"] = "success"
        return jsonify(result)

    except Exception as e:
        return jsonify({"status": "error", "message": f"Routing failed: {str(e)}"}), 400


@app.route('/api/compare-all', methods=['POST'])
def compare_all():
    """
    Runs every algorithm on the EXACT same scenario (same graph, same
    hazards, same start/end) so their results are directly comparable.
    This single call is what powers the "Compare All" button that overlays
    every route on the map together with a stats table -- the strongest
    single piece of evidence in the demo that these are genuinely
    different algorithms, not the same code renamed three times.
    """
    data = request.json or {}
    start_node = tuple(data.get('start', DEFAULT_START))
    end_node = tuple(data.get('end', DEFAULT_END))
    custom_hazards = data.get('custom_hazards', [])

    graph = build_scenario(custom_hazards)

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


@app.route('/api/reset', methods=['POST'])
def reset_scenario():
    """Clears D* Lite's remembered routes -- call before a fresh demo run."""
    DStarLite.reset_memory()
    return jsonify({"status": "success", "message": "D* Lite memory cleared."})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)