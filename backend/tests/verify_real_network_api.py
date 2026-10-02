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


# 1. No start/end -- falls back to the default cached Vellore network, still succeeds
r = post('/api/route', {"algorithm": "dijkstra", "custom_hazards": []})
body = r.get_json()
check("no start/end still succeeds (default cached network)", r.status_code == 200 and body["status"] == "success")
check("default route has a plausible non-zero distance", body.get("distance_m", 0) > 0)

# 2. start/end given as {lat, lng} points near Bhopal -- dynamic area fetch,
# resolved close to where actually requested
r = post('/api/route', {
    "algorithm": "dijkstra",
    "start": {"lat": 23.28, "lng": 77.39},
    "end": {"lat": 23.24, "lng": 77.43},
})
body = r.get_json()
resolved_start = body.get("path", [[None, None]])[0]
check("points near Bhopal succeed and resolve close to where requested",
      r.status_code == 200 and body["status"] == "success"
      and resolved_start[0] is not None and math.dist(resolved_start, [23.28, 77.39]) < 0.005)  # ~500m

# 3. The actual new feature: start/end far from Bhopal (a different city,
# Indore -- still within the downloaded region's coverage, see README)
# now succeed too -- a real network is fetched dynamically around wherever
# the two points are, not just the one fixed demo location.
r = post('/api/route', {
    "algorithm": "dijkstra",
    "start": {"lat": 22.7196, "lng": 75.8577},
    "end": {"lat": 22.7396, "lng": 75.8377},
})
body = r.get_json()
check("routing works for a completely different city, not just Bhopal",
      r.status_code == 200 and body.get("status") == "success" and body.get("distance_m", 0) > 0)

# 4. Two points implausibly far apart (opposite sides of the world) are
# rejected with a clear error instead of attempting to fetch a
# continent-sized network.
r = post('/api/route', {
    "algorithm": "dijkstra",
    "start": {"lat": 23.2599, "lng": 77.4126},
    "end": {"lat": 40.7128, "lng": -74.0060},  # New York
})
body = r.get_json()
check("two points too far apart are rejected with a clear error",
      r.status_code == 400 and "apart" in body.get("message", ""))

# 5. An explicit lat/lng hazard actually changes the route -- use a short
# route straddling the hazard center directly, so it's guaranteed to
# actually pass near the hazard.
straddle = {"start": {"lat": 23.2599 - 0.004, "lng": 77.4126}, "end": {"lat": 23.2599 + 0.004, "lng": 77.4126}}
r_clear = post('/api/route', {"algorithm": "d_star", "custom_hazards": [], **straddle})
client.post('/api/reset')  # D* Lite remembers the last plan -- clear it so the hazard below forces a fresh one
r_hazard = post('/api/route', {
    "algorithm": "d_star",
    "custom_hazards": [{"lat": 23.2599, "lng": 77.4126, "radius": 1}],
    **straddle,
})
d_clear = r_clear.get_json().get("distance_m", 0)
d_hazard = r_hazard.get_json().get("distance_m", 0)
check("a real-coordinate hazard actually perturbs the route",
      r_hazard.status_code == 200 and d_hazard != d_clear)

# 6. /api/compare-all works across every algorithm + NSGA-II's Pareto front
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
