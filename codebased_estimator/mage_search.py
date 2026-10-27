"""Deterministic, bounded search for CE-priced MAGE-Stern trees.

This is a multistart heuristic, not a global optimizer.  Every returned point
is replayed by the fixed-point cost kernel.  An optimized one-level tree is
retained throughout.  CE Stern uses a different M4RI construction and competes
separately through the normal report comparison when requested.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from functools import lru_cache
from math import comb, floor, isfinite, log2

from .mage_costs import MageCost, evaluate_parameters
from .mage_targets import optimal_target_batch


SEARCH_VERSION = "ce-mage-deterministic-multistart-v2"
POINT_BUDGET = 3600
INITIAL_P_LIMIT = 12
REFINED_P_LIMIT = 16
BRANCH_LIMIT = 65536
_PAPER_BLOCKS = (13978, 1247, 568, 399, 385, 298, 218, 203, 188, 184)
_PAPER_REPETITIONS = (1, 94, 7, 3, 3, 3, 2, 2, 2, 2, 1)


def _target_batch_coefficients(n, k, ell, p, delta, blocks, repetitions):
    """Exact A, B, D in T(u)=n*D+D*u+(A+B*u)/(1-(1-S)**u)."""
    nodes, weighted_blocks = 1, 0
    for block, repeat in zip(blocks, repetitions):
        nodes *= repeat
        weighted_blocks += nodes * block
    leaves = nodes * repetitions[-1]
    left, right = comb(k//2, p), comb(k-k//2, p-delta)
    denominator = 1 << ell
    shared = n * (k * weighted_blocks + leaves * left)
    per_target = Fraction(n * leaves * ((right+k)*denominator+left*right), denominator)
    return shared, per_target, (n-k)**2


def _partition(total, weights):
    """Largest-remainder integer partition with strictly positive blocks."""
    if total < len(weights):
        return None
    scale = sum(weights)
    ideal = [total*weight/scale for weight in weights]
    result = [max(1, floor(value)) for value in ideal]
    ordering = sorted(range(len(weights)), key=lambda i: (-(ideal[i]-floor(ideal[i])), i))
    if sum(result) <= total:
        for index in ordering[:total-sum(result)]:
            result[index] += 1
    else:
        for index in sorted(range(len(weights)), key=lambda i: (-result[i], i)):
            remove = min(result[index]-1, sum(result)-total)
            result[index] -= remove
            if sum(result) == total:
                break
    return tuple(result)


def _tree_seeds(n, k, w):
    yield "one_level", (k,), (1, 1)
    for depth in (2, 4, 6, 10):
        if depth > k:
            continue
        # Front-loaded and geometrically decreasing, independent of any
        # cryptosystem.  Branches approximately compensate zero-error loss.
        weights = [0.78] + [0.22*0.65**i for i in range(depth-1)]
        weights[0] = sum(weights[1:])*0.78/0.22
        blocks = _partition(k, weights)
        previous, repetitions = blocks[0], [1]
        for block in blocks[1:]:
            exponent = max(0.0, w*block/(n-previous)*log2(2.718281828459045)-1)
            repetitions.append(min(BRANCH_LIMIT, max(1, round(2.0**min(16, exponent)))))
            previous += block
        yield f"geometric_{depth}", blocks, tuple(repetitions+[1])
    if k >= 10:
        # Published HQC-I shape, scaled to any k, is an additional seed only.
        # Its published time or memory figures never enter the objective.
        yield "scaled_paper_example", _partition(k, _PAPER_BLOCKS), _PAPER_REPETITIONS
    if k >= 4:
        yield "balanced_4", _partition(k, (1, 1, 1, 1)), (1, 2, 2, 2, 1)


class _Search:
    def __init__(self, n, k, w, targets, bound, codewords=None, block_profile=None):
        self.n, self.k, self.w = n, k, w
        self.targets, self.bound = targets, bound
        self.codewords = codewords
        self.block_profile = block_profile
        self.cache, self.batch_caps = {}, {}
        self.best = None
        self.cache_hits = 0
        self.exhausted = False
        self.refined_starts = 0
        self.refinement_passes = 0
        self.ell_caps = set()

    def raw(self, ell, p, delta, blocks, repetitions, targets):
        key = (ell, p, delta, tuple(blocks), tuple(repetitions), targets)
        if key in self.cache:
            self.cache_hits += 1
            return self.cache[key]
        if len(self.cache) >= POINT_BUDGET:
            self.exhausted = True
            return None
        result = evaluate_parameters(
            self.n, self.k, self.w, ell=ell, p=p, delta=delta,
            blocks=blocks, repetitions=repetitions, targets=targets,
            memory_bound_log2_bits=self.bound,
            codewords=self.codewords,
            block_profile=self.block_profile,
        )
        self.cache[key] = result
        if result is not None and (self.best is None
                or (result.time_log2, result.parameters["targets_used"])
                < (self.best.time_log2, self.best.parameters["targets_used"])):
            self.best = result
        return result

    def feasible_shape(self, p, delta):
        return (1 <= p <= min(REFINED_P_LIMIT, self.k//2, self.w)
                and 0 <= delta <= p and 2*p-delta <= self.w)

    def batch_cap(self, p, delta):
        key = (p, delta)
        if key in self.batch_caps:
            return self.batch_caps[key]
        if self.bound is None:
            self.batch_caps[key] = self.targets
            return self.targets
        # Memory is independent of ell, the partition, and the branch factors.
        def feasible(targets):
            return self.raw(0, p, delta, (self.k,), (1, 1), targets) is not None
        if feasible(self.targets):
            cap = self.targets
        elif not feasible(1):
            cap = 0
        else:
            lo, hi = 1, self.targets
            while lo < hi and not self.exhausted:
                mid = (lo+hi+1)//2
                if feasible(mid):
                    lo = mid
                else:
                    hi = mid-1
            cap = lo
        self.batch_caps[key] = cap
        return cap

    def at(self, ell, p, delta, blocks, repetitions):
        if not self.feasible_shape(p, delta):
            return None
        maximum = self.batch_cap(p, delta)
        if not maximum:
            return None
        result = self.raw(ell, p, delta, blocks, repetitions, maximum)
        if result is None:
            return None
        if self.codewords is not None:
            # One zero syndrome is processed.  All acceptable codewords are
            # free alternatives in that same search, not a syndrome batch.
            return result
        details = result.details
        probability = details["log2_single_target_success_probability"]
        # For fixed tree parameters the exact independent-union objective is
        # strictly convex.  Binary-search the sign of consecutive integer cost
        # differences; exact cost coefficients avoid cancellation in rounded
        # total costs.  These scalar comparisons do not consume tree points.
        shared, per_target, conversion = _target_batch_coefficients(
            self.n, self.k, ell, p, delta, blocks, repetitions)
        targets = optimal_target_batch(probability, shared, per_target, conversion, maximum)
        candidate = self.raw(ell, p, delta, blocks, repetitions, targets)
        return candidate if candidate is not None else result

    def ell_limit(self, p, delta):
        feasible = self.n-self.k-self.w+2*p-delta
        left = log2(comb(self.k//2, p))
        right = log2(comb(self.k-self.k//2, p-delta))
        # Bounded domain, not a claim that larger collision windows are
        # impossible.  The bound is reported along with the other truncations.
        limit = min(feasible, 512, max(32, int(left+right+log2(self.targets)+16)))
        self.ell_caps.add(limit)
        return limit

    def tune_ell(self, p, delta, blocks, repetitions, center=None):
        if not self.feasible_shape(p, delta):
            return None
        limit = self.ell_limit(p, delta)
        candidates = {0, limit, limit//4, limit//2, 3*limit//4}
        if center is not None:
            candidates.add(max(0, min(limit, center)))
        best = None
        for ell in sorted(candidates):
            point = self.at(ell, p, delta, blocks, repetitions)
            if point is not None and (best is None or point.time_log2 < best.time_log2):
                best = point
        if best is None:
            return None
        step = 1 << max(0, (max(1, limit//4)).bit_length()-1)
        while step:
            for _ in range(2):
                previous = best
                ell = best.parameters["ell"]
                for candidate in sorted({max(0, ell-step), min(limit, ell+step)}):
                    point = self.at(candidate, p, delta, blocks, repetitions)
                    if point is not None and point.time_log2 < best.time_log2:
                        best = point
                if best is previous:
                    break
            step //= 2
        return best

    def deltas(self, p):
        # Include the usual symmetric/one-step DOOM cases and a balancing
        # estimate for unusually large target batches.  Descent adds neighbors.
        spacing = max(1.0, log2(max(2.0, self.k/(2*p))))
        balance = min(p, round(log2(self.targets)/spacing))
        values = {0, 1, balance, min(p, balance+1), max(0, 2*p-self.w)}
        return sorted(delta for delta in values if self.feasible_shape(p, delta))

    def refine(self, seed, allowance=620):
        self.refined_starts += 1
        end = min(POINT_BUDGET, len(self.cache)+allowance)
        current = seed
        for divisor, branch_step in ((32, 1.0), (128, 0.5), (512, 0.25), (0, 0.125)):
            block_step = max(1, self.k//divisor) if divisor else 1
            for _ in range(2):
                self.refinement_passes += 1
                original = current
                parameters = current.parameters
                ell, p, delta = (parameters[key] for key in ("ell", "p", "delta"))
                blocks = tuple(parameters["blocks"])
                repeats = tuple(parameters["repetitions"])

                def query(e=ell, a=p, d=delta, b=blocks, r=repeats):
                    nonlocal current
                    if len(self.cache) >= end:
                        return
                    point = self.at(e, a, d, b, r)
                    if point is not None and point.time_log2 < current.time_log2:
                        current = point

                for step in sorted({1, max(1, round(branch_step*8))}):
                    for direction in (-1, 1):
                        query(e=max(0, min(self.ell_limit(p, delta), ell+direction*step)))
                for direction in (-1, 1):
                    query(a=p+direction)
                    query(d=delta+direction)
                    query(a=p+direction, d=delta+direction)
                # Jointly move a partition boundary and adjust the two
                # neighboring branch factors to preserve approximate mean
                # offspring counts.  Also test the uncoupled boundary move.
                for index in range(len(blocks)-1):
                    for direction in (-1, 1):
                        change = direction*min(block_step,
                                               blocks[index+1]-1 if direction > 0 else blocks[index]-1)
                        if not change:
                            continue
                        moved = list(blocks)
                        moved[index] += change
                        moved[index+1] -= change
                        query(b=tuple(moved))
                        coupled = list(repeats)
                        previous = sum(blocks[:index])
                        exponent = max(-8.0, min(8.0, self.w*change/(self.n-previous)*log2(2.718281828459045)))
                        if index:
                            coupled[index] = min(BRANCH_LIMIT, max(1, round(repeats[index]*2.0**exponent)))
                        coupled[index+1] = min(BRANCH_LIMIT, max(1, round(repeats[index+1]*2.0**(-exponent))))
                        query(b=tuple(moved), r=tuple(coupled))
                # r_1 is fixed at one; it is absorbed in independent retries.
                for index in range(1, len(repeats)):
                    values = {max(1, repeats[index]-1), min(BRANCH_LIMIT, repeats[index]+1)}
                    values.update(min(BRANCH_LIMIT, max(1, round(repeats[index]*2.0**direction)))
                                  for direction in (-branch_step, branch_step))
                    for value in sorted(values):
                        if value != repeats[index]:
                            varied = list(repeats)
                            varied[index] = value
                            query(r=tuple(varied))
                if current is original or len(self.cache) >= end:
                    break
            if len(self.cache) >= end:
                break
        return current


@lru_cache(maxsize=128)
def _optimize(n, k, w, targets, memory_bound_log2_bits, codewords=None, block_profile=None):
    search = _Search(n, k, w, targets, memory_bound_log2_bits, codewords, block_profile)
    limit = min(INITIAL_P_LIMIT, k//2, w)
    initial_ps = sorted(set(range(1, min(8, limit)+1)) | {value for value in (10, 12) if value <= limit})
    one_level = []
    for p in initial_ps:
        for delta in search.deltas(p):
            point = search.tune_ell(p, delta, (k,), (1, 1))
            if point is not None:
                one_level.append(point)
    if not one_level:
        return None
    one_level.sort(key=lambda value: value.time_log2)
    baseline = one_level[0]
    # Include the best one-level shapes and the smaller lists that can become
    # favorable once Gaussian work is amortized across a tree.
    selected = one_level[:4]
    for p in range(1, min(4, limit)+1):
        point = next((value for value in one_level if value.parameters["p"] == p), None)
        if point is not None and point not in selected:
            selected.append(point)
    seeded, origins, used_depths = [baseline], [], set()
    for origin, blocks, repetitions in _tree_seeds(n, k, w):
        origins.append(origin)
        used_depths.add(len(blocks))
        if origin == "one_level":
            continue
        for point in selected:
            parameters = point.parameters
            candidate = search.tune_ell(parameters["p"], parameters["delta"], blocks,
                                        repetitions, parameters["ell"])
            if candidate is not None:
                seeded.append(candidate)
        # Reserve at least half of the budget for joint tree refinement.
        if len(search.cache) >= POINT_BUDGET//2:
            break
    seeded.sort(key=lambda value: value.time_log2)
    starts = []
    for candidate in seeded:
        signature = (len(candidate.parameters["blocks"]), candidate.parameters["p"],
                     candidate.parameters["delta"])
        if signature not in [item[0] for item in starts]:
            starts.append((signature, candidate))
        if len(starts) == 3:
            break
    for _, candidate in starts:
        search.refine(candidate)
    result = search.best
    # Fixed-point replay is deliberately outside the search budget: it checks
    # the value ultimately exposed by the public optimizer.
    replay = evaluate_parameters(n, k, w, targets=result.parameters["targets_used"],
                                 memory_bound_log2_bits=memory_bound_log2_bits,
                                 **result.parameters)
    if replay is None:
        raise ArithmeticError("MAGE-Stern search winner failed fixed-point replay")
    statistics = {
        "version": SEARCH_VERSION,
        "method": "deterministic_multistart_joint_partition_branch_descent",
        "global_optimum": False,
        "point_budget": POINT_BUDGET,
        "candidate_points": len(search.cache),
        "cache_hits": search.cache_hits,
        "budget_exhausted": search.exhausted,
        "stopping": "four block/branch step scales, at most two passes per scale; soft 620-point allowance per start (the current batch evaluation can finish across it); hard global point budget",
        "refined_starts": search.refined_starts,
        "refinement_passes": search.refinement_passes,
        "initial_p_values": initial_ps,
        "refined_p_domain": [1, min(REFINED_P_LIMIT, k//2, w)],
        "delta_domain": "initial 0/1/target-balance seeds and integer neighbors; 0 <= delta <= p",
        "ell_domain": "0..min(n-k-w+2p-delta, 512); initial window tuning additionally caps at max(32, floor(log2(L_left L_right targets)+16)); joint refinement can retain a window when p/delta changes",
        "maximum_ell_considered": max(search.ell_caps),
        "depth_seeds": sorted(used_depths),
        "planned_depth_seeds": sorted({len(blocks) for _, blocks, _ in _tree_seeds(n, k, w)}),
        "tree_seed_origins": origins,
        "branch_domain": [1, BRANCH_LIMIT],
        "first_branch_fixed": 1,
        "target_batch_search": "independent-union convex integer differences; binary search under memory cap, adaptive precision near ties; subject to the tree point budget",
        "available_targets": targets,
        "one_level_baseline_retained": True,
        "one_level_baseline_time_log2": baseline.time_log2,
        "one_level_baseline_parameters": baseline.parameters,
        "fixed_point_replayed": True,
        "scaled_paper_seed_is_only_a_start": True,
        "existing_ce_stern_is_a_separate_candidate": True,
    }
    if codewords is not None:
        statistics.update({
            "codeword_count": codewords,
            "target_batch_search": "not applicable: one zero syndrome, all codewords enter the outer probability",
        })
    if block_profile is not None:
        statistics["unbalanced"] = {
            "model": "block-profile-first-transition-tree-v1",
            "allocation_search": "deterministic integer quota seeds and three-scale pairwise descent; exhaustive for two blocks when one length is at most 128",
            "global_optimum": False,
            "objective": "whole-tree survival, not an added one-level exponent",
            "scope": "first pivot transition only; remaining coordinates are uniformly shuffled",
            "uniform_first_transition_retained": True,
        }
    return replace(replay, search=statistics)


def optimize(n, k, w, *, algorithm="MAGE-Stern", targets=1,
             memory_bound_log2_bits=None, codewords=None, block_profile=None) -> MageCost | None:
    """Return a replayable heuristic tree for binary decoding or QCCF proxies.

    ``targets`` counts available syndromes, each with one accepted solution.
    Invalid or memory-infeasible instances return ``None``.  The public
    classical adapter handles unsupported problem families.  CE's original
    Stern algorithm competes separately in the normal report comparison when
    requested.  Cached results are copied before being returned.

    Positive ``codewords`` selects the one-syndrome QCCF proxy.  It requires
    ``targets=1`` and enters the objective before tree parameter optimization;
    its codeword count is never optimized as a materialized syndrome batch.
    """
    if algorithm != "MAGE-Stern":
        raise ValueError(f"Unknown MAGE search algorithm: {algorithm}")
    if (any(type(value) is not int for value in (n, k, w, targets))
            or not (0 < k < n and 1 <= w <= n-k and targets >= 1)):
        return None
    if codewords is not None and (type(codewords) is not int or codewords < 1 or targets != 1):
        return None
    if block_profile is not None:
        from .unbalanced import BlockProfile

        if isinstance(block_profile, dict):
            block_profile = BlockProfile(**block_profile)
        block_profile.validate(n, w)
    bound = memory_bound_log2_bits
    if bound is not None and (isinstance(bound, bool) or not isinstance(bound, (int, float))
                              or not isfinite(bound) or bound < 0):
        return None
    return deepcopy(_optimize(n, k, w, targets, bound, codewords, block_profile))
