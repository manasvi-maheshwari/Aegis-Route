import networkx as nx


def risk_cost(u, v, d):
    """Standard cost: physical distance + disaster risk penalty."""
    return d.get('distance', 1.0) + d.get('risk', 0.0)


def get_safe_subgraph(graph):
    """
    Returns a copy of the graph with every 'blocked' road removed completely.
    This is what 'impassable' should actually mean -- a heavy cost penalty is
    NOT the same as a road being gone, because with enough penalty weight an
    algorithm can still be forced to cross it if that's the only option left
    on paper. Removing the edge is the only way to guarantee it is never used
    unless truly no other route exists.
    """
    blocked_edges = [(u, v) for u, v, d in graph.edges(data=True) if d.get('blocked', False)]
    H = graph.copy()
    H.remove_edges_from(blocked_edges)
    return H


def find_safe_path(graph, start, goal, weight=risk_cost):
    """
    Two-stage search used by every algorithm in this project:
      1. Try to reach the goal using ONLY unblocked roads.
      2. If that is impossible (goal is cut off / surrounded by hazards),
         fall back to the full graph as a last resort and say so honestly.

    Returns: (path, is_fully_safe)
      is_fully_safe = True  -> path never touches a blocked road
      is_fully_safe = False -> no safe route exists; this is the best
                               available route but it crosses a hazard
    """
    safe_graph = get_safe_subgraph(graph)
    try:
        path = nx.shortest_path(safe_graph, source=start, target=goal, weight=weight)
        return path, True
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        try:
            path = nx.shortest_path(graph, source=start, target=goal, weight=weight)
            return path, False
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None, False


def path_stats(graph, path):
    """Total distance (meters) and total risk exposure for a computed path."""
    if not path or len(path) < 2:
        return {"distance_m": 0.0, "risk": 0.0, "hops": 0}
    dist, risk = 0.0, 0.0
    for u, v in zip(path, path[1:]):
        edge = graph.get_edge_data(u, v, {})
        dist += edge.get('distance', 0.0)
        risk += edge.get('risk', 0.0)
    return {"distance_m": round(dist, 1), "risk": round(risk, 1), "hops": len(path) - 1}
