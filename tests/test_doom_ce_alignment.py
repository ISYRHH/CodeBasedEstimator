"""Check the explicit QCSD kernels against independent installed CE costs.

The CE callback is the oracle for fixed parameters. Batch checks enumerate
every feasible target count, so they also cover projection discontinuities
that an affine batch optimizer alone would miss.
"""

from importlib import import_module
from itertools import combinations
from math import comb, isfinite, log2
from types import SimpleNamespace

import pytest

from cryptographic_estimators.SDEstimator.sd_problem import SDProblem
from cryptographic_estimators.SDEstimator.sd_helper import (
    _gaussian_elimination_complexity,
    _mem_matrix,
)

from codebased_estimator.backend import _install_ce_outer_probability
from codebased_estimator.classical_doom import (
    _optimal_batches,
    _point,
    _terms,
    evaluate_parameters,
)
from codebased_estimator.unbalanced import BlockProfile
from codebased_estimator.doom_bjmm import bjmm_terms
from cryptographic_estimators.SDEstimator.SDAlgorithms import BJMM


SIMPLE_NAMES = ("Prange", "Dumer", "Stern")


def corresponding_parameters(n, k, w, name):
    if name == "Prange":
        yield {}, {}
        return
    for p in range(w // 2 + 1):
        for ell in range(n - k + 1):
            half = (k + (ell if name == "Dumer" else 0)) // 2
            if p <= half and w - 2 * p <= n - k - ell:
                yield {"p": p, "l": ell}, {"p_left": p, "p_right": p, "l": ell}


@pytest.mark.parametrize("name", SIMPLE_NAMES)
@pytest.mark.parametrize("problem,solutions,r", [
    ((12, 6, 3), 0, 0), ((21, 11, 4), 2, 2),
    ((31, 16, 7), 4.5, 0), ((100, 50, 10), 33.75, 2),
])
def test_one_target_fixed_parameters_match_ce(name, problem, solutions, r):
    n, k, w = problem
    classes = import_module("cryptographic_estimators.SDEstimator.SDAlgorithms")
    ce = getattr(classes, name)(SDProblem(n, k, w, nsolutions=solutions), hmap=True)
    for ce_parameters, local_parameters in corresponding_parameters(n, k, w, name):
        expected_time, expected_memory = ce._time_and_memory_complexity({"r": r, **ce_parameters})
        actual = evaluate_parameters(n, k, w, name, targets=1, log2_solutions=solutions,
                                     r=r, **local_parameters)
        assert actual is not None
        assert actual.time_log2 == pytest.approx(expected_time + log2(n), abs=1e-11)
        assert actual.memory_log2 == pytest.approx(expected_memory + log2(n), abs=1e-11)


@pytest.mark.parametrize("name", SIMPLE_NAMES)
@pytest.mark.parametrize("problem,weights,solutions", [
    ((12, 6, 3), (0, 3), 0), ((21, 11, 4), (1, 3), 4.5),
    ((20, 10, 6), (1, 5), 8), ((20, 10, 6), (1, 5), 15.25),
])
def test_profile_changes_only_outer_probability_at_ce_fixed_point(name, problem, weights, solutions):
    n, k, w = problem
    profile = BlockProfile((n // 2, n - n // 2), weights)
    classes = import_module("cryptographic_estimators.SDEstimator.SDAlgorithms")
    ce = getattr(classes, name)(SDProblem(n, k, w, nsolutions=solutions), hmap=True)
    _install_ce_outer_probability(ce, profile)
    for ce_parameters, local_parameters in corresponding_parameters(n, k, w, name):
        expected_time, expected_memory = ce._time_and_memory_complexity({"r": 0, **ce_parameters})
        actual = evaluate_parameters(n, k, w, name, targets=1, log2_solutions=solutions,
                                     block_profile=profile, r=0, **local_parameters)
        plain = evaluate_parameters(n, k, w, name, targets=1, log2_solutions=solutions,
                                    r=0, **local_parameters)
        assert actual is not None and plain is not None
        assert actual.time_log2 == pytest.approx(expected_time + log2(n), abs=1e-11)
        assert actual.memory_log2 == pytest.approx(expected_memory + log2(n), abs=1e-11)
        assert actual.details["log2_iteration_bit_cost"] == plain.details["log2_iteration_bit_cost"]
        if name == "Stern":
            assert actual.details["residual_solutions"] == plain.details["residual_solutions"]
            assert actual.details["projections"] == plain.details["projections"]
            assert actual.details["unbalanced"]["tail_size"] == n - k


def matrix(n, k, r=0):
    return r, _gaussian_elimination_complexity(n, k, r), _mem_matrix(n, k, r)


def best_batch(n, k, terms, available, solutions, bound=None):
    costs = [_point(n, k, terms, matrix(n, k), u, solutions, bound)
             for u in range(1, available + 1)]
    feasible = [cost for cost in costs if cost is not None]
    candidates = _optimal_batches(n, k, terms, matrix(n, k), available, solutions, bound)
    selected = [_point(n, k, terms, matrix(n, k), u, solutions, bound) for u in candidates]
    assert all(point is not None for point in selected)
    if not feasible:
        assert candidates == ()
        return None
    exhaustive = min(feasible, key=lambda point: point.time_log2)
    optimized = min(selected, key=lambda point: point.time_log2)
    assert optimized.time_log2 == pytest.approx(exhaustive.time_log2, abs=1e-11)
    return optimized


def test_stern_batch_optimizer_finds_projection_jump_after_outer_saturation():
    terms = _terms(20, 10, 4, "Stern", {"l": 6, "p_left": 1, "p_right": 0})
    result = best_batch(20, 10, terms, 64, 0)
    assert result.parameters["targets_used"] == 17
    assert result.details["projections"] == 15
    old_affine_best = min(_point(20, 10, terms, matrix(20, 10), u, 0, None).time_log2
                          for u in (1, 8, 9))
    assert result.time_log2 < old_affine_best


@pytest.mark.parametrize("name", SIMPLE_NAMES)
@pytest.mark.parametrize("solutions", (0, 2.5, 6))
@pytest.mark.parametrize("profile", (None, BlockProfile((6, 6), (0, 3))))
def test_integer_batch_candidates_match_exhaustive_costs_with_memory_bounds(name, solutions, profile):
    n, k, w, available = 12, 6, 3, 37
    choices = [{}] if name == "Prange" else [
        {"l": ell, "p_left": pl, "p_right": pr}
        for ell in range(n-k+1) for pl in range(w+1) for pr in range(w-pl+1)
    ]
    for parameters in choices:
        terms = _terms(n, k, w, name, parameters, profile)
        if terms is None:
            continue
        memory_at_three = _point(n, k, terms, matrix(n, k), 3, solutions, None).memory_log2
        for bound in (None, memory_at_three, memory_at_three - 1e-7, 0):
            best_batch(n, k, terms, available, solutions, bound)


@pytest.mark.parametrize("n,k,w,solutions", [(20, 10, 6, 0), (21, 10, 6, 4),
                                            (40, 20, 8, 4), (41, 21, 8, 0)])
def test_bjmm_single_target_fixed_points_match_ce_time_and_memory(n, k, w, solutions):
    ce = BJMM(SDProblem(n, k, w, nsolutions=solutions), bit_complexities=1,
              memory_access=0, complexity_type=0).BJMM_depth_2
    checked = 0
    for ell in range(n-k):
        for p in range(0, w//2+1, 2):
            for p1 in range(p//2, min((k+ell)//2, p//2+4)+1):
                for r in (0, 2):
                    parameters = dict(l=ell, p=p, p1=p1, r=r)
                    if ce._are_parameters_invalid(parameters):
                        continue
                    ce_time, ce_memory = ce._time_and_memory_complexity(parameters)
                    if not isfinite(ce_time):
                        continue
                    actual = evaluate_parameters(n, k, w, "BJMM", targets=1,
                                                 log2_solutions=solutions,
                                                 weight_deficit=0, **parameters)
                    assert actual is not None, parameters
                    assert actual.time_log2 == pytest.approx(ce_time+log2(n), abs=1e-11)
                    assert actual.memory_log2 == pytest.approx(ce_memory+log2(n), abs=1e-11)
                    assert actual.details["half_lengths"] == [(k+ell)//2]*2
                    checked += 1
    assert checked >= 30


def test_representation_ceiling_rejects_too_few_matching_bits():
    # R=12 previously passed by clipping floor(log2 R) to ell=2.
    assert bjmm_terms(12, 6, 4, ell=2, p=2, p1=2, weight_deficit=1) is None
    assert bjmm_terms(20, 10, 4, ell=10, p=2, p1=1, weight_deficit=0) is None


@pytest.mark.parametrize("p,p1,ell,deficit,representations,repetitions", [
    (0, 0, 0, 0, 1, 1),
    (2, 1, 8, 0, 4, 1),
    (2, 2, 10, 1, 364, 2),
])
def test_representation_repetitions_scale_only_the_list_tree(
    p, p1, ell, deficit, representations, repetitions,
):
    n, k, w, u = 40, 20, 8, 7
    terms = bjmm_terms(n, k, w, ell=ell, p=p, p1=p1, weight_deficit=deficit)
    assert terms is not None
    details = terms["details"]
    assert terms["parameters"]["l1"] == (representations-1).bit_length()
    assert details["representation_repetitions"] == repetitions
    assert terms["log2_representations"] == pytest.approx(log2(representations))
    point = evaluate_parameters(n, k, w, "BJMM", targets=u, r=0, l=ell,
                                p=p, p1=p1, weight_deficit=deficit)
    list_work = min(shared+u*target for shared, target in details["list_work_branches"])
    iteration = n*(_gaussian_elimination_complexity(n, k, 0)+list_work)+(u-1)*(n-k)**2
    assert point.details["log2_iteration_bit_cost"] == pytest.approx(log2(iteration))
    if representations == 1:
        # All singleton merge calls cost one, rather than two inputs plus an output.
        assert list_work == 1+2*u


@pytest.mark.parametrize("deficit,targets", [(0, 1), (0, 16), (1, 1), (1, 14), (1, 15), (1, 32)])
def test_streaming_memory_uses_the_peak_of_build_and_probe_phases(deficit, targets):
    n, k, w, ell = 40, 20, 8, 8
    terms = bjmm_terms(n, k, w, ell=ell, p=2, p1=1, weight_deficit=deficit)
    assert terms is not None
    a, b, _, d = terms["details"]["base_list_sizes"]
    x, y = terms["details"]["intermediate_list_sizes_per_target"]
    peak = max(a+b+x, a+targets*d+x)
    expected_memory = n*(_mem_matrix(n, k, 0)+peak)+(targets-1)*(n-k)
    point = evaluate_parameters(n, k, w, "BJMM", targets=targets, r=0, l=ell,
                                p=2, p1=1, weight_deficit=deficit)
    assert point.memory_log2 == pytest.approx(log2(expected_memory))
    assert peak < a+b+x+targets*(d+y)
    assert "stream" in point.details["memory_model"]
    assert evaluate_parameters(n, k, w, "BJMM", targets=targets, r=0, l=ell,
                               p=2, p1=1, weight_deficit=deficit,
                               memory_bound_log2_bits=log2(expected_memory)-1e-8) is None


def test_multi_target_rounding_is_per_target_and_work_remains_affine():
    terms = bjmm_terms(40, 20, 8, ell=10, p=2, p1=2, weight_deficit=1)
    details = terms["details"]
    a, _, _, d = details["base_list_sizes"]
    x, y = details["intermediate_list_sizes_per_target"]
    l1 = terms["parameters"]["l1"]
    assert y == max(1, a*d//2**l1)
    assert 16*y != max(1, 16*a*d//2**l1)
    # Independent CE-style merges, with one stored shared side at each stage.
    shared = 2*((2*a+a*a//2**l1)+a+x)
    per_target = 2*(d+a*d//2**l1+y+x*y//2**(10-l1))
    assert details["list_work_shared"] == shared
    assert details["list_work_per_target"] == per_target
    for targets in (1, 2, 16):
        point = evaluate_parameters(40, 20, 8, "BJMM", targets=targets,
                                    r=0, l=10, p=2, p1=2, weight_deficit=1)
        expected = 40*(20**2+shared+targets*per_target)+(targets-1)*20**2
        assert point.details["log2_iteration_bit_cost"] == pytest.approx(log2(expected))


def test_singleton_fourth_leaf_can_reuse_a_shared_hash_table():
    n, k, w, ell = 40, 20, 8, 8
    terms = bjmm_terms(n, k, w, ell=ell, p=2, p1=1, weight_deficit=1)
    details = terms["details"]
    a, _, _, d = details["base_list_sizes"]
    assert (a, d) == (14, 1)
    scan, hashed = details["list_work_branches"]
    assert scan[0]+scan[1] < hashed[0]+hashed[1]
    assert scan[0]+2*scan[1] < hashed[0]+2*hashed[1]
    assert scan[0]+3*scan[1] > hashed[0]+3*hashed[1]
    for targets, branch in ((1, scan), (2, scan), (3, hashed), (64, hashed)):
        point = evaluate_parameters(n, k, w, "BJMM", targets=targets, r=0,
                                    l=ell, p=2, p1=1, weight_deficit=1)
        expected = n*((n-k)**2+branch[0]+targets*branch[1])+(targets-1)*(n-k)**2
        assert point.details["log2_iteration_bit_cost"] == pytest.approx(log2(expected))


def test_each_singleton_merge_selects_its_own_scan_or_hash_strategy():
    from codebased_estimator.doom_bjmm import _merge_options

    # These two singleton merges switch at different target counts, so taking
    # just an all-scan/all-hash minimum would omit the mixed strategy.
    second = _merge_options(16, 1, 4)
    final = _merge_options(4, 1, 1)
    combined = [(s[0]+f[0], s[1]+f[1]) for s in second for f in final]
    assert len(combined) == 4
    winner = min(range(4), key=lambda i: combined[i][0]+2*combined[i][1])
    assert winner == 2  # Hash the first merge, scan the second.
    assert _merge_options(1, 17, 3) == ((0, 17),)


def test_deficit_and_odd_coordinate_success_event_matches_enumerated_supports():
    n, k, w, ell, p, p1, deficit = 14, 5, 4, 4, 2, 1, 1
    terms = bjmm_terms(n, k, w, ell=ell, p=p, p1=p1, weight_deficit=deficit)
    assert terms is not None
    left, right = set(range(4)), set(range(4, 8))
    unused, tail = {8}, set(range(9, 14))
    matching = sum(len(set(support)&left) == 2 and len(set(support)&right) == 1
                   and not (set(support)&unused) and len(set(support)&tail) == 1
                   for support in combinations(range(n), w))
    assert terms["log2_probability"] == pytest.approx(log2(matching/comb(n, w)))
    assert terms["details"]["half_lengths"] == [4, 4]
    assert terms["details"]["unused_information_coordinates"] == 1
    assert terms["details"]["base_weights"] == [1, 1, 1, 0]


@pytest.mark.parametrize("profile", [None, BlockProfile((20, 20), (0, 8))])
@pytest.mark.parametrize("solutions", [0, 2.5, 6])
def test_batch_optimizer_matches_enumeration_across_streaming_phases(profile, solutions):
    from codebased_estimator.classical_doom import _optimal_batches, _point, _terms

    n, k, w, available = 40, 20, 8, 128
    matrix = (0, _gaussian_elimination_complexity(n, k, 0), _mem_matrix(n, k, 0))
    terms = _terms(n, k, w, "BJMM", dict(l=8, p=2, p1=1, weight_deficit=1), profile)
    branches = terms["details"]["list_memory_branches"]
    # Build/probe phases cross at u=14; exercise bounds on either side.
    assert branches[0][0] == branches[1][0]+14*branches[1][1]
    bounds = [None]
    bounds += [_point(n, k, terms, matrix, u, solutions, None).memory_log2
               for u in (1, 10, 14, 15, 32, 128)]
    bounds.append(bounds[1]-1e-8)
    for bound in bounds:
        candidates = _optimal_batches(n, k, terms, matrix, available, solutions, bound)
        brute = [_point(n, k, terms, matrix, u, solutions, bound)
                 for u in range(1, available+1)]
        brute = [point for point in brute if point is not None]
        selected = [_point(n, k, terms, matrix, u, solutions, bound) for u in candidates]
        assert all(point is not None for point in selected)
        if not brute:
            assert not selected
        else:
            assert min(point.time_log2 for point in selected) == pytest.approx(
                min(point.time_log2 for point in brute), abs=1e-12,
            )


@pytest.mark.parametrize("weights,solutions", [((0, 4), 0), ((1, 3), 2)])
def test_unbalanced_pruning_preserves_exhaustive_bjmm_minimum(weights, solutions):
    from codebased_estimator.classical_doom import _matrix_profiles, _optimize, _point, _terms

    n, k, w, available = 14, 6, 4, 32
    profile = BlockProfile((7, 7), weights)
    actual, search = _optimize(n, k, w, "BJMM", available, solutions, None,
                              SimpleNamespace(parameters={}, metadata={}), profile)
    brute = []
    for ell in range(n-k):
        for p in range(0, 2*w//3+1, 2):
            for p1 in range(p//2, (k+ell)//2+1):
                for deficit in range(min(p//2, p1)+1):
                    terms = _terms(n, k, w, "BJMM", dict(l=ell, p=p, p1=p1,
                                                         weight_deficit=deficit), profile)
                    if terms is None:
                        continue
                    for matrix in _matrix_profiles(n, k):
                        brute.extend(_point(n, k, terms, matrix, u, solutions, None)
                                     for u in range(1, available+1))
    assert search["exhaustive"] and not search["budget_exhausted"]
    assert actual.time_log2 == pytest.approx(min(point.time_log2 for point in brute), abs=1e-12)
