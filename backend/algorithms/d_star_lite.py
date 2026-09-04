"""
D* Lite (Lifelong Planning A*) -- simplified teaching version.

WHY THIS ALGORITHM EXISTS (explain this in viva):
Plain A* solves the map ONE TIME, assuming nothing changes. But in a real
disaster, new hazards (a flooded road, a collapsed bridge) can appear WHILE
a rescue vehicle is already driving. If you used plain A*, you'd have to
throw away the whole route and search the ENTIRE map again from scratch
every single time a new hazard is reported -- slow, and wasteful.

D* Lite fixes this: it remembers the route it already calculated. When a
new hazard shows up, it first checks "does my old route still avoid it?"
  - If YES -> reuse the old route instantly. Zero re-search needed.
  - If NO  -> only THEN does it run a fresh search.

So D* Lite behaves exactly like A* in terms of ROUTE QUALITY (same safe
path), but it is much cheaper to keep updating as hazards keep changing --
that is its real advantage, and that's the answer to "why not just use A*?"
"""

from utils.routing_helpers import find_safe_path, risk_cost


class DStarLite:

    # Class-level memory shared across requests: remembers the last route
    # found for each (start, goal) pair, like a rescue vehicle remembering
    # the road it is currently driving on.
    _path_cache = {}

    def __init__(self, graph, start, goal):
        self.graph = graph
        self.start = start
        self.goal = goal

        # These two flags get read by app.py after get_path() runs, so the
        # API (and the UI) can honestly report what actually happened.
        self.was_reused = False     # True = reused memory, no search ran
        self.is_fully_safe = True   # False = had to cross a hazard (no choice)

    @classmethod
    def reset_memory(cls):
        """Call this when the demo scenario is reset / cleared."""
        cls._path_cache.clear()

    def _path_still_safe(self, path):
        """Check every road on the old path -- has any of it become blocked?"""
        for u, v in zip(path, path[1:]):
            edge = self.graph.get_edge_data(u, v)
            if edge is None or edge.get('blocked', False):
                return False
        return True

    def get_path(self):
        key = (self.start, self.goal)
        cached_path = DStarLite._path_cache.get(key)

        # Step 1: can we just reuse what we already know?
        if cached_path and self._path_still_safe(cached_path):
            self.was_reused = True
            self.is_fully_safe = True
            return cached_path

        # Step 2: memory is missing or broken by a new hazard -> replan.
        self.was_reused = False
        path, fully_safe = find_safe_path(self.graph, self.start, self.goal, weight=risk_cost)
        self.is_fully_safe = fully_safe

        if path:
            DStarLite._path_cache[key] = path   # remember it for next time
            return path

        # No route exists at all (start or goal totally cut off).
        return [self.start]
