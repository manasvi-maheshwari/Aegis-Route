/* ============================================================================
   Disaster Rescue Router -- Frontend logic
   ----------------------------------------------------------------------------
   What this file does, in plain terms:
     1. Draws the Leaflet map and the fixed start/end markers.
     2. Lets the user click the map to drop a hazard zone (sends grid
        coordinates to the backend, draws two circles -- a solid "core"
        circle that is impassable, and a dashed "danger ring" that is risky
        but still usable -- matching exactly how the backend treats it).
     3. Calls the Flask backend (/api/route or /api/compare-all) and draws
        the resulting route(s) as coloured lines on the map.
     4. Fills in the right-hand "telemetry" panel with distance/risk/time
        numbers so the results aren't just visual -- they're measurable.

   API_BASE points at the Flask server. Change this one line if you deploy
   the backend somewhere other than localhost.
   ============================================================================ */


// Grid <-> real-world coordinate conversion. MUST match backend/utils/graph_builder.py
const BASE_LAT = 12.9716;
const BASE_LNG = 79.1594;
const SCALE = 0.005;
const START_NODE = [0, 0];
const END_NODE = [14, 14];

// Colours per algorithm, used consistently across single-run and compare-all
const ALGO_COLORS = {
  a_star:        '#38BDF8', // cyan
  dijkstra:      '#A78BFA', // purple
  d_star:        '#38BDF8', // cyan (same family as a_star -- both are "single best route" answers)
  nsga2:         '#22C55E', // green
  nsga2_fastest: '#EF4444', // red   -- shortest but riskiest
  nsga2_balanced:'#F59E0B', // amber -- middle ground
  nsga2_safest:  '#22C55E', // green -- longest but safest
};

const ALGO_EXPLAINERS = {
  d_star: `<strong>D* Lite</strong> remembers the last route it planned. If nothing near that route has changed, it reuses it instantly instead of re-searching the whole map — critical when hazards keep updating live.`,
  nsga2: `<strong>NSGA-II</strong> doesn't return one "best" route — real disaster routing has 3 competing goals (distance, time, risk) with no single winner. It returns a family of trade-off routes and we surface the Safest one by default here; use "Compare all" to see the full spread.`,
  a_star: `<strong>A*</strong> is the classic baseline: always finds the lowest-cost path for a FIXED map, but has no concept of memory or multiple objectives — it has to be run from scratch every time.`,
  dijkstra: `<strong>Dijkstra</strong> is A* without the distance heuristic guiding the search — same guaranteed-shortest-path result, just explores more nodes to get there. Kept as the classic baseline reference.`,
};

// ----------------------------------------------------------------------------
// Map setup
// ----------------------------------------------------------------------------
const map = L.map('map', { zoomControl: true }).setView([BASE_LAT + 0.035, BASE_LNG + 0.035], 13);

// Dark basemap so it matches the command-center theme
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

function gridToLatLng(gx, gy) {
  return [BASE_LAT + gx * SCALE, BASE_LNG + gy * SCALE];
}

// Fixed start (rescue base) and end (disaster site) markers
const startIcon = L.divIcon({ className: '', html: '<div style="background:#22C55E;width:14px;height:14px;border-radius:50%;border:2px solid #0E1626;box-shadow:0 0 8px #22C55E;"></div>' });
const endIcon = L.divIcon({ className: '', html: '<div style="background:#EF4444;width:14px;height:14px;border-radius:2px;border:2px solid #0E1626;box-shadow:0 0 8px #EF4444;"></div>' });
L.marker(gridToLatLng(...START_NODE), { icon: startIcon }).addTo(map).bindTooltip('Rescue base', { direction: 'top' });
L.marker(gridToLatLng(...END_NODE), { icon: endIcon }).addTo(map).bindTooltip('Disaster site', { direction: 'top' });

// ----------------------------------------------------------------------------
// State
// ----------------------------------------------------------------------------
let activeHazards = [];     // what we send to the backend: [{grid_x, grid_y, radius}, ...]
let hazardLayers = [];      // Leaflet circle layers currently drawn
let routeLayers = [];       // Leaflet polyline layers currently drawn
let selectedAlgo = 'd_star';

// ----------------------------------------------------------------------------
// Status log (left rail) -- small helper so every action leaves a trace,
// which doubles as a natural "here's what just happened" narration during
// a live demo.
// ----------------------------------------------------------------------------
function log(message, kind = '') {
  const el = document.getElementById('statusLog');
  const line = document.createElement('div');
  line.className = 'log-line' + (kind ? ' ' + kind : '');
  const time = new Date().toLocaleTimeString('en-GB', { hour12: false });
  line.textContent = `[${time}] ${message}`;
  el.prepend(line);
  while (el.children.length > 30) el.removeChild(el.lastChild);
}

// ----------------------------------------------------------------------------
// Clock + backend health check
// ----------------------------------------------------------------------------
function tickClock() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-GB', { hour12: false });
}
setInterval(tickClock, 1000);
tickClock();

async function checkBackend() {
  const dot = document.getElementById('connDot');
  const label = document.getElementById('connLabel');
  try {
    const res = await fetch(`${API_BASE}/api/hazards`);
    if (res.ok) {
      dot.className = 'dot online';
      label.textContent = 'Backend online';
      return true;
    }
    throw new Error('bad status');
  } catch (e) {
    dot.className = 'dot offline';
    label.textContent = 'Backend offline';
    return false;
  }
}
checkBackend();
setInterval(checkBackend, 8000);

// ----------------------------------------------------------------------------
// Hazard drawing -- draws BOTH rings so the map visually matches exactly
// what backend/utils/hazard_mapper.py does: a solid impassable core, and a
// wider dashed "risky but passable" danger ring (radius * 1.8).
// ----------------------------------------------------------------------------
const DANGER_BUFFER_MULT = 1.8;

function drawHazard(gx, gy, radiusGridUnits) {
  const center = gridToLatLng(gx, gy);
  const coreRadiusM = radiusGridUnits * 500;
  const dangerRadiusM = coreRadiusM * DANGER_BUFFER_MULT;

  const core = L.circle(center, {
    color: '#EF4444', fillColor: '#EF4444', fillOpacity: 0.35, weight: 2, radius: coreRadiusM,
  }).addTo(map);

  const danger = L.circle(center, {
    color: '#F59E0B', fillColor: '#F59E0B', fillOpacity: 0.08, weight: 2, dashArray: '6 6', radius: dangerRadiusM,
  }).addTo(map);

  hazardLayers.push(core, danger);

  // one-off pulse animation to make the placement feel deliberate
  const point = map.latLngToContainerPoint(center);
  const pulse = document.createElement('div');
  pulse.className = 'hazard-pulse';
  pulse.style.width = pulse.style.height = '40px';
  pulse.style.left = (point.x - 20) + 'px';
  pulse.style.top = (point.y - 20) + 'px';
  document.querySelector('.map-wrap').appendChild(pulse);
  setTimeout(() => pulse.remove(), 650);
}

function redrawAllHazards() {
  hazardLayers.forEach(l => map.removeLayer(l));
  hazardLayers = [];
  activeHazards.forEach(h => drawHazard(h.grid_x, h.grid_y, h.radius));
}

// Load the backend's default demo hazard on first page load
async function loadDefaultHazard() {
  try {
    const res = await fetch(`${API_BASE}/api/hazards`);
    const hazards = await res.json();
    hazards.forEach(h => {
      activeHazards.push({ grid_x: h.grid_x, grid_y: h.grid_y, radius: h.radius });
    });
    redrawAllHazards();
    log('Loaded default hazard scenario from backend.', 'info');
  } catch (e) {
    log('Could not load default hazard -- is the backend running?', 'err');
  }
}

// Click-to-add hazard
map.on('click', (e) => {
  const gx = Math.round((e.latlng.lat - BASE_LAT) / SCALE);
  const gy = Math.round((e.latlng.lng - BASE_LNG) / SCALE);
  const radius = parseInt(document.getElementById('hazardRadius').value, 10);

  activeHazards.push({ grid_x: gx, grid_y: gy, radius });
  drawHazard(gx, gy, radius);
  log(`Hazard placed at grid (${gx}, ${gy}), size ${radius}. Recalculate route to see the effect.`, 'info');
});

document.getElementById('hazardRadius').addEventListener('input', (e) => {
  document.getElementById('hazardRadiusVal').textContent = e.target.value;
});

// ----------------------------------------------------------------------------
// Route drawing
// ----------------------------------------------------------------------------
function clearRoutes() {
  routeLayers.forEach(l => map.removeLayer(l));
  routeLayers = [];
}

function drawRoute(path, color, weight = 5, dashArray = null) {
  const line = L.polyline(path, { color, weight, opacity: 0.9, dashArray }).addTo(map);
  routeLayers.push(line);
  return line;
}

function fitAllRoutes() {
  if (routeLayers.length === 0) return;
  const group = L.featureGroup(routeLayers);
  map.fitBounds(group.getBounds(), { padding: [40, 40] });
}

// ----------------------------------------------------------------------------
// Algorithm selector (segmented buttons)
// ----------------------------------------------------------------------------
document.querySelectorAll('.algo-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.algo-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedAlgo = btn.dataset.algo;
    document.getElementById('explainerBox').innerHTML = ALGO_EXPLAINERS[selectedAlgo] || '';
  });
});

// ----------------------------------------------------------------------------
// Telemetry panel updates
// ----------------------------------------------------------------------------
function showSingleTelemetry(result) {
  document.getElementById('telemetryEmpty').classList.add('hidden');
  document.getElementById('compareTableWrap').classList.add('hidden');
  const panel = document.getElementById('telemetrySingle');
  panel.classList.remove('hidden');

  document.getElementById('metDistance').textContent = `${(result.distance_m / 1000).toFixed(2)} km`;
  document.getElementById('metRisk').textContent = result.risk_score.toFixed(0);
  document.getElementById('metTime').textContent = `${result.time_ms.toFixed(2)} ms`;

  const safeEl = document.getElementById('metSafe');
  safeEl.textContent = result.fully_safe ? 'Fully safe' : 'Crosses hazard';
  safeEl.className = 'metric-value ' + (result.fully_safe ? 'good' : 'bad');

  const reusedCard = document.getElementById('metReusedCard');
  if (result.algorithm === 'd_star') {
    reusedCard.style.display = 'block';
    const reusedEl = document.getElementById('metReused');
    reusedEl.textContent = result.reused_previous_plan ? 'Reused cached route' : 'Full replan ran';
    reusedEl.className = 'metric-value ' + (result.reused_previous_plan ? 'good' : '');
  } else {
    reusedCard.style.display = 'none';
  }
}

function showCompareTable(rows) {
  document.getElementById('telemetryEmpty').classList.add('hidden');
  document.getElementById('telemetrySingle').classList.add('hidden');
  document.getElementById('compareTableWrap').classList.remove('hidden');

  const tbody = document.getElementById('compareTableBody');
  tbody.innerHTML = '';
  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><span style="color:${ALGO_COLORS[r.key] || '#fff'}">&#9679;</span> ${r.label}</td>
                     <td>${r.distance_m.toFixed(0)}</td>
                     <td>${r.risk_score.toFixed(0)}</td>
                     <td>${r.time_ms !== undefined ? r.time_ms.toFixed(2) : '–'}</td>`;
    tbody.appendChild(tr);
  });
}

// ----------------------------------------------------------------------------
// Run ONE selected algorithm
// ----------------------------------------------------------------------------
async function calculateRoute() {
  clearRoutes();
  log(`Running ${selectedAlgo.replace('_', ' ')}…`, 'info');

  try {
    const res = await fetch(`${API_BASE}/api/route`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start: START_NODE, end: END_NODE, algorithm: selectedAlgo, custom_hazards: activeHazards }),
    });
    const data = await res.json();

    if (data.status !== 'success') {
      log(data.message || 'Route computation failed.', 'err');
      return;
    }

    drawRoute(data.path, ALGO_COLORS[selectedAlgo] || '#38BDF8');
    fitAllRoutes();
    showSingleTelemetry(data);

    const safeNote = data.fully_safe ? 'fully safe route' : 'route crosses a hazard (no safer option exists)';
    log(`${selectedAlgo} done in ${data.time_ms.toFixed(2)} ms — ${safeNote}.`, data.fully_safe ? 'ok' : 'err');

  } catch (e) {
    log('Request failed. Is the Flask backend running on port 5000?', 'err');
  }
}

// ----------------------------------------------------------------------------
// Compare ALL algorithms at once
// ----------------------------------------------------------------------------
async function compareAll() {
  clearRoutes();
  log('Running all algorithms for comparison…', 'info');

  try {
    const res = await fetch(`${API_BASE}/api/compare-all`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start: START_NODE, end: END_NODE, custom_hazards: activeHazards }),
    });
    const data = await res.json();
    if (data.status !== 'success') {
      log('Comparison failed.', 'err');
      return;
    }

    const rows = [];
    const { results } = data;

    ['a_star', 'dijkstra', 'd_star'].forEach(key => {
      const r = results[key];
      if (r && r.status === 'success') {
        drawRoute(r.path, ALGO_COLORS[key], key === 'd_star' ? 5 : 3, key === 'dijkstra' ? '4 6' : null);
        rows.push({ key, label: key.replace('_', ' '), distance_m: r.distance_m, risk_score: r.risk_score, time_ms: r.time_ms });
      }
    });

    ['fastest', 'balanced', 'safest'].forEach(label => {
      const r = results.nsga2 && results.nsga2[label];
      if (r) {
        drawRoute(r.path, ALGO_COLORS['nsga2_' + label], 4, '2 4');
        rows.push({ key: 'nsga2_' + label, label: `NSGA-II (${label})`, distance_m: r.distance_m, risk_score: r.risk_score, time_ms: undefined });
      }
    });

    fitAllRoutes();
    showCompareTable(rows);
    log(`Compared ${rows.length} route options across 4 algorithms.`, 'ok');

  } catch (e) {
    log('Comparison request failed. Is the backend running?', 'err');
  }
}

// ----------------------------------------------------------------------------
// Reset scenario
// ----------------------------------------------------------------------------
async function resetScenario() {
  activeHazards = [];
  redrawAllHazards();
  clearRoutes();
  document.getElementById('telemetryEmpty').classList.remove('hidden');
  document.getElementById('telemetrySingle').classList.add('hidden');
  document.getElementById('compareTableWrap').classList.add('hidden');

  try {
    await fetch(`${API_BASE}/api/reset`, { method: 'POST' });
  } catch (e) { /* non-fatal */ }

  log('Scenario reset. D* Lite memory cleared.', 'info');
}

// ----------------------------------------------------------------------------
// Wire up buttons
// ----------------------------------------------------------------------------
document.getElementById('runBtn').addEventListener('click', calculateRoute);
document.getElementById('compareBtn').addEventListener('click', compareAll);
document.getElementById('resetBtn').addEventListener('click', resetScenario);

// ----------------------------------------------------------------------------
// Boot
// ----------------------------------------------------------------------------
loadDefaultHazard();
