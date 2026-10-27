"""Target-aware binary ISD costs, using CE's vector/bit cost convention.

Sendrier (2011), Section 5, gives a shared list and a syndrome-dependent
list, with success proxy min(1, M * P).  Esser--May--Zweydinger (2022),
Section 5.1, extends the fourth BJMM leaf instead.  This module instantiates
those constructions with finite binomial counts and reoptimizes parameters.
The polynomial prices below are explicit modeling choices, not benchmarks.

Lists use CE's integer sizes and hash-merge work with per-target rounding.
A vector operation
costs n bits, as in CE 2.1.1.  The first syndrome is included in CE's Gaussian
budget; each additional syndrome costs (n-k)^2 bit operations for its dense
linear transform and (n-k) bits of storage.  BJMM streams its final merge.
Targets
are assumed usable under the random-label/rare-event DOOM approximation;
their independence or QC orbit size is not inferred from n or k.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import product
from math import comb, floor, inf, isfinite, log2

from .assumptions import BLOCK_OUTER, BLOCK_SOLUTIONS, CLASSICAL_COST, SINGLE_SYNDROME
from .doom_bjmm import bjmm_terms
from .models import AttackInstance, Estimate, Options


COST_MODEL = "ce-doom-finite-v2"
ALGORITHMS = ("Prange", "Stern", "Dumer", "BJMM")
REFERENCES = (
    "https://eprint.iacr.org/2011/367 (Sendrier, Section 5, Eq. 8)",
    "https://eprint.iacr.org/2021/1634 (Esser--May--Zweydinger, Sections 2 and 5.1)",
)


def _doom_assumptions(*, profile=False):
    assumptions = (
        "DOOM uses a linear-union proxy for success probability; syndrome correlations are not modeled.",
        CLASSICAL_COST,
    )
    if profile:
        assumptions += (
            BLOCK_OUTER,
            BLOCK_SOLUTIONS,
            "Only syndromes preserving block weights share a coordinate allocation.",
        )
    return assumptions


@dataclass(frozen=True)
class DoomCost:
    time_log2: float
    memory_log2: float
    parameters: dict
    details: dict


def _logadd(*terms):
    top = max(terms, default=-inf)
    return top if top == -inf else top + log2(sum(2.0 ** (x - top) for x in terms))


@lru_cache(maxsize=32768)
def _logcomb(n, w):
    return -inf if not 0 <= w <= n else log2(comb(n, min(w, n - w)))


def _simple_terms(n, k, w, name, parameters):
    if name == "Prange":
        if parameters:
            return None
        return dict(parameters={}, log2_probability=_logcomb(n-k, w)-_logcomb(n, w),
                    log2_work_shared=-inf, log2_work_per_target=-inf,
                    log2_memory_shared=-inf, log2_memory_per_target=-inf, details={})
    if set(parameters) != {"l", "p_left", "p_right"}:
        return None
    ell, pl, pr = (parameters[key] for key in ("l", "p_left", "p_right"))
    if any(type(v) is not int for v in (ell, pl, pr)) or not 0 <= ell <= n-k:
        return None
    length = k if name == "Stern" else k+ell
    # CE uses two floor-sized halves; an odd remaining coordinate is zero.
    left = right = length//2
    if not (0 <= pl <= left and 0 <= pr <= right and 0 <= w-pl-pr <= n-k-ell):
        return None
    a, b = comb(left, pl), comb(right, pr)
    matches = a*b//(1 << ell)
    shared, target = (0, 1) if a == b == 1 else (a, b+matches)
    tail, t = (n-k if name == "Stern" else n-k-ell), w-pl-pr
    numerator, denominator = comb(tail, t)*a*b, comb(n, w)
    terms = dict(
        parameters=parameters,
        log2_probability=min(0.0, log2(numerator)-log2(denominator)),
        log2_work_shared=log2(shared) if shared else -inf,
        log2_work_per_target=log2(target),
        log2_memory_shared=log2(a), log2_memory_per_target=log2(b),
        details={"half_lengths": [left, right], "half_weights": [pl, pr],
                 "unused_information_coordinates": length-left-right,
                 "tail_weight": t, "outer_tail_size": tail,
                 "log2_base_lists": [log2(a), log2(b)],
                 "log2_outputs_per_target": log2(matches) if matches else None,
                 "collision_rounding": "per target, floor(A*B/2^l)"},
    )
    if name == "Stern":
        terms.update(raw_projections=comb(n-k, t)//comb(n-k-ell, t),
                     residual_numerator=numerator, residual_denominator=denominator)
    return terms


def _terms(n, k, w, name, parameters, block_profile=None):
    if name == "BJMM":
        if set(parameters) != {"l", "p", "p1", "weight_deficit"}:
            return None
        terms = bjmm_terms(n, k, w, ell=parameters["l"], p=parameters["p"],
                           p1=parameters["p1"], weight_deficit=parameters["weight_deficit"])
    else:
        terms = _simple_terms(n, k, w, name, parameters)
    if terms is not None and block_profile is not None:
        from .unbalanced import optimize_outer

        tail = n-k if name == "Stern" else n-k-parameters.get("l", 0)
        weight = (0 if name == "Prange" else
                  2*parameters["p"]-parameters["weight_deficit"] if name == "BJMM" else
                  parameters["p_left"]+parameters["p_right"])
        outer = optimize_outer(block_profile, tail, weight)
        terms = {**terms,
                 "log2_probability": min(0.0, terms["log2_probability"]+outer.gain),
                 "details": {**terms["details"], "unbalanced": {
                     **outer.to_dict(), "applied": True,
                     "tail_size": tail, "information_weight": weight,
                     "model": "block_outer_probability",
                     "inner_costs": "unchanged; uniformly shuffle selected information and tail regions",
                 }}}
    return terms


@lru_cache(maxsize=256)
def _matrix_profiles(n, k):
    """All nondominated CE Gaussian block widths, with exact integer pruning."""
    from cryptographic_estimators.SDEstimator.sd_helper import (
        _gaussian_elimination_complexity, _mem_matrix,
    )
    profiles, best = [], None
    for r in range(n-k):
        # G(r) >= 2^r; larger widths also use strictly more matrix memory.
        if best is not None and (1 << r) >= best:
            break
        work = _gaussian_elimination_complexity(n, k, r)
        if best is None or work < best:
            profiles.append((r, work, _mem_matrix(n, k, r)))
            best = work
    return tuple(profiles)


def _affine_costs(n, k, terms, matrix, projections=1, targets=1):
    _, gaussian, storage = matrix
    m = n-k
    # Subtract the first syndrome because CE's baseline already includes it.
    # All matrix costs dominate that single dense transform.
    list_scale = log2(n)+log2(projections)
    work_branches = terms.get("log2_work_branches", (
        (terms["log2_work_shared"], terms["log2_work_per_target"]),
    ))
    work_shared, work_target = min(work_branches,
                                  key=lambda pair: _logadd(pair[0], log2(targets)+pair[1]))
    shared_work = _logadd(log2(n*gaussian-m*m), list_scale+work_shared)
    target_work = _logadd(log2(m*m), list_scale+work_target)
    shared_memory = _logadd(log2(n*storage-m), log2(n)+terms["log2_memory_shared"])
    target_memory = _logadd(log2(m), log2(n)+terms["log2_memory_per_target"])
    return shared_work, target_work, shared_memory, target_memory


@lru_cache(maxsize=256)
def _integral_solutions(solutions):
    """CE uses floor(2**s) inside Stern and real s in the outer probability."""
    if float(solutions).is_integer():
        return 1 << int(solutions)
    integer = floor(solutions)
    if integer <= 1000:
        return int(2**solutions)
    return int(2**(solutions-integer+52)) << (integer-52)


def _projections(terms, targets, solutions):
    if "raw_projections" not in terms:
        return 1, 0
    # Deliberately use the generic event even for a block profile, matching
    # the existing CE hook: unbalanced changes only the outer repetition.
    residual = (targets*_integral_solutions(solutions)*terms["residual_numerator"]
                // terms["residual_denominator"])
    return max(1, terms["raw_projections"]//max(1, residual)), residual


def _memory_branches(n, k, terms, matrix):
    branches = terms.get("log2_memory_branches", (
        (terms["log2_memory_shared"], terms["log2_memory_per_target"]),
    ))
    return tuple((_logadd(log2(n*matrix[2]-(n-k)), log2(n)+shared),
                  _logadd(log2(n-k), log2(n)+per_target))
                 for shared, per_target in branches)


def _point(n, k, terms, matrix, targets, solutions, bound):
    projections, residual = _projections(terms, targets, solutions)
    shared, per_target, _, _ = _affine_costs(n, k, terms, matrix, projections, targets)
    log_targets = log2(targets)
    mem_shared, mem_target = max(_memory_branches(n, k, terms, matrix),
                                key=lambda pair: _logadd(pair[0], log_targets+pair[1]))
    memory = _logadd(mem_shared, log_targets+mem_target)
    if bound is not None and memory > bound:
        return None
    log_probability = min(0.0, terms["log2_probability"]+solutions+log_targets)
    iteration = _logadd(shared, log_targets+per_target)
    details = {
        **terms["details"],
        "log2_single_solution_probability": terms["log2_probability"],
        "log2_success_probability": log_probability,
        "log2_permutations": -log_probability,
        "log2_iteration_bit_cost": iteration,
        "log2_shared_bit_cost": shared,
        "log2_per_target_bit_cost": per_target,
        "log2_shared_memory_bits": mem_shared,
        "log2_per_target_memory_bits": mem_target,
        "log2_active_targets": log_targets,
        "log2_gaussian_bit_cost": log2(n*matrix[1]),
        "log2_extra_syndrome_bit_cost": None if targets == 1 else log2(targets-1)+2*log2(n-k),
        "effective_log2_solutions": solutions,
        "memory_model": terms["details"].get("memory_model", "materialized base lists"),
    }
    if "raw_projections" in terms:
        details.update(raw_projections=terms["raw_projections"], projections=projections,
                       residual_solutions=residual,
                       residual_probability_model="generic event; unbalanced changes outer probability only")
    if "log2_base_lists" in details:
        expanded = list(details["log2_base_lists"])
        expanded[-1] += log_targets
        details["log2_expanded_base_lists"] = expanded
        outputs = details["log2_outputs_per_target"]
        details["log2_total_outputs"] = None if outputs is None else outputs+log_targets
    if "log2_intermediate_lists" in details:
        left, right = details["log2_intermediate_lists"]
        details["log2_expanded_intermediate_lists"] = [left, right+log_targets]
    return DoomCost(iteration-log_probability, memory,
                    {**terms["parameters"], "r": matrix[0], "targets_used": targets}, details)


def evaluate_parameters(n, k, w, name, *, targets, log2_solutions=0,
                        memory_bound_log2_bits=None, block_profile=None, **parameters):
    """Replay a fixed DOOM point; invalid or memory-infeasible points return None.

    Use ``l,p_left,p_right`` for Stern/Dumer and ``l,p,p1,weight_deficit``
    for depth-two BJMM.  ``r`` optionally fixes the CE Gaussian block width;
    otherwise it is optimized.  Result parameter dictionaries can be replayed
    directly: ``targets_used``, ``depth`` and ``l1`` are checked if supplied.
    Costs are in bits; ``targets`` is the active batch, not a log solution count.
    """
    if name not in ALGORITHMS:
        raise ValueError(f"Unknown explicit DOOM algorithm: {name}")
    if (any(type(v) is not int for v in (n, k, w, targets))
            or not (0 < k < n and 1 <= w <= n-k and targets >= 1)):
        return None
    if block_profile is not None:
        block_profile.validate(n, w)
    if (isinstance(log2_solutions, bool) or not isinstance(log2_solutions, (int, float))
            or not isfinite(log2_solutions) or log2_solutions < 0):
        return None
    bound = memory_bound_log2_bits
    if bound is not None and (isinstance(bound, bool) or not isinstance(bound, (int, float))
                              or not isfinite(bound) or bound < 0):
        return None
    parameters = dict(parameters)
    used = parameters.pop("targets_used", targets)
    r = parameters.pop("r", None)
    depth, l1 = parameters.pop("depth", None), parameters.pop("l1", None)
    if type(used) is not int or used != targets:
        return None
    if r is not None and (type(r) is not int or not 0 <= r < n-k):
        return None
    if any(value is not None and type(value) is not int for value in (depth, l1)):
        return None
    terms = _terms(n, k, w, name, parameters, block_profile)
    if terms is None or (depth is not None and depth != terms["parameters"].get("depth")):
        return None
    if l1 is not None and l1 != terms["parameters"].get("l1"):
        return None
    matrices = _matrix_profiles(n, k)
    if r is not None:
        from cryptographic_estimators.SDEstimator.sd_helper import (
            _gaussian_elimination_complexity, _mem_matrix,
        )
        matrices = ((r, _gaussian_elimination_complexity(n, k, r), _mem_matrix(n, k, r)),)
    points = [_point(n, k, terms, matrix, targets, log2_solutions, bound) for matrix in matrices]
    return min((point for point in points if point is not None),
               key=lambda point: point.time_log2, default=None)


def _batch_candidates(available, log_probability, mem_shared, mem_target, bound):
    """Optimize the integer batch for an affine cost divided by min(1,t*P).

    Below success saturation the objective decreases, above it increases.
    Only the two adjacent integers (and feasibility endpoints) are needed.
    """
    maximum = available
    if bound is not None:
        if _logadd(mem_shared, mem_target) > bound:
            return ()
        if _logadd(mem_shared, log2(maximum)+mem_target) > bound:
            lo, hi = 1, maximum
            while lo < hi:
                mid = (lo+hi+1)//2
                if _logadd(mem_shared, log2(mid)+mem_target) <= bound:
                    lo = mid
                else:
                    hi = mid-1
            maximum = lo
    if log_probability >= 0:
        return (1,)
    if -log_probability >= log2(maximum):
        return (maximum,)
    exponent = -log_probability
    integer = floor(exponent)
    # Avoid overflow when supplied target counts exceed the float range.
    scale = min(integer, 52)
    lower = int(2.0**(exponent-integer+scale)) << (integer-scale)
    return tuple(sorted({1, min(maximum, max(1, lower)), min(maximum, lower+1)}))


def _optimal_batches(n, k, terms, matrix, available, solutions, bound):
    """Exact integer batch candidates for affine work on Stern's J intervals.

    Memory is monotone, including BJMM's peak of two streaming phases. On
    each constant-projection interval the work is the minimum of positive
    affine costs (BJMM may scan singleton leaves or share a hash table).
    Each cost/u decreases before success saturation and each cost increases
    afterwards, as does their minimum in the respective direction. Inspect
    interval ends and adjacent saturation integers; no merge crossover is
    needed. Quotient jumps skip batches with the same projection count.
    """
    branches = _memory_branches(n, k, terms, matrix)

    def fits(u):
        return bound is None or all(_logadd(a, log2(u)+b) <= bound for a, b in branches)

    if not fits(1):
        return ()
    maximum = available
    if not fits(maximum):
        lo, hi = 1, maximum
        while lo < hi:
            mid = (lo+hi+1)//2
            if fits(mid):
                lo = mid
            else:
                hi = mid-1
        maximum = lo
    saturation = _batch_candidates(maximum, terms["log2_probability"]+solutions,
                                    -inf, -inf, None)
    first, _ = _projections(terms, 1, solutions)
    last, _ = _projections(terms, maximum, solutions)
    if first == last:
        return saturation
    numerator = terms["residual_numerator"]*_integral_solutions(solutions)
    denominator = terms["residual_denominator"]
    raw = terms["raw_projections"]
    candidates, start = set(), 1
    while start <= maximum:
        projections, _ = _projections(terms, start, solutions)
        if projections == 1:
            end = maximum
        else:
            # Next change occurs at floor(u*N/D) >= floor(J0/J)+1.
            next_residual = raw//projections+1
            end = min(maximum, (next_residual*denominator-1)//numerator)
        candidates.update((start, end))
        candidates.update(min(end, max(start, u)) for u in saturation)
        start = end+1
    return tuple(sorted(candidates))


def _optimize(n, k, w, name, available, solutions, bound, baseline, block_profile=None):
    matrices = _matrix_profiles(n, k)
    keys = ("l", "p", "p1", "weight_deficit") if name == "BJMM" else ("l", "p_left", "p_right")
    if name == "Prange":
        keys = ()
    cache, best = {}, None
    budget = 16000

    def visit(values):
        nonlocal best
        values = tuple(values)
        if values in cache:
            return cache[values]
        if len(cache) >= budget:
            return None
        parameters = dict(zip(keys, values))
        terms = _terms(n, k, w, name, parameters)
        point = None
        if terms is not None and block_profile is not None:
            tail = n-k if name == "Stern" else n-k-parameters.get("l", 0)
            weight = (0 if name == "Prange" else
                      2*parameters["p"]-parameters["weight_deficit"] if name == "BJMM" else
                      parameters["p_left"]+parameters["p_right"])
            aggregate = _logcomb(tail, w-weight)+_logcomb(n-tail, weight)-_logcomb(n, w)
            optimistic = {**terms, "log2_probability": min(0.0, terms["log2_probability"]-aggregate)}
            # Any block allocation has aggregate-event probability <= 1.
            # Optimize that optimistic conditional split over matrix/batch
            # choices before paying for block-distribution convolutions.
            competitive = best is None
            if not competitive:
                for matrix in matrices:
                    batches = _optimal_batches(n, k, optimistic, matrix, available, solutions, bound)
                    for batch in batches:
                        lower = _point(n, k, optimistic, matrix, batch, solutions, bound)
                        if lower is not None and lower.time_log2 < best.time_log2:
                            competitive = True
                            break
                    if competitive:
                        break
            if not competitive:
                cache[values] = None
                return None
            terms = _terms(n, k, w, name, parameters, block_profile)
        if terms is not None:
            for matrix in matrices:
                batches = _optimal_batches(n, k, terms, matrix, available, solutions, bound)
                for batch in batches:
                    candidate = _point(n, k, terms, matrix, batch, solutions, bound)
                    if candidate is not None and (point is None or candidate.time_log2 < point.time_log2):
                        point = candidate
            if point is not None and (best is None or point.time_log2 < best.time_log2):
                best = point
        cache[values] = point
        return point

    exhaustive = name == "Prange" or (n <= 48 and w <= 8)
    if name == "Prange":
        visit(())
    elif exhaustive:
        if name == "BJMM":
            choices = ((ell, p, p1, deficit)
                       for ell in range(n-k+1) for p in range(0, 2*w//3+1, 2)
                       for p1 in range(p//2, (k+ell)//2+1)
                       for deficit in range(min(p//2, p1)+1))
        else:
            choices = ((ell, pl, pr) for ell in range(n-k+1)
                       for pl in range(w+1) for pr in range(w-pl+1))
        for values in choices:
            visit(values)
            if len(cache) >= budget:
                exhaustive = False
                break
    else:
        base = baseline.parameters
        base_l, base_p = int(base.get("l", 0)), int(base.get("p", 0))
        if name == "BJMM":
            # The CE parent may select depth three. Its p1 is not the depth-
            # two optimizer's p1; seed the actual child too, retaining the
            # previous starts and any profiled child's independent optimum.
            seeds = [base] + [baseline.metadata[key] for key in (
                "ce_depth_two_parameters", "ce_profile_depth_two_parameters",
            ) if key in baseline.metadata]
            seed_weights = {int(seed.get("p", 0)) for seed in seeds}
            seed_lengths = {int(seed.get("l", 0)) for seed in seeds}
            weights = sorted(set(range(0, min(16, 2*w//3)+1, 2))
                             | {p-p%2 for p in seed_weights})
            for p in weights:
                for extra in range(4):
                    p1 = p//2+extra
                    center = max(0, round(2*_logcomb(max(k//2, p1), p1)))
                    for deficit in range(min(p//2, p1)+1):
                        for ell in sorted({0, center, center-4, center+4,
                                           center+int(log2(available))//2} | seed_lengths):
                            visit((ell, p, p1, deficit))
            for seed in seeds:
                p = int(seed.get("p", 0))
                visit((int(seed.get("l", 0)), p-p%2, int(seed.get("p1", p//2)), 0))
        else:
            weights = sorted(set(range(min(16, w)+1)) | {base_p})
            for pl, pr in product(weights, repeat=2):
                if pl+pr > w:
                    continue
                # Matching work balances list generation and Gaussian work.
                a, b = _logcomb(k//2, pl), _logcomb(k//2, pr)
                if not isfinite(a+b):
                    continue
                center = max(0, round(a+b+log2(available)-_logadd(
                    a, b+log2(available), log2(matrices[-1][1]))))
                for ell in sorted({0, base_l, center, center-4, center+4, center+8}):
                    visit((ell, pl, pr))
        # Keep several distinct starts; refine over the full integer domain.
        starts = sorted(((v, p) for v, p in cache.items() if p is not None),
                        key=lambda item: item[1].time_log2)[:8]
        for values, point in starts:
            for step in (16, 8, 4, 2, 1):
                while len(cache) < budget:
                    next_values, next_point = values, point
                    directions = []
                    for axis in range(len(keys)):
                        delta = [0]*len(keys)
                        delta[axis] = step*(2 if name == "BJMM" and axis == 1 else 1)
                        directions.extend((delta, [-v for v in delta]))
                    if name == "BJMM":
                        directions.extend(([0, 2*step, step, 0], [0, -2*step, -step, 0]))
                    for delta in directions:
                        trial = tuple(a+b for a, b in zip(values, delta))
                        candidate = visit(trial)
                        if candidate is not None and candidate.time_log2 < next_point.time_log2:
                            next_values, next_point = trial, candidate
                    if next_values == values:
                        break
                    values, point = next_values, next_point
    search = {"method": "finite enumeration" if exhaustive else "deterministic grid and integer local refinement",
              "evaluated_parameter_points": len(cache), "point_budget": budget,
              "budget_exhausted": len(cache) >= budget, "exhaustive": exhaustive,
              "batch_optimization": "exact affine intervals: memory endpoint, saturation integers, Stern projection quotient jumps",
              "gaussian_optimization": "all nondominated CE block widths",
              "baseline_retained": True, "bjmm_depths": [2] if name == "BJMM" else None,
              "stopping_reason": "point budget" if len(cache) >= budget else
                                 ("domain exhausted" if exhaustive else "integer local optima"),
              "parameter_domain": "valid finite weight splits with 0 <= l <= n-k; see cost evaluator",
              "initial_weight_grid_max": None if exhaustive else 16,
              "local_starts": 0 if exhaustive else 8}
    if name == "BJMM":
        search["ce_depth_two_seed"] = baseline.metadata.get("ce_depth_two_parameters")
        search["ce_profile_depth_two_seed"] = baseline.metadata.get("ce_profile_depth_two_parameters")
    return best, search


def _estimate_profile_doom(name, instance, options, baseline):
    """Compare a shared profile-preserving batch with the full generic orbit.

    Targets with a different block-weight permutation are deliberately not
    assigned the first class's optimized allocation. This is an achievable
    class-selection strategy, not independent free allocations per target.
    """
    from .backend import ClassicalModel

    profile = instance.block_profile
    generic = estimate_doom(name, replace(instance, block_profile=None), options, baseline)
    single = ClassicalModel().estimate_algorithm(
        name, replace(instance, tags=(), targets=1), options,
    )
    n, k, w = (instance.problem.parameters[key] for key in ("n", "k", "w"))
    available = profile.preserving_targets(instance.targets)
    solutions = instance.problem.log2_solutions
    if solutions is None:
        solutions = max(0.0, sum(_logcomb(length, weight) for length, weight in
                                  zip(profile.lengths, profile.weights))-(n-k))
    point = None
    search = {"method": "single-target CE identity", "baseline_retained": True}
    # Preserve the same one-target algorithm family as estimate_doom below.
    # Merely supplying a redundant profile must not add local asymmetric
    # inner candidates that the ordinary CE single-target route never sees.
    if instance.targets > 1:
        seed = baseline
        if name == "BJMM" and "ce_depth_two_parameters" in single.metadata:
            seed = replace(baseline, metadata={
                **baseline.metadata,
                "ce_profile_depth_two_parameters": single.metadata["ce_depth_two_parameters"],
            })
        point, search = _optimize(n, k, w, name, available, solutions,
                                  options.memory_bound_log2_bits, seed, profile)
    candidates = [("generic_full_orbit", generic), ("profile_single_target", single)]
    if point is not None:
        candidates.append(("profile_preserving_batch", replace(
            baseline, status="computed", reason="", time_log2=point.time_log2,
            memory_log2=point.memory_log2, parameters=point.parameters,
            metadata={**baseline.metadata, "cost_breakdown": point.details,
                      "unbalanced": point.details["unbalanced"]},
        )))
    valid = [(strategy, candidate) for strategy, candidate in candidates
             if candidate.status == "computed"]
    strategy, selected = min(valid, key=lambda item: item[1].time_log2) if valid else candidates[0]
    active = (point.parameters["targets_used"] if strategy == "profile_preserving_batch" else
              1 if strategy == "profile_single_target" else
              generic.metadata["doom"]["active_targets"])
    selected_search = (search if strategy == "profile_preserving_batch" else
                       {"method": "single-target block-aware CE optimization",
                        "baseline_retained": True} if strategy == "profile_single_target" else
                       generic.metadata["doom"]["search"])
    unbalanced = {
        **selected.metadata.get("unbalanced", {}),
        "applied": strategy != "generic_full_orbit" and
                   selected.metadata.get("unbalanced", {}).get("applied", False),
        "strategy": strategy,
        "profile_preserving_targets": available,
        "available_targets": instance.targets,
        "target_policy": "one shared allocation for the profile-preserving subgroup; full generic orbit retained",
        "generic_time_log2": generic.time_log2,
        "profile_single_target_time_log2": single.time_log2,
        "profile_batch_time_log2": point.time_log2 if point else None,
        "search": search,
    }
    metadata = {**selected.metadata, "tags": list(instance.tags), "targets": instance.targets,
                "effective_log2_solutions": (generic.metadata.get("effective_log2_solutions")
                                             if strategy == "generic_full_orbit" else solutions),
                "unbalanced": unbalanced,
                "doom": {**generic.metadata["doom"], "strategy": strategy,
                         "active_targets": active,
                         "search": selected_search,
                         "generic_full_orbit_search": generic.metadata["doom"]["search"],
                         "profile_preserving_targets": available,
                         "log2_speedup": (baseline.time_log2-selected.time_log2)
                         if baseline.status == "computed" and selected.status == "computed" else None}}
    if strategy == "profile_preserving_batch":
        metadata["gaussian_elimination_search"] = (
            "all nondominated CE block widths under the DOOM memory budget"
        )
    if strategy == "profile_preserving_batch":
        assumptions = _doom_assumptions(profile=True)
    elif strategy == "profile_single_target":
        assumptions = single.assumptions + (SINGLE_SYNDROME,)
    else:
        assumptions = generic.assumptions
    return replace(selected, metadata=metadata, assumptions=assumptions,
                   references=tuple(dict.fromkeys(selected.references+REFERENCES)))


def estimate_doom(name: str, instance: AttackInstance, options: Options, baseline: Estimate) -> Estimate:
    """Optimize a tagged binary instance, retaining its unchanged CE baseline."""
    if instance.block_profile is not None:
        return _estimate_profile_doom(name, instance, options, baseline)
    problem = instance.problem
    n, k, w = (problem.parameters[key] for key in ("n", "k", "w"))
    solutions = baseline.metadata.get("effective_log2_solutions")
    if solutions is None:
        solutions = problem.log2_solutions
        if solutions is None:
            solutions = max(0.0, _logcomb(n, w)-(n-k))
    point = None
    search = {"method": "single-target CE identity", "baseline_retained": True}
    if instance.targets > 1:
        point, search = _optimize(n, k, w, name, instance.targets, solutions,
                                 options.memory_bound_log2_bits, baseline)
    take_point = point is not None and (baseline.status != "computed"
                                        or point.time_log2 < baseline.time_log2)
    doom = {"model": "parameter_optimized", "cost_model": COST_MODEL,
            "available_targets": instance.targets,
            "active_targets": point.parameters["targets_used"] if take_point else 1,
            "strategy": "explicit_doom" if take_point else "single_target_baseline",
            "search": search,
            "baseline_time_log2": baseline.time_log2,
            "log2_speedup": (baseline.time_log2-point.time_log2 if take_point else 0.0)
                            if baseline.status == "computed" else None}
    metadata = {**baseline.metadata, "tags": list(instance.tags), "targets": instance.targets,
                "effective_log2_solutions": solutions, "doom": doom}
    if not take_point:
        return replace(baseline, metadata=metadata, assumptions=baseline.assumptions + (SINGLE_SYNDROME,),
                       references=tuple(dict.fromkeys(baseline.references+REFERENCES)))
    metadata["cost_breakdown"] = point.details
    metadata["gaussian_elimination_search"] = "all nondominated CE block widths under the DOOM memory budget"
    return replace(baseline, status="computed", time_log2=point.time_log2,
                   memory_log2=point.memory_log2, parameters=point.parameters, reason="",
                   assumptions=_doom_assumptions(), metadata=metadata,
                   references=tuple(dict.fromkeys(baseline.references+REFERENCES)))
