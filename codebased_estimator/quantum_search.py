"""Bounded integer-boundary refinement of the unchanged quantum cost model.

This is an additional heuristic search, not a proof of local/global optimality.
In particular we sample important index/sorting thresholds, not every change
of the integer list-size proxies. No instance-specific parameters live here.
"""

from __future__ import annotations

from math import isqrt, log2


SEARCH_VERSION = "deterministic-boundary-refinement-v2"
REFINEMENT_POINT_BUDGET = 12000
_SHAPE_BUDGET = 2500
_STARTS = 4
_MIN_LOG_STEP = 1 / 1024


def _ceil_sqrt(value: int) -> int:
    return isqrt(value - 1) + 1 if value else 0


def boundary_candidates(u: int, f: int, ell: int, umax: int) -> dict[str, tuple[int, ...]]:
    """Return both sides of nearby exact integer cost thresholds.

    ``u`` is a feasible walk size, and f/ell satisfy its low-fanout domain.
    Integer roots preserve strict vs non-strict threshold inequalities even
    when counts cannot be represented by binary64. Only nearby depth levels
    are sampled; all integer proxy discontinuities are NOT enumerated.
    """
    from .quantum_costs import _L

    def levels(center, minimum):
        return range(max(minimum, center - 1), max(minimum, center + 1) + 1)

    def neighbors(thresholds):
        return tuple(sorted({x for t in thresholds for x in (t - 1, t, t + 1)
                             if 1 <= x <= umax}))

    u2 = u * u
    j1 = max(1, u2 >> f)
    g = ell - f
    j2 = (j1 * j1) >> g

    def output_threshold(count):
        first = _ceil_sqrt(count << g)
        # J1 is clamped to one, so this threshold already holds everywhere.
        return 1 if first <= 1 else _ceil_sqrt(first << f)

    return {
        "leaf_sort": neighbors(1 << j for j in levels(u.bit_length() - 1, 1)),
        "leaf_index": neighbors((1 << j) - 1 for j in levels(_L(u), 2)),
        "intermediate_sort": neighbors(_ceil_sqrt(1 << (f + j))
                                       for j in levels(j1.bit_length() - 1, 1)),
        "intermediate_index": neighbors(isqrt(((1 << j) - 2) << f) + 1
                                        for j in levels(_L(u2, f), 2)),
        "terminal_load_index": neighbors(isqrt(isqrt(((1 << j) - 2) << (ell + f))) + 1
                                         for j in levels(_L(u2 * u2, ell + f), 2)),
        "terminal_output": neighbors((output_threshold(1),)),
        "terminal_output_index": neighbors(output_threshold((1 << j) - 1)
                                           for j in levels((j2 + 1).bit_length(), 2)),
    }


def _walk_limit(V: int, ell: int) -> int:
    result = V // 2
    if (result * result - 1).bit_length() > ell:
        result = isqrt(1 << ell)
    return result


class _BudgetExhausted(Exception):
    pass


def refine_candidates(model, seeds, baseline, evaluate, *, point_budget=REFINEMENT_POINT_BUDGET):
    """Refine a few shapes after the original optimizer has finished.

    evaluate(sh,ell,p,d,u,f) returns the best integer b split and records the
    corresponding cost evaluations in the caller. A budget point is a new
    (ell,p,d,u,f), not a b evaluation or a cache hit. The old winner is retained
    even if no refinement can be completed. All loops have deterministic caps.
    """
    from .quantum_costs import _integer_exp2

    cache = {}
    best = baseline
    stats = dict(applied=False, point_budget=point_budget, candidate_points=0,
                 cache_hits=0, budget_exhausted=False, shape_budget_hits=0,
                 iteration_cap_hit=False, filter_scan_truncated=False,
                 boundary_iteration_cap_hit=False, polish_iteration_cap_hit=False,
                 polish_passes=0, polish_budget_hits=0,
                 refined_shapes=0, refinement_passes=0, neighbor_shapes=0, peak_cached_points=0,
                 boundary_categories=[], target_min_log2_step=_MIN_LOG_STEP,
                 baseline_time_log2=baseline.time_log2,
                 baseline_parameters=dict(baseline.parameters))
    categories = set()
    shape_counts = {}
    refined_shapes = set()
    shape_winners = {}
    capped_shapes = set()

    def at(sh, ell, p, d, u, f, cap):
        nonlocal best
        shape = (ell, p, d)
        key = shape + (u, f)
        if key in cache:
            stats["cache_hits"] += 1
            return cache[key]
        if len(cache) >= point_budget:
            stats["budget_exhausted"] = True
            raise _BudgetExhausted
        if shape_counts.get(shape, 0) >= cap:
            raise _BudgetExhausted
        value = evaluate(sh, ell, p, d, u, f)
        cache[key] = value
        shape_counts[shape] = shape_counts.get(shape, 0) + 1
        if value.time_log2 < best.time_log2:
            best = value
        return value

    def refine_shape(seed, allowance, *, polish=False):
        nonlocal best
        par = seed.parameters
        ell, p, d = (par[key] for key in ("ell", "p", "d"))
        shape = (ell, p, d)
        sh = model.shape(*shape)
        V = sh["V"]
        umax = _walk_limit(V, ell)
        cap = shape_counts.get(shape, 0) + allowance
        stats["refinement_passes"] += 1
        if polish:
            stats["polish_passes"] += 1
        refined_shapes.add(shape)
        candidates = [seed]

        def query(u, f):
            fmin = 0 if u == V else (u - 1).bit_length()
            f = max(fmin, min(ell, f))
            value = at(sh, ell, p, d, u, f, cap)
            candidates.append(value)
            return value

        def nearby_filters(u, center):
            fmin = 0 if u == V else (u - 1).bit_length()
            return sorted({max(fmin, min(ell, f)) for f in
                           (center - 1, center, center + 1, fmin, ell,
                            sh["R"].bit_length() - 1)})

        def scan_filters(candidate):
            u = candidate.parameters["u"]
            fmin = 0 if u == V else (u - 1).bit_length()
            center = candidate.parameters["a"] + candidate.parameters["b"]
            # Final scans are complete for ordinary small ell. Large ell uses
            # a stated bounded neighborhood, not a purported full scan.
            if ell - fmin <= 128:
                fs = range(fmin, ell + 1)
            else:
                stats["filter_scan_truncated"] = True
                fs = sorted(set(nearby_filters(u, center)) |
                            set(range(max(fmin, center - 32), min(ell, center + 32) + 1)))
            return min((query(u, f) for f in fs), key=lambda c: c.time_log2)

        try:
            center = par["a"] + par["b"]
            for u in sorted({1, umax, min(par["u"], umax), V}):
                for f in nearby_filters(u, center):
                    query(u, f)
            current = scan_filters(seed)
            # Two passes permit a full f scan to expose a new u neighborhood.
            for _ in range(2):
                current = min(candidates, key=lambda c: c.time_log2)
                dx = 1 / 8
                for _iteration in range(32):
                    old = current
                    u0 = min(current.parameters["u"], umax)
                    f0 = current.parameters["a"] + current.parameters["b"]
                    f0 = max((u0 - 1).bit_length(), f0)
                    us = {u0, max(1, u0 - 1), min(umax, u0 + 1)}
                    us.update(min(umax, _integer_exp2(max(0.0, log2(u0) + sign * dx)))
                              for sign in (-1, 1))
                    for f in sorted({max((u0 - 1).bit_length(), f0 - 1), f0, min(ell, f0 + 1)}):
                        boundaries = boundary_candidates(u0, f, ell, umax)
                        categories.update(boundaries)
                        for values in boundaries.values():
                            us.update(values)
                    for u in sorted(us, key=lambda x: (abs(x - u0), x)):
                        for f in nearby_filters(u, f0):
                            query(u, f)
                    current = min(candidates, key=lambda c: c.time_log2)
                    # The compatibility pass keeps v1's trajectory. In the
                    # additional polishing pass, unit-sized drift cannot pin
                    # a coarse exponent step forever. Shrinking a step does
                    # not discard any evaluated candidate or certify an error.
                    tiny_move = (polish and
                                 abs(log2(current.parameters["u"]) -
                                     log2(old.parameters["u"])) < dx / 4)
                    if current.time_log2 >= old.time_log2 - 1e-13 or tiny_move:
                        dx /= 2
                        if dx < _MIN_LOG_STEP:
                            break
                else:
                    stats["iteration_cap_hit"] = True
                    stats["polish_iteration_cap_hit" if polish else "boundary_iteration_cap_hit"] = True
                    capped_shapes.add(shape)
                # Scan the two best distinct sublist sizes, including full
                # lists if selected. Ordering and candidate retention are fixed.
                selected = {}
                for c in sorted(candidates, key=lambda c: c.time_log2):
                    selected.setdefault(c.parameters["u"], c)
                    if len(selected) == 2:
                        break
                for c in selected.values():
                    scan_filters(c)
        except _BudgetExhausted:
            if not stats["budget_exhausted"]:
                stats["shape_budget_hits"] += 1
                if polish:
                    stats["polish_budget_hits"] += 1
        winner = min(candidates, key=lambda c: c.time_log2)
        previous = shape_winners.get(shape)
        if previous is None or winner.time_log2 < previous.time_log2:
            shape_winners[shape] = winner
        return winner

    ordered = sorted(seeds, key=lambda c: c.time_log2)[:_STARTS]
    if ordered and point_budget > 0:
        stats["applied"] = True
        for seed in ordered:
            refine_shape(seed, _SHAPE_BUDGET)
            if stats["budget_exhausted"]:
                break
        # Check adjacent structural coordinates without changing/replacing the
        # original structural search. Each new point shares the same budget.
        if not stats["budget_exhausted"] and best.parameters["branch"] != "direct":
            par = best.parameters
            stride = 4 if model.algorithm == "QSS" else 2
            neighbors = [(par["ell"] + sign * stride, par["p"], par["d"]) for sign in (-1, 1)]
            neighbors += [(par["ell"], par["p"] + sign * 4, par["d"]) for sign in (-1, 1)]
            if model.algorithm == "QMMT+":
                neighbors += [(par["ell"], par["p"], par["d"] + sign * 2) for sign in (-1, 1)]
            adjacent = []
            try:
                for ell, p, d in neighbors:
                    sh = model.shape(ell, p, d)
                    if sh is None:
                        continue
                    u = min(par["u"], _walk_limit(sh["V"], ell))
                    f = max((u - 1).bit_length(), min(ell, par["a"] + par["b"]))
                    c = at(sh, ell, p, d, u, f, shape_counts.get((ell, p, d), 0) + 1)
                    adjacent.append(c)
                    stats["neighbor_shapes"] += 1
                for c in sorted(adjacent, key=lambda c: c.time_log2)[:2]:
                    refine_shape(c, 1000)
            except _BudgetExhausted:
                pass
    # Retain every v1 candidate before adding a new search trajectory. Prior
    # iteration-limit flags stay visible even when subsequent polishing helps.
    before_polish = best.time_log2
    if not stats["budget_exhausted"] and shape_winners:
        winner_shape = tuple(best.parameters[key] for key in ("ell", "p", "d"))
        keys = capped_shapes | ({winner_shape} if winner_shape in shape_winners else set())
        for seed in sorted((shape_winners[key] for key in keys), key=lambda c: c.time_log2)[:4]:
            refine_shape(seed, 1500, polish=True)
            if stats["budget_exhausted"]:
                break
    stats.update(candidate_points=len(cache), peak_cached_points=len(cache),
                 refined_shapes=len(refined_shapes),
                 pre_polish_time_log2=before_polish,
                 polish_improvement_log2=before_polish - best.time_log2,
                 boundary_categories=sorted(categories), refined_time_log2=best.time_log2,
                 improvement_log2=baseline.time_log2 - best.time_log2)
    return best, stats
