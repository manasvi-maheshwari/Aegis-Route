# Aegis-Route: Autonomous AI Disaster Rescue & Safe Route Router

A full-stack, real-time routing engine designed for disaster rescue operations. Aegis-Route evaluates road network safety under dynamic conditions, using multi-objective optimization and incremental replanning to help emergency responders navigate around hazard zones safely.

---

## 1. Project Structure

```text
Aegis-Route/
├── backend/
│   ├── app.py                     # Flask API server
│   ├── requirements.txt           # Python dependencies
│   ├── algorithms/
│   │   ├── d_star_lite.py         # Dynamic replanning algorithm
│   │   └── nsga2_router.py        # Multi-objective (distance vs. risk) solver
│   ├── utils/
│   │   ├── graph_builder.py       # Builds the real OpenStreetMap road network
│   │   ├── hazard_mapper.py       # Computes hazard zones & cost multipliers
│   │   └── routing_helpers.py     # Shared pathfinding & safety logic
│   └── benchmarks/
│       └── runner.py              # Generates benchmarking CSVs and performance charts
├── frontend/
│   ├── index.html                 # Main web dashboard interface
│   ├── css/
│   │   └── style.css              # Command center styling
│   └── js/
│       └── map.js                 # Leaflet map logic & backend integration
└── README.md                      # Project documentation

```

---

## 2. Setup & Installation

### Prerequisites

* Python 3.9 or higher
* [`osmium-tool`](https://osmcode.org/osmium-tool/) — a command-line tool used to quickly clip small areas out of the local road-data file (see below). Install with `brew install osmium-tool` (macOS) or your package manager's equivalent on Linux.

### Installation

Clone the repository, create a virtual environment, and install the backend dependencies into it:

```bash
git clone https://github.com/YOUR_USERNAME/Aegis-Route.git
cd Aegis-Route/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

```

> **Use a virtual environment, not your system/conda Python.** A dependency like `pyrosm` (used for the real road network) only exists inside `.venv` once installed there, running `python app.py` from a different environment (e.g. a `(base)` conda shell) will fail with an import error even though installation "succeeded" earlier in some other environment.

> **Note:** The application uses in-memory graph models and lightweight local state. No external databases or API keys are required.

### One-time: download the road data

Routing reads real street data from a local file instead of a live API call, this is what makes it fast and not dependent on a shared internet service (see section 6). Download it once:

```bash
cd backend
mkdir -p data
curl -L -o data/india-central-zone.osm.pbf https://download.geofabrik.de/asia/india/central-zone-latest.osm.pbf

```

This covers central India (Madhya Pradesh and neighboring states, including Bhopal) and is **not** committed to the repo (a few hundred MB), every clone needs to download it once. The app's default location (Bhopal) and any custom rescue base / disaster site you place both read from this same file; a point placed outside this region's coverage will fail with a clear "no road data found" error. To cover a different or larger region instead, grab a different extract from [Geofabrik's India downloads](https://download.geofabrik.de/asia/india.html) and update `OSM_PBF_PATH` in `backend/utils/graph_builder.py` to match its filename.

---

## 3. Usage

### Step 1: Start the Backend Server

Launch the Flask API from the `backend` directory, with the virtual environment active (your prompt should show `(.venv)` — if it doesn't, run `source .venv/bin/activate` first):

```bash
source .venv/bin/activate
python app.py

```

The server will run locally at:
`http://127.0.0.1:5000`

### Step 2: Launch the Frontend Interface

Open `frontend/index.html` directly in any web browser.

If your browser restricts local CORS requests when opening plain static files, serve the frontend using Python:

```bash
cd ../frontend
python -m http.server 8080

```

Then navigate to [`http://localhost:8080`](http://localhost:8080) in your web browser.

---

## 4. Features & Interface

1. **Interactive Hazards:** The map boots up with default active hazards (represented by red core rings and amber danger buffer zones).
2. **Placing Hazards:** Click anywhere on the map to drop a custom hazard zone. Use the range slider in the left rail to adjust the radius of newly placed hazards.
3. **Route Planning:** Select an algorithm from the control panel (`D* Lite`, `NSGA-II`, `A*`, or `Dijkstra`) and click **Calculate Route**.
4. **Comparative Analysis:** Click **Compare All Algorithms** to render paths side-by-side on the map along with telemetry metrics (distance, risk score, and compute time) in the right-hand panel.
5. **Resetting State:** Click **Reset Scenario** to clear all dynamic hazards and reset the algorithm cache.

---

## 5. Benchmarking & Chart Generation

To run performance tests and generate benchmark figures:

```bash
cd backend
source .venv/bin/activate
python benchmarks/runner.py

```

This generates four output files inside `backend/benchmarks/`:

* `benchmark_results.csv` — Execution timing and metric breakdown
* `execution_time_plot.png` — Compute speed comparative bar chart
* `pareto_front_plot.png` — NSGA-II distance vs. risk trade-off visualization
* `dstar_memory_plot.png` — Cache hit vs. full replanning speedup analysis

---

## 6. Spatial & Hazard Model Verification

The live app routes on a **real road network**, built by `utils/graph_builder.build_real_road_graph()` in two local steps: `osmium` first clips a small bounding box out of the regional OSM data file (`backend/data/india-central-zone.osm.pbf`, downloaded once per the setup step above), then `pyrosm` parses just that small result into a graph. (Asking `pyrosm` to filter the full regional file directly was measured at 70+ seconds per request regardless of area size — clipping first brings that under 3 seconds.) This is entirely local file processing, not a live API call -- no network dependency, no shared rate-limited third-party service. Verify it with:

```bash
cd backend
source .venv/bin/activate
python tests/verify_real_road_graph.py

```

Hazards and start/end points are real `{lat, lng}` coordinates — click anywhere on the map, or a raw OSM node id / omit either to fall back to nearest-node defaults. Verify the API layer with:

```bash
cd backend
source .venv/bin/activate
python tests/verify_real_network_api.py

```

`utils/graph_builder.py` also still has `build_city_graph()`, the original synthetic 15×15 demo grid — the live app and frontend no longer use it, but `backend/benchmarks/runner.py` does, so it's kept for that. Verify the grid + hazard-zone logic in isolation with:

```bash
cd backend
source .venv/bin/activate
python tests/verify_spatial_hazard.py

```

---

## 7. Troubleshooting

* **Frontend shows "Backend offline":** Ensure the Flask server is active and has not crashed due to port conflicts.
* **Routes are not drawing:** Open your browser console (`F12` → `Console`). Verify that network requests to `http://127.0.0.1:5000` are reaching the server cleanly.
* **Port 5000 is occupied:** If another service is using port 5000, update the port parameter in `backend/app.py` and modify `API_BASE` in `frontend/index.html` to match.
* **`Routing failed: ... requires pyrosm`:** The backend process isn't using the project's `.venv`. Check your terminal prompt — it should show `(.venv)`, not `(base)` or nothing. Run `source .venv/bin/activate` from `backend/` before `python app.py`.
* **`Routing failed: Missing OSM data file...`:** You haven't done the one-time road-data download yet (see section 2's "One-time: download the road data").
* **`Routing failed: ... requires the 'osmium' command-line tool`:** Install it — see section 2's Prerequisites.
* **Frontend shows old behavior after a code change:** Your browser cached the old `js/map.js`. Hard-refresh (`Cmd+Shift+R` on Mac) or open the page in a private/incognito window.
