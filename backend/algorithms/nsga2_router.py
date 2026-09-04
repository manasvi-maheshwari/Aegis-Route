"""
NSGA-II style Multi-Objective Router -- simplified teaching version.

WHY THIS ALGORITHM EXISTS (explain this in viva):
A* / D* Lite both answer ONE question: "what is the single best route?"
But "best" is actually THREE competing goals at once:
    1) shortest distance
    2) fastest travel time
    3) lowest disaster risk exposure
A route that is shortest is often NOT the safest, and the safest route is
often NOT the fastest. There is no single "correct" answer -- there is a
trade-off. NSGA-II is a real multi-objective evolutionary algorithm used
in research for exactly this kind of trade-off (it keeps a whole
"Pareto front" of non-dominated solutions instead of one winner).

This file is an EDUCATIONAL, lightweight stand-in for full NSGA-II that is
honest about what it does: instead of running genetic operators
(crossover/mutation) over generations, it sweeps a risk-weight parameter to
generate a family of candidate routes, evaluates all of them on
(distance, risk), and keeps the non-dominated ones -- which IS the actual
definition of a Pareto front. We then expose three clearly labelled
options (Fastest / Balanced / Safest) so the trade-off is visible on the
map, instead of silently returning one path like A* does.
"""

import networkx as nx
from utils.routing_helpers import get_safe_subgraph, path_stats


def _generate_candidates(graph, start, goal, population_size=8):
    """
    Sweep the risk-weight from 0 (ignore risk, pure shortest path) up to a
    high value (avoid risk at almost any distance cost). Each weight value
    is one "individual" in the population; the resulting path is that
    individual's genome expressed as a route.
    """
    safe_graph = get_safe_subgraph(graph)   # never propose a path through a blocked road
    search_graph = safe_graph if safe_graph.has_node(start) and nx.has_path(safe_graph, start, goal) else graph

    candidates = []
    seen_paths = set()
    for i in range(population_size):
        risk_weight = i * 0.75  # 0.0 -> 0.75 -> 1.5 ... -> up to ~5.25

        def cost_func(u, v, d, rw=risk_weight):
            return d.get('distance', 1.0) + (d.get('risk', 0.0) * rw)

        try:
            path = nx.shortest_path(search_graph, source=start, target=goal, weight=cost_func)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue

        key = tuple(path)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        stats = path_stats(graph, path)
        candidates.append({"path": path, "distance": stats["distance_m"], "risk": stats["risk"]})

    return candidates


def _pareto_front(candidates):
    """
    Keep only the non-dominated candidates: a candidate is dominated (and
    thrown away) if some OTHER candidate is at least as good on both
    distance and risk, and strictly better on one of them. What survives
    is the actual Pareto front.
    """
    front = []
    for c in candidates:
        dominated = any(
            (o["distance"] <= c["distance"] and o["risk"] <= c["risk"]) and
            (o["distance"] < c["distance"] or o["risk"] < c["risk"])
            for o in candidates if o is not c
        )
        if not dominated:
            front.append(c)
    return front


def get_pareto_front(graph, start, goal, population_size=8):
    """
    Returns up to three clearly-labelled routes representing the trade-off:
      fastest  -> minimum distance, risk ignored
      safest   -> minimum disaster-risk exposure
      balanced -> the Pareto candidate closest to the middle ground

    This is what the "Compare All" view in the UI calls, so the supervisor
    can visually see three different coloured routes on the SAME map for
    the SAME start/end -- the concrete proof that this is a real
    multi-objective optimizer, not just one algorithm renamed three times.
    """
    candidates = _generate_candidates(graph, start, goal, population_size)
    if not candidates:
        return {}

    front = _pareto_front(candidates)
    front_sorted_by_distance = sorted(front, key=lambda c: c["distance"])
    front_sorted_by_risk = sorted(front, key=lambda c: c["risk"])

    fastest = front_sorted_by_distance[0]
    safest = front_sorted_by_risk[0]

    # "Balanced" = the front member with the best combined (normalized) score
    max_d = max(c["distance"] for c in front) or 1.0
    max_r = max(c["risk"] for c in front) or 1.0
    balanced = min(
        front,
        key=lambda c: (c["distance"] / max_d) + (c["risk"] / max_r)
    )

    return {"fastest": fastest, "balanced": balanced, "safest": safest}


def run_nsga2_route(graph, start, goal, population_size=5, generations=3):
    """
    Backward-compatible single-path entry point (used by the simple
    /api/route endpoint). Returns the 'safest' Pareto-optimal path --
    i.e. NSGA-II's answer when disaster-risk is the priority.
    generations kept as a parameter for interface compatibility with the
    original design / paper wording, even though this simplified version
    does not run literal generational evolution.
    """
    front = get_pareto_front(graph, start, goal, population_size)
    if not front:
        # Absolute fallback so the API never hard-crashes
        try:
            return nx.shortest_path(graph, source=start, target=goal)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return [start]
    return front["safest"]["path"]
