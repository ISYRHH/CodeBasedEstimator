"""Functional search contracts without external snapshots or research tools."""

from math import ceil, comb, log2

import pytest

from codebased_estimator.matrix_costs import MATRIX_PROFILES
from codebased_estimator.quantum_costs import _Model, evaluate_parameters, optimize
from codebased_estimator.quantum_search import boundary_candidates, refine_candidates


def complete_small_domain(n, k, w, algorithm, profile):
    """Enumerate legal integer points independently of search and pruning."""
    stride = 4 if algorithm == "QSS" else 2
    for ell in range(n - k + 1):
        K = k + ell
        for p in (0, K):
            point = evaluate_parameters(n, k, w, algorithm, ell=ell, p=p,
                                        matrix_profile=profile)
            if point is not None:
                yield point
        if K % stride:
            continue
        for p in range(4, min(w, K - 1) + 1, 4):
            for d in ((0,) if algorithm == "QSS" else range(0, K - p + 1, 2)):
                t = p // 4 + d // 2
                V = comb(K // stride, t)
                for u in sorted(set(range(1, V // 2 + 1)) | {V}):
                    for f in range(ell + 1):
                        for b in ((0,) if algorithm == "QSS" else range(f + 1)):
                            point = evaluate_parameters(
                                n, k, w, algorithm, ell=ell, p=p, d=d,
                                u=u, a=f - b, b=b, matrix_profile=profile,
                            )
                            if point is not None:
                                yield point


@pytest.mark.parametrize("algorithm", ["QSS", "QMMT+"])
@pytest.mark.parametrize("profile", MATRIX_PROFILES)
def test_small_search_is_exact_for_both_profiles_and_all_branches(algorithm, profile):
    candidates = list(complete_small_domain(12, 4, 4, algorithm, profile))
    assert {point.parameters["branch"] for point in candidates} == {
        "direct", "walk", "full_list",
    }
    if algorithm == "QMMT+":
        assert any(point.parameters["d"] > 0 for point in candidates)
        assert any(point.parameters["b"] > 0 for point in candidates)
    result = optimize(12, 4, 4, algorithm, matrix_profile=profile)
    assert result is not None
    assert result.time_log2 == pytest.approx(min(point.time_log2 for point in candidates), abs=1e-10)
    assert result.parameters in [point.parameters for point in candidates]
    assert result.search["global_optimum"] is True
    assert result.search["method"] == "exhaustive_integer_domain"
    assert result.search["refinement"] is None


@pytest.mark.parametrize("algorithm", ["QSS", "QMMT+"])
@pytest.mark.parametrize("profile", MATRIX_PROFILES)
def test_heuristic_is_reproducible_replayable_and_uses_the_best_filter_split(algorithm, profile):
    result = optimize(200, 100, 30, algorithm, matrix_profile=profile)
    repeated = optimize(200, 100, 30, algorithm, matrix_profile=profile)
    assert result is not None and repeated == result
    assert result.search["global_optimum"] is False
    assert result.search["method"] == "deterministic_multistart"
    point = {key: value for key, value in result.parameters.items() if key != "branch"}
    replay = evaluate_parameters(200, 100, 30, algorithm, matrix_profile=profile, **point)
    assert replay is not None
    assert (replay.time_log2, replay.parameters, replay.details, replay.matrix) == (
        result.time_log2, result.parameters, result.details, result.matrix)
    f = point["a"] + point["b"]
    splits = [evaluate_parameters(200, 100, 30, algorithm, matrix_profile=profile,
                                 **dict(point, a=f - b, b=b)) for b in range(f + 1)]
    assert result.time_log2 == pytest.approx(min(value.time_log2 for value in splits if value is not None))
    baseline = evaluate_parameters(200, 100, 30, algorithm, ell=0, p=0, matrix_profile=profile)
    assert result.time_log2 <= baseline.time_log2
    stats = result.search["refinement"]
    assert stats["candidate_points"] <= stats["point_budget"]
    assert stats["refined_time_log2"] <= stats["baseline_time_log2"]


def test_boundary_candidates_straddle_nearest_integer_cost_jumps():
    # Scan small integer sizes as an oracle; do not invert the thresholds.
    u, f, ell, umax = 16, 6, 12, 64
    candidates = boundary_candidates(u, f, ell, umax)

    def j1(x):
        return max(1, x * x // 2**f)

    def j2(x):
        return j1(x) ** 2 // 2 ** (ell - f)

    measures = {
        "leaf_sort": lambda x: x.bit_length() - 1,
        "leaf_index": lambda x: ceil(log2(2 + x)),
        "intermediate_sort": lambda x: j1(x).bit_length() - 1,
        "intermediate_index": lambda x: ceil(log2(2 + x * x / 2**f)),
        "terminal_load_index": lambda x: ceil(log2(2 + x**4 / 2 ** (ell + f))),
        "terminal_output": lambda x: j2(x) > 0,
        "terminal_output_index": lambda x: ceil(log2(2 + j2(x))),
    }
    assert set(candidates) == set(measures)
    for category, measure in measures.items():
        jumps = [x for x in range(2, umax + 1) if measure(x) != measure(x - 1)
                 and (category != "terminal_output_index" or j2(x - 1) > 0)]
        nearest = min(jumps, key=lambda x: (abs(x - u), x))
        assert {nearest - 1, nearest} <= set(candidates[category]), category
        assert tuple(sorted(set(candidates[category]))) == candidates[category]
        assert all(1 <= x <= umax for x in candidates[category])


@pytest.mark.parametrize("point_budget", [0, 2, 200])
def test_refinement_obeys_its_budget_and_retains_the_incumbent(point_budget):
    model = _Model(24, 12, 4, "QMMT+")
    baseline = model.evaluate(ell=4, p=4, u=2, a=1)
    queried = []

    def evaluate(shape, ell, p, d, u, f):
        queried.append((ell, p, d, u, f))
        costs = [model.evaluate(ell=ell, p=p, d=d, u=u, a=f - b, b=b)
                 for b in range(min(f, shape["R"].bit_length() - 1) + 1)]
        return min(costs, key=lambda cost: cost.time_log2)

    result, stats = refine_candidates(model, [baseline], baseline, evaluate,
                                      point_budget=point_budget)
    assert result.time_log2 <= baseline.time_log2
    assert stats["candidate_points"] == len(queried) == len(set(queried))
    assert stats["candidate_points"] <= point_budget
    assert stats["baseline_parameters"] == baseline.parameters
    assert stats["refined_time_log2"] == result.time_log2
    if point_budget == 0:
        assert result is baseline and stats["applied"] is False
    elif point_budget == 2:
        assert len(queried) == point_budget and stats["budget_exhausted"] is True
