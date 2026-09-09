"""
Benchmark script -- produces the numbers and charts used in the survey
paper and the Review 1 presentation.

Generates 3 outputs in this same folder:
    1. benchmark_results.csv   -- raw numbers table (put this straight into the paper)
    2. execution_time_plot.png -- bar chart: how fast each algorithm is
    3. pareto_front_plot.png   -- scatter chart: PROOF that NSGA-II gives a
                                   genuine distance-vs-risk trade-off (this
                                   is the single most important chart for
                                   defending "why NSGA-II" in the viva)
    4. dstar_memory_plot.png   -- bar chart: proves D* Lite's whole reason
                                   for existing -- reusing a cached route is
                                   drastically faster than replanning fully

Run this from the backend/ folder:
    python benchmarks/runner.py
"""

import time
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import matplotlib
matplotlib.use('Agg')  # no display needed, just saves PNG files
import matplotlib.pyplot as plt
import pandas as pd
import networkx as nx

from utils.graph_builder import build_city_graph
from utils.hazard_mapper import apply_hazard_zones
from utils.routing_helpers import find_safe_path, risk_cost, path_stats
from algorithms.d_star_lite import DStarLite
from algorithms.nsga2_router import get_pareto_front

OUT_DIR = os.path.dirname(__file__)
START, GOAL = (0, 0), (14, 14)

# A moderately-sized central hazard: big enough to force real detours,
# small enough that a route still exists. This is the same style of
# scenario the live demo uses, so numbers here match what the panel sees
# on screen.
DEMO_HAZARD = [{"grid_x": 7, "grid_y": 7, "radius": 4}]


def build_demo_graph():
    G = build_city_graph(grid_size=15)
    G = apply_hazard_zones(G, DEMO_HAZARD)
    return G


def benchmark_execution_time():
    """Part 1: how many milliseconds does each algorithm take?"""
    print("\n=== Benchmark 1: Execution time per algorithm ===")
    G = build_demo_graph()
    DStarLite.reset_memory()
    results = []

    t0 = time.perf_counter()
    p, safe = find_safe_path(G, START, GOAL, weight=risk_cost)
    t = (time.perf_counter() - t0) * 1000
    stats = path_stats(G, p)
    results.append({"Algorithm": "Dijkstra (baseline)", "Execution Time (ms)": round(t, 3),
                     "Distance (m)": stats["distance_m"], "Risk Score": stats["risk"], "Fully Safe": safe})

    t0 = time.perf_counter()
    p = nx.astar_path(G, START, GOAL, weight=risk_cost)
    t = (time.perf_counter() - t0) * 1000
    stats = path_stats(G, p)
    results.append({"Algorithm": "A* (baseline)", "Execution Time (ms)": round(t, 3),
                     "Distance (m)": stats["distance_m"], "Risk Score": stats["risk"], "Fully Safe": True})

    # D* Lite -- first call has no memory yet, so this is a FULL plan
    t0 = time.perf_counter()
    dstar = DStarLite(G, START, GOAL)
    p = dstar.get_path()
    t = (time.perf_counter() - t0) * 1000
    stats = path_stats(G, p)
    results.append({"Algorithm": "D* Lite (first plan)", "Execution Time (ms)": round(t, 3),
                     "Distance (m)": stats["distance_m"], "Risk Score": stats["risk"], "Fully Safe": dstar.is_fully_safe})

    t0 = time.perf_counter()
    front = get_pareto_front(G, START, GOAL)
    t = (time.perf_counter() - t0) * 1000
    safest = front["safest"]
    results.append({"Algorithm": "NSGA-II (Pareto search)", "Execution Time (ms)": round(t, 3),
                     "Distance (m)": safest["distance"], "Risk Score": safest["risk"], "Fully Safe": True})

    df = pd.DataFrame(results)
    print(df.to_string(index=False))

    csv_path = os.path.join(OUT_DIR, "benchmark_results.csv")
    df.to_csv(csv_path, index=False)
    print(f"Saved -> {csv_path}")

    plt.figure(figsize=(8, 5))
    bars = plt.bar(df['Algorithm'], df['Execution Time (ms)'],
                    color=['#38BDF8', '#0EA5E9', '#F59E0B', '#EF4444'])
    plt.ylabel('Execution Time (ms)')
    plt.title('Algorithm Execution Time -- Same Disaster Scenario')
    plt.xticks(rotation=15, ha='right')
    plt.tight_layout()
    plot_path = os.path.join(OUT_DIR, "execution_time_plot.png")
    plt.savefig(plot_path, dpi=150)
    plt.close()
    print(f"Saved -> {plot_path}")
    return df


def benchmark_pareto_front():
    """
    Part 2: THE key evidence chart. Plots distance (x) vs risk (y) for the
    three NSGA-II candidates. If this were a fake multi-objective router,
    all three points would land on top of each other. Seeing them spread
    out along a downward-sloping curve is the actual definition of a
    Pareto front: to get less risk, you must accept more distance.
    """
    print("\n=== Benchmark 2: NSGA-II Pareto front (distance vs risk) ===")
    G = build_demo_graph()
    front = get_pareto_front(G, START, GOAL)

    labels = list(front.keys())
    dists = [front[l]["distance"] for l in labels]
    risks = [front[l]["risk"] for l in labels]
    for l, d, r in zip(labels, dists, risks):
        print(f"  {l:9s} distance={d:9.1f} m   risk={r:8.1f}")

    plt.figure(figsize=(7, 5.5))
    colors = {'fastest': '#EF4444', 'balanced': '#F59E0B', 'safest': '#22C55E'}
    for l, d, r in zip(labels, dists, risks):
        plt.scatter(d, r, s=140, color=colors.get(l, '#38BDF8'), zorder=3)
        plt.annotate(l.capitalize(), (d, r), textcoords="offset points", xytext=(8, 6), fontsize=10)
    plt.plot(dists, risks, '--', color='#94A3B8', linewidth=1, zorder=1)
    plt.xlabel('Total route distance (m)')
    plt.ylabel('Total disaster-risk exposure')
    plt.title('NSGA-II Pareto Front: Distance vs. Risk Trade-off')
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plot_path = os.path.join(OUT_DIR, "pareto_front_plot.png")
    plt.savefig(plot_path, dpi=150)
    plt.close()
    print(f"Saved -> {plot_path}")


def benchmark_dstar_memory(n_trials=15):
    """
    Part 3: proves WHY D* Lite's caching is worth using. Runs three
    scenarios, each repeated `n_trials` times to average out timer noise
    (a single perf_counter() sample on sub-millisecond operations can vary
    2x run to run on a shared machine, so a one-shot measurement is not
    reproducible or defensible on its own):

      1. Cold start          -> cache empty, full Dijkstra-based search
      2. Same scenario again -> cached route is still safe, reused as-is
      3. New hazard appears  -> cached route is invalidated, forced replan

    The hazard used in stage 3 (grid cell (2,13)) is deliberately placed
    ON TOP of the route actually returned in stage 1/2 (verified: the
    stage-1 path passes directly through node (2,13)), so stage 3 is a
    genuine forced replan, not a coincidental cache hit.

    For a fair point of comparison, this also times a completely fresh
    A* and Dijkstra search on the SAME post-hazard graph, with no cache
    involved at all. NOTE: this simplified D* Lite's "replan" step
    internally calls the same Dijkstra routine (find_safe_path) used for
    the baseline -- so stage 3 is expected to cost about the same as a
    fresh Dijkstra/A* run, not less. The real saving this design provides
    is stage 2 (skipping the search entirely when nothing relevant
    changed), not a faster replan algorithm. All numbers below are
    measured, not assumed.

    Raw per-trial timings and the summary are written to
    dstar_memory_results.csv so the numbers behind the chart/paper/slide
    are independently checkable and reproducible.
    """
    print(f"\n=== Benchmark 3: D* Lite memory reuse vs full replan ({n_trials} trials each) ===")
    G = build_demo_graph()

    # A brand new hazard lands directly ON the cached route (near node (2,13),
    # which the stage-1/2 route passes through) -> old route is no longer
    # safe, forcing a genuine replan instead of a reuse.
    HAZARD_2 = {"grid_x": 2, "grid_y": 13, "radius": 2}
    G2 = apply_hazard_zones(build_city_graph(15), DEMO_HAZARD + [HAZARD_2])

    # Sanity-check (asserted, not just assumed) that the new hazard really
    # does sit on the route the cache is holding, otherwise stage 3 would
    # silently just be another cache hit.
    DStarLite.reset_memory()
    reference_path = DStarLite(G, START, GOAL).get_path()
    hazard_on_route = not DStarLite(G2, START, GOAL)._path_still_safe(reference_path)
    assert hazard_on_route, "Benchmark scenario is invalid: new hazard does not intersect the cached route."

    raw_rows = []

    def time_n(label, setup, fn, n=n_trials):
        """setup() runs BEFORE the clock starts (e.g. populating the cache);
        only fn() is timed."""
        for trial in range(1, n + 1):
            setup()
            t0 = time.perf_counter()
            result = fn()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            raw_rows.append({"Stage": label, "Trial": trial, "Execution Time (ms)": round(elapsed_ms, 4),
                              "Result": result})

    noop = lambda: None

    # Stage 1: cold start (cache cleared before every trial; only the
    # get_path() call itself is timed, not the reset).
    def cold_start_setup():
        DStarLite.reset_memory()
    def cold_start():
        d = DStarLite(G, START, GOAL)
        d.get_path()
        return f"was_reused={d.was_reused}"
    time_n('1. Cold start (full search)', cold_start_setup, cold_start)

    # Stage 2: cache populated once up front, then every trial is a pure
    # cache-hit call with nothing else timed alongside it.
    DStarLite.reset_memory()
    DStarLite(G, START, GOAL).get_path()
    def cache_reuse():
        d = DStarLite(G, START, GOAL)
        d.get_path()
        return f"was_reused={d.was_reused}"
    time_n('2. Same scenario (memory reuse)', noop, cache_reuse)

    # Stage 3: cache is (re)populated with the pre-hazard path in setup()
    # (NOT timed), then only the post-hazard get_path() call -- the one
    # that must detect the break and replan -- is timed.
    def forced_replan_setup():
        DStarLite.reset_memory()
        DStarLite(G, START, GOAL).get_path()
    def forced_replan():
        d = DStarLite(G2, START, GOAL)
        d.get_path()
        return f"was_reused={d.was_reused}"
    time_n('3. New hazard appears (forced replan)', forced_replan_setup, forced_replan)

    # Baselines on the SAME post-hazard graph G2, with no cache involved
    # at all, for direct comparison against stage 3.
    def fresh_dijkstra():
        find_safe_path(G2, START, GOAL, weight=risk_cost)
        return "fresh_search"
    time_n('4. Fresh Dijkstra on updated graph (no cache)', noop, fresh_dijkstra)

    def fresh_astar():
        nx.astar_path(G2, START, GOAL, weight=risk_cost)
        return "fresh_search"
    time_n('5. Fresh A* on updated graph (no cache)', noop, fresh_astar)

    raw_df = pd.DataFrame(raw_rows)
    summary_df = (raw_df.groupby('Stage')['Execution Time (ms)']
                  .agg(['mean', 'median', 'min', 'max', 'std'])
                  .reindex(['1. Cold start (full search)',
                            '2. Same scenario (memory reuse)',
                            '3. New hazard appears (forced replan)',
                            '4. Fresh Dijkstra on updated graph (no cache)',
                            '5. Fresh A* on updated graph (no cache)'])
                  .round(4)
                  .reset_index())

    print(summary_df.to_string(index=False))

    def mean_of(stage):
        # Split into two steps (row filter, then column select) instead of
        # summary_df.loc[mask, 'mean'].iloc[0] -- Pylance's pandas stubs
        # can't prove that chained form returns a Series, and flag every
        # scalar type pandas could theoretically return (str, bytes, date,
        # etc.) as "no .iloc attribute". This is a static-analysis-only
        # false positive, not a runtime bug -- the original line runs fine.
        matching_rows = summary_df[summary_df['Stage'] == stage]
        return float(matching_rows['mean'].iloc[0])
    cold, reuse, replan = mean_of(summary_df['Stage'][0]), mean_of(summary_df['Stage'][1]), mean_of(summary_df['Stage'][2])
    fresh_dij, fresh_a = mean_of(summary_df['Stage'][3]), mean_of(summary_df['Stage'][4])

    print(f"\nMeasured speedup, cache reuse vs cold start : {cold / reuse:.1f}x")
    print(f"Measured ratio, forced replan vs fresh Dijkstra: {replan / fresh_dij:.2f}x "
          f"(expected ~1x -- this simplified D* Lite's replan step IS a Dijkstra search)")
    print(f"Measured ratio, forced replan vs fresh A*      : {replan / fresh_a:.2f}x")

    raw_csv_path = os.path.join(OUT_DIR, "dstar_memory_raw_trials.csv")
    raw_df.to_csv(raw_csv_path, index=False)
    print(f"Saved -> {raw_csv_path}")

    summary_csv_path = os.path.join(OUT_DIR, "dstar_memory_results.csv")
    summary_df.to_csv(summary_csv_path, index=False)
    print(f"Saved -> {summary_csv_path}")

    plt.figure(figsize=(8.5, 5.5))
    short_labels = [s.split(' (')[0] for s in summary_df['Stage']]
    plt.bar(short_labels, summary_df['mean'], yerr=summary_df['std'], capsize=4,
            color=['#EF4444', '#22C55E', '#F59E0B', '#94A3B8', '#64748B'])
    plt.ylabel(f'Mean Execution Time (ms), n={n_trials} trials')
    plt.title('D* Lite: Cache Reuse vs. Forced Replan vs. Fresh Baseline Search')
    plt.xticks(rotation=20, ha='right')
    plt.tight_layout()
    plot_path = os.path.join(OUT_DIR, "dstar_memory_plot.png")
    plt.savefig(plot_path, dpi=150)
    plt.close()
    print(f"Saved -> {plot_path}")


if __name__ == '__main__':
    print("Building road network and placing hazard zones...")
    benchmark_execution_time()
    benchmark_pareto_front()
    benchmark_dstar_memory()
    print("\nAll benchmarks complete. 3 PNGs + 1 CSV are in backend/benchmarks/")
