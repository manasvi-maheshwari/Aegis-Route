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

        core_radius_deg = zone.get('radius', 2) * scale
        danger_radius_deg = core_radius_deg * DANGER_BUFFER_MULT

        for node in G.nodes():
            n_lat = G.nodes[node]['lat']
            n_lng = G.nodes[node]['lng']
            dist = math.sqrt((n_lat - h_lat) ** 2 + (n_lng - h_lng) ** 2)

            if dist <= core_radius_deg:
                # Inside the core -> completely impassable
                G.nodes[node]['risk_score'] = CORE_RISK
                for neighbor in G.neighbors(node):
                    G[node][neighbor]['risk'] = CORE_RISK
                    G[node][neighbor]['blocked'] = True

            elif dist <= danger_radius_deg:
                # Inside the wider danger ring -> risky, but still usable.
                # Only raise risk if this road isn't already marked worse
                # by an overlapping hazard's core.
                if G.nodes[node]['risk_score'] < DANGER_RISK:
                    G.nodes[node]['risk_score'] = DANGER_RISK
                for neighbor in G.neighbors(node):
                    if not G[node][neighbor].get('blocked', False):
                        G[node][neighbor]['risk'] = max(G[node][neighbor].get('risk', 0.0), DANGER_RISK)

    return G
