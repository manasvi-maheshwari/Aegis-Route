"""
Applies disaster hazard zones onto the road graph.

IMPORTANT DESIGN DECISION (mention this in the paper -- it's a genuine
small contribution, not just plumbing):

A real flood/disaster zone is not just "safe" vs "100% impassable". There
is a middle ground: roads NEAR a hazard are risky (partially flooded,
debris, reduced visibility) but a vehicle CAN still use them if there is
no better option. Roads at the CENTER of a hazard are truly impassable.

So every hazard now has TWO rings:
    - CORE ring   (radius)              -> blocked = True  (never usable)
    - DANGER ring (radius * BUFFER_MULT) -> high risk, but NOT blocked
                                            (usable, but costly)

This is what makes the multi-objective algorithm (NSGA-II) actually
meaningful: a "fastest" route can cut through the danger ring to save
distance, while a "safest" route avoids the danger ring completely even
though it's a longer trip. Without this graduated model, every route
would just be forced to detour around one single blocked zone -- and there
is nothing to actually trade off.
"""

import math

CORE_RISK = 10000.0     # cost added to roads inside the impassable core
DANGER_RISK = 350.0     # cost added to roads inside the risky-but-passable ring
DANGER_BUFFER_MULT = 1.8  # danger ring extends this many times past the core radius

METERS_PER_RADIUS_UNIT = 500.0

EARTH_RADIUS_M = 6371000.0


def _haversine_m(lat1, lng1, lat2, lng2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def apply_hazard_zones(G, hazard_zones):
    """
    Scans every node/edge in the graph. Anything inside a hazard's CORE
    radius is marked blocked (impassable). Anything further out, inside
    the wider DANGER ring, is left passable but given a real risk cost.
    """
    scale = 0.005
    base_lat, base_lng = 12.9716, 79.1594

    for zone in hazard_zones:
        if 'lat' in zone and 'lng' in zone:
            h_lat, h_lng = zone['lat'], zone['lng']
        else:
            h_lat = base_lat + (zone['grid_x'] * scale)
            h_lng = base_lng + (zone['grid_y'] * scale)

        core_radius_m = zone.get('radius', 2) * METERS_PER_RADIUS_UNIT
        danger_radius_m = core_radius_m * DANGER_BUFFER_MULT

        for node in G.nodes():
            n_lat = G.nodes[node]['lat']
            n_lng = G.nodes[node]['lng']
            dist_m = _haversine_m(n_lat, n_lng, h_lat, h_lng)

            if dist_m <= core_radius_m:
                # Inside the core -> completely impassable
                G.nodes[node]['risk_score'] = CORE_RISK
                for neighbor in G.neighbors(node):
                    G[node][neighbor]['risk'] = CORE_RISK
                    G[node][neighbor]['blocked'] = True

            elif dist_m <= danger_radius_m:
                # Inside the wider danger ring -> risky, but still usable.
                # Only raise risk if this road isn't already marked worse
                # by an overlapping hazard's core.
                if G.nodes[node]['risk_score'] < DANGER_RISK:
                    G.nodes[node]['risk_score'] = DANGER_RISK
                for neighbor in G.neighbors(node):
                    if not G[node][neighbor].get('blocked', False):
                        G[node][neighbor]['risk'] = max(G[node][neighbor].get('risk', 0.0), DANGER_RISK)

    return G
