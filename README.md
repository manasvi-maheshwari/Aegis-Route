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
│   │   ├── graph_builder.py       # Constructs the 15x15 grid road network
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
├── paper/                         # Documentation and research papers
├── presentation/                  # Project slide decks
└── README.md                      # Project documentation

```

---

## 2. Setup & Installation

### Prerequisites

* Python 3.9 or higher

### Installation

Clone the repository and install the backend dependencies:

```bash
git clone https://github.com/YOUR_USERNAME/Aegis-Route.git
cd Aegis-Route/backend
pip install -r requirements.txt

```

> **Note:** The application uses in-memory graph models and lightweight local state. No external databases or API keys are required.

---

## 3. Usage

### Step 1: Start the Backend Server

Launch the Flask API from the `backend` directory:

```bash
python app.py

```

The server will run locally at:
`[http://127.0.0.1:5000](http://127.0.0.1:5000)`

### Step 2: Launch the Frontend Interface

Open `frontend/index.html` directly in any web browser.

If your browser restricts local CORS requests when opening plain static files, serve the frontend using Python:

```bash
cd ../frontend
python -m http.server 8080

```

Then navigate to `http://localhost:8080` in your web browser.

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
python benchmarks/runner.py

```

This generates four output files inside `backend/benchmarks/`:

* `benchmark_results.csv` — Execution timing and metric breakdown
* `execution_time_plot.png` — Compute speed comparative bar chart
* `pareto_front_plot.png` — NSGA-II distance vs. risk trade-off visualization
* `dstar_memory_plot.png` — Cache hit vs. full replanning speedup analysis

---

## 6. Troubleshooting

* **Frontend shows "Backend offline":** Ensure the Flask server is active and has not crashed due to port conflicts.
* **Routes are not drawing:** Open your browser console (`F12` $\rightarrow$ `Console`). Verify that network requests to `[http://127.0.0.1:5000](http://127.0.0.1:5000)` are reaching the server cleanly.
* **Port 5000 is occupied:** If another service is using port 5000, update the port parameter in `backend/app.py` and modify `API_BASE` in `frontend/index.html` to match.