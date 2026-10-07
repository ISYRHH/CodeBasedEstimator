"""Independent arithmetic and search contracts for the outer-union proxy."""

from dataclasses import replace
from decimal import Decimal, localcontext
from math import comb, expm1, isfinite, log2

import pytest

from codebased_estimator import quantum_costs as costs
from codebased_estimator.matrix_costs import DEFAULT_MATRIX_PROFILE, M4RI_MATRIX_PROFILE


def parameters(point):
    return {key: value for key, value in point.parameters.items() if key != "branch"}


@pytest.mark.parametrize("q,M", [(0.125, 3), (0.9, 2), (0.001, 17), (0.5, 1)])
def test_union_matches_independent_high_precision_arithmetic(q, M):
    with localcontext() as context:
        context.prec = 70
        expected = float((1 - (1 - Decimal(str(q))) ** M).ln() / Decimal(2).ln())
    assert costs._log_solution_union(log2(q), log2(M)) == pytest.approx(expected, abs=1e-13)


def test_union_survives_underflow_huge_multiplicity_and_endpoints():
    # Both q and M fall outside float range, while M*q=1 is ordinary.
    assert costs._log_solution_union(-2000, 2000) == pytest.approx(log2(-expm1(-1)))
    assert costs._log_solution_union(-2000, 1000) == -1000
    assert costs._log_solution_union(-2000, 1e308) == 0
    assert costs._log_solution_union(0, 1e308) == 0
    assert costs._log_solution_union(-float("inf"), 1e308) == -float("inf")
    assert costs._log_solution_union(-2000, 0) == -2000


@pytest.mark.parametrize("s", [-1, float("nan"), float("inf"), True, "2"])
def test_invalid_solution_counts_are_rejected_by_both_entry_points(s):
    with pytest.raises(ValueError, match="log2_solutions"):
        costs.evaluate_parameters(24, 12, 4, "QSS", ell=4, p=4, log2_solutions=s)
    with pytest.raises(ValueError, match="log2_solutions"):
        costs.optimize(24, 12, 4, "QSS", log2_solutions=s)


def test_explicit_single_solution_preserves_default_point_and_search():
    assert costs.evaluate_parameters(24, 12, 4, "QMMT+", ell=4, p=4, b=2) == (
        costs.evaluate_parameters(24, 12, 4, "QMMT+", ell=4, p=4, b=2,
                                  log2_solutions=0, codeword_finding=False))
    assert costs.optimize(24, 12, 4, "QMMT+") == costs.optimize(
        24, 12, 4, "QMMT+", log2_solutions=0, codeword_finding=False)


def test_finite_union_scales_only_repeated_cost_and_preserves_inner_budget():
    args = dict(ell=4, p=4, d=2, u=6, b=4)
    single = costs.evaluate_parameters(12, 4, 4, "QMMT+", **args)
    multi = costs.evaluate_parameters(12, 4, 4, "QMMT+", log2_solutions=log2(3), **args)
    q = (36 / 495) * (16 / 31)
    rho = 2 ** single.details["log2_rho"]
    effective = rho * (1 - (1 - q) ** 3)
    assert multi.details["log2_q_single"] == pytest.approx(log2(q))
    assert multi.details["log2_q_multi"] == pytest.approx(log2(1 - (1 - q) ** 3))
    assert multi.details["log2_outer_occupancy"] == pytest.approx(log2(3 * q))
    assert multi.details["log2_P_eff_model"] == pytest.approx(log2(effective))
    assert multi.details["log2_P_eff_single"] == single.details["log2_P_eff_model"]
    for key in ("log2_T0", "log2_R", "log2_S", "log2_U", "log2_Q"):
        assert multi.details[key] == single.details[key]
    T0 = 2 ** single.details["log2_T0"]
    expected = T0 + (2 ** single.time_log2 - T0) * (rho * q / effective) ** 0.5
    assert multi.time_log2 == pytest.approx(log2(expected))


def test_saturation_keeps_the_common_rank_factor_and_finite_budget():
    point = costs.evaluate_parameters(24, 12, 4, "QSS", ell=0, p=0,
                                      log2_solutions=1024)
    assert isfinite(point.time_log2)
    assert point.details["log2_q_multi"] == 0
    assert point.details["log2_rho"] < 0
    assert point.details["log2_P_eff_model"] == point.details["log2_rho"]


def test_sparse_union_gives_square_root_gain_without_changing_walk_marking():
    args = dict(ell=20, p=4, u=2, a=1)
    single = costs.evaluate_parameters(1000, 500, 100, "QSS", **args)
    multi = costs.evaluate_parameters(1000, 500, 100, "QSS", log2_solutions=8, **args)
    assert multi.details["log2_outer_occupancy"] < -54
    for key in ("log2_epsilon_lower", "log2_delta", "log2_S", "log2_U", "log2_Q"):
        assert multi.details[key] == single.details[key]
    T0 = 2 ** single.details["log2_T0"]
    expected = T0 + (2 ** single.time_log2 - T0) / 16
    assert multi.time_log2 == pytest.approx(log2(expected), abs=1e-12)


def all_small_points(algorithm, profile, codeword_finding):
    n, k, w = 12, 4, 4
    options = dict(log2_solutions=log2(3), codeword_finding=codeword_finding,
                   matrix_profile=profile)
    stride = 4 if algorithm == "QSS" else 2
    for ell in range(n - k + 1):
        K = k + ell
        for p in (0, K):
            point = costs.evaluate_parameters(n, k, w, algorithm, ell=ell, p=p, **options)
            if point is not None:
                yield point
        if K % stride:
            continue
        for p in range(4, min(w, K - 1) + 1, 4):
            for d in ((0,) if algorithm == "QSS" else range(0, K - p + 1, 2)):
                V = comb(K // stride, p // 4 + d // 2)
                for u in sorted(set(range(1, V // 2 + 1)) | {V}):
                    for f in range(ell + 1):
                        for b in ((0,) if algorithm == "QSS" else range(f + 1)):
                            point = costs.evaluate_parameters(
                                n, k, w, algorithm, ell=ell, p=p, d=d, u=u,
                                a=f - b, b=b, **options)
                            if point is not None:
                                yield point


@pytest.mark.parametrize("algorithm", ["QSS", "QMMT+"])
@pytest.mark.parametrize("profile", [DEFAULT_MATRIX_PROFILE, M4RI_MATRIX_PROFILE])
@pytest.mark.parametrize("codeword_finding", [False, True])
def test_multisolution_search_matches_full_small_domain(algorithm, profile, codeword_finding):
    candidates = list(all_small_points(algorithm, profile, codeword_finding))
    point = costs.optimize(12, 4, 4, algorithm, log2_solutions=log2(3),
                           codeword_finding=codeword_finding, matrix_profile=profile)
    assert point.time_log2 == pytest.approx(min(c.time_log2 for c in candidates))
    assert point.search["global_optimum"] is True
    assert point.search["filter_split"] == "enumerated"
    if codeword_finding:
        assert point.parameters["p"] > 0


def test_codeword_search_excludes_only_zero_direct_branch_and_handles_empty_domain():
    assert costs.evaluate_parameters(10, 2, 4, "QSS", ell=1, p=0,
                                      codeword_finding=True) is None
    allowed = costs.evaluate_parameters(10, 2, 4, "QSS", ell=1, p=3,
                                        codeword_finding=True)
    assert allowed == costs.evaluate_parameters(10, 2, 4, "QSS", ell=1, p=3)
    assert costs.optimize(12, 8, 1, "QSS", codeword_finding=True,
                           log2_solutions=3) is None


def test_multisolution_search_retains_single_candidate_when_heuristic_misses_it(monkeypatch):
    single = costs.optimize(24, 12, 4, "QSS")
    replay = costs.evaluate_parameters(24, 12, 4, "QSS", log2_solutions=2,
                                       **parameters(single))
    poor = costs.evaluate_parameters(24, 12, 4, "QSS", ell=0, p=0,
                                     log2_solutions=2)
    assert poor.time_log2 > replay.time_log2

    def search(n, k, w, algorithm, matrix_profile=DEFAULT_MATRIX_PROFILE, *,
               log2_solutions=0, codeword_finding=False):
        selected = poor if log2_solutions else single
        return replace(selected, search={"evaluated_points": 7, "global_optimum": False})

    monkeypatch.setattr(costs, "_optimize", search)
    result = costs.optimize(24, 12, 4, "QSS", log2_solutions=2)
    assert result.parameters == replay.parameters
    assert result.time_log2 == replay.time_log2
    assert result.search["single_solution_retention"]["selected_from"] == "single_replay"
    assert result.search["evaluated_points"] == 15


def test_saturated_search_reoptimizes_parameters_and_profile_replay_keeps_solution_count():
    single = costs.optimize(24, 12, 4, "QMMT+")
    multi = costs.optimize(24, 12, 4, "QMMT+", log2_solutions=8,
                            matrix_profile=M4RI_MATRIX_PROFILE)
    assert single.parameters != multi.parameters
    replay = costs.evaluate_parameters(24, 12, 4, "QMMT+", log2_solutions=8,
                                       matrix_profile=M4RI_MATRIX_PROFILE, **parameters(multi))
    assert (multi.time_log2, multi.details, multi.matrix) == (
        replay.time_log2, replay.details, replay.matrix)
    legacy_multi = costs.optimize(24, 12, 4, "QMMT+", log2_solutions=8)
    legacy_replay = costs.evaluate_parameters(
        24, 12, 4, "QMMT+", log2_solutions=8,
        matrix_profile=M4RI_MATRIX_PROFILE, **parameters(legacy_multi))
    assert multi.time_log2 <= legacy_replay.time_log2


def test_large_codeword_search_selects_best_integer_filter_split():
    point = costs.optimize(200, 100, 30, "QMMT+", log2_solutions=4,
                           codeword_finding=True)
    params = parameters(point)
    f = params["a"] + params["b"]
    splits = [costs.evaluate_parameters(
        200, 100, 30, "QMMT+", log2_solutions=4, codeword_finding=True,
        **dict(params, a=f - b, b=b)) for b in range(f + 1)]
    assert point.time_log2 == min(c.time_log2 for c in splits if c is not None)
    assert point.parameters["p"] > 0
    assert point.search["filter_split"] == "enumerated"
