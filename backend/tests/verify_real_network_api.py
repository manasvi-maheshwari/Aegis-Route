import os
import sys

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


# 1. Default (omitted network) behaves exactly like before -- the grid, unchanged
r = post('/api/route', {"start": [0, 0], "end": [14, 14], "algorithm": "dijkstra", "custom_hazards": []})
body = r.get_json()
check("omitting network defaults to grid mode and succeeds", r.status_code == 200 and body["status"] == "success")
check("grid-mode default route matches the known baseline distance",
      abs(body.get("distance_m", 0) - 12348.8) < 1.0)

# 2. network='real' with no start/end -- falls back to nearest-node defaults
r = post('/api/route', {"network": "real", "algorithm": "dijkstra", "custom_hazards": []})
body = r.get_json()
check("network=real with no start/end still succeeds", r.status_code == 200 and body["status"] == "success")
check("real-mode route has a plausible non-zero distance", body.get("distance_m", 0) > 0)

# 2b. network='real' with start/end given as {lat, lng} points (e.g. a map click)
r = post('/api/route', {
    "network": "real", "algorithm": "dijkstra",
    "start": {"lat": 12.9716, "lng": 79.1594},
    "end": {"lat": 12.9750, "lng": 79.1630},
})
body = r.get_json()
check("network=real accepts {lat,lng} start/end points, resolved to nearest real nodes",
      r.status_code == 200 and body["status"] == "success" and body.get("distance_m", 0) > 0)

# 3. network='real' with an explicit lat/lng hazard actually changes the route
r_clear = post('/api/route', {"network": "real", "algorithm": "d_star", "custom_hazards": []})
r_hazard = post('/api/route', {
    "network": "real", "algorithm": "d_star",
    "custom_hazards": [{"lat": 12.9716, "lng": 79.1594, "radius": 1}],
})
d_clear = r_clear.get_json().get("distance_m", 0)
d_hazard = r_hazard.get_json().get("distance_m", 0)
check("a real-coordinate hazard actually perturbs the real-network route",
      r_hazard.status_code == 200 and d_hazard != d_clear)

# 4. Invalid network value is rejected cleanly, not a 500
r = post('/api/route', {"network": "bogus"})
check("invalid network value returns a clean 400, not a crash", r.status_code == 400)

# 5. /api/compare-all works in real mode across every algorithm + NSGA-II's Pareto front
r = post('/api/compare-all', {"network": "real"})
body = r.get_json()
check("compare-all succeeds in real mode", r.status_code == 200 and body["status"] == "success")
if body.get("status") == "success":
    results = body["results"]
    check("compare-all real mode includes all 3 single-path algorithms",
          all(results.get(k, {}).get("status") == "success" for k in ("a_star", "dijkstra", "d_star")))
    check("compare-all real mode includes all 3 NSGA-II Pareto labels",
          set(results.get("nsga2", {}).keys()) == {"fastest", "balanced", "safest"})

print()
if failures:
    print(f"{len(failures)} CHECK(S) FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All checks passed.")
