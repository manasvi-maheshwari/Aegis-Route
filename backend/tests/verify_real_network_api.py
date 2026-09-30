import os
import sys
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as appmod

failures = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        failures.append(label)


client = appmod.app.test_client()


def post(path, body):
    return client.post(path, json=body)


# 1. No start/end -- falls back to nearest-node defaults, still succeeds
r = post('/api/route', {"algorithm": "dijkstra", "custom_hazards": []})
body = r.get_json()
check("no start/end still succeeds (nearest-node defaults)", r.status_code == 200 and body["status"] == "success")
check("default route has a plausible non-zero distance", body.get("distance_m", 0) > 0)

# 2. start/end given as {lat, lng} points (e.g. a map click), resolved to real nodes
r = post('/api/route', {
    "algorithm": "dijkstra",
    "start": {"lat": 12.9716, "lng": 79.1594},
    "end": {"lat": 12.9750, "lng": 79.1630},
})
body = r.get_json()
check("accepts {lat,lng} start/end points, resolved to nearest real nodes",
      r.status_code == 200 and body["status"] == "success" and body.get("distance_m", 0) > 0)

# 2b. Regression guard for the "far apart points silently snap to the wrong
# place" bug -- a point well within the network's ~5km coverage radius must
# resolve to a node very close to where it was actually requested.
r = post('/api/route', {
    "algorithm": "dijkstra",
    "start": {"lat": 12.99, "lng": 79.14},
    "end": {"lat": 12.95, "lng": 79.18},
})
body = r.get_json()
resolved_start = body.get("path", [[None, None]])[0]
check("a point well within network coverage resolves close to where it was requested",
      resolved_start[0] is not None and math.dist(resolved_start, [12.99, 79.14]) < 0.002)  # ~200m

# 3. An explicit lat/lng hazard actually changes the route -- use a short
# route straddling the hazard center directly, rather than the network-wide
# defaults, so it's guaranteed to actually pass near the hazard.
straddle = {"start": {"lat": 12.9716 - 0.004, "lng": 79.1594}, "end": {"lat": 12.9716 + 0.004, "lng": 79.1594}}
r_clear = post('/api/route', {"algorithm": "d_star", "custom_hazards": [], **straddle})
client.post('/api/reset')  # D* Lite remembers the last plan -- clear it so the hazard below forces a fresh one
r_hazard = post('/api/route', {
    "algorithm": "d_star",
    "custom_hazards": [{"lat": 12.9716, "lng": 79.1594, "radius": 1}],
    **straddle,
})
d_clear = r_clear.get_json().get("distance_m", 0)
d_hazard = r_hazard.get_json().get("distance_m", 0)
check("a real-coordinate hazard actually perturbs the route",
      r_hazard.status_code == 200 and d_hazard != d_clear)

# 4. /api/compare-all works across every algorithm + NSGA-II's Pareto front
r = post('/api/compare-all', {})
body = r.get_json()
check("compare-all succeeds", r.status_code == 200 and body["status"] == "success")
if body.get("status") == "success":
    results = body["results"]
    check("compare-all includes all 3 single-path algorithms",
          all(results.get(k, {}).get("status") == "success" for k in ("a_star", "dijkstra", "d_star")))
    check("compare-all includes all 3 NSGA-II Pareto labels",
          set(results.get("nsga2", {}).keys()) == {"fastest", "balanced", "safest"})

print()
if failures:
    print(f"{len(failures)} CHECK(S) FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All checks passed.")
