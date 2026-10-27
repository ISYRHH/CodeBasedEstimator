"""Block-conditioned outer events precede quantum survival and union factors."""

from dataclasses import replace
from fractions import Fraction
from itertools import product
from math import comb, log2, prod, sqrt

import pytest

from codebased_estimator import AttackInstance, Options, Problem, estimate
from codebased_estimator import quantum_costs as costs
from codebased_estimator.matrix_costs import DEFAULT_MATRIX_PROFILE, M4RI_MATRIX_PROFILE
from codebased_estimator.unbalanced import BlockProfile


def log_fraction(value):
    return log2(value.numerator)-log2(value.denominator)


def rank_probability(n, k, ell):
    return prod((1-Fraction(1, 2**(n-k-i)))/(1-Fraction(1, 2**(n-i)))
                for i in range(n-k-ell))


@pytest.mark.parametrize("algorithm,d,u,a,b", [
    ("QSS", 0, 1, 0, 0), ("QMMT+", 2, 6, 0, 4), ("QMMT+", 0, 1, 2, 1),
])
@pytest.mark.parametrize("solutions", [1, 17])
def test_block_event_survival_union_and_time_match_exact_formula(algorithm, d, u, a, b, solutions):
    profile = BlockProfile((5, 7), (3, 1))
    arguments = dict(ell=4, p=4, d=d, u=u, a=a, b=b)
    baseline = costs.evaluate_parameters(12, 4, 4, algorithm, **arguments)
    actual = costs.evaluate_parameters(12, 4, 4, algorithm, **arguments,
                                      log2_solutions=log2(solutions), block_profile=profile)
    # For four tail positions, the five allocations have probabilities
    # 3/7, 8/35, 1/14, 0, 0 of leaving all four errors inside. Then shuffle.
    split = Fraction(16 if algorithm == "QSS" else 36, comb(8, 4))
    event = Fraction(3, 7)*split
    representations = 1 if algorithm == "QSS" else (comb(2, 1)*comb(2, d//2))**2
    sigma = Fraction(representations, representations+2**b-1)
    rho = rank_probability(12, 4, 4)
    q = event*sigma
    union = 1-(1-q)**solutions
    for key, expected in (("log2_P", event), ("log2_sigma", sigma), ("log2_rho", rho),
                          ("log2_q_single", q), ("log2_q_multi", union),
                          ("log2_P_eff_model", rho*union)):
        assert actual.details[key] == pytest.approx(log_fraction(expected), abs=2e-12)
    expected_time = (2**baseline.details["log2_T0"] + 12/sqrt(float(rho*union)) *
                     (2**baseline.details["log2_G"] + 2**(a/2)*2**baseline.details["log2_Q"]))
    assert actual.time_log2 == pytest.approx(log2(expected_time), abs=2e-12)
    assert actual.details["log2_P_uniform"] == baseline.details["log2_P"]
    for key in ("log2_T0", "log2_G", "log2_Q", "log2_R", "log2_V", "log2_S", "log2_U"):
        assert actual.details[key] == baseline.details[key]


@pytest.mark.parametrize("direct", [False, True])
def test_saturated_block_event_keeps_common_rank_and_initialization(direct):
    n, k, profile = ((24, 12, BlockProfile((12, 12), (4, 0))) if direct else
                     (12, 4, BlockProfile((5, 7), (3, 1))))
    arguments = (dict(ell=0, p=0) if direct else dict(ell=4, p=4, d=2, u=6, b=4))
    point = costs.evaluate_parameters(n, k, 4, "QMMT+", **arguments,
                                      block_profile=profile, log2_solutions=1024)
    assert (point.details["log2_q_single"] == 0) == direct
    assert point.details["log2_q_multi"] == 0
    rho = rank_probability(n, k, arguments["ell"])
    assert point.details["log2_P_eff_model"] == pytest.approx(log_fraction(rho))
    expected = (2**point.details["log2_T0"] + n/sqrt(float(rho)) *
                (2**point.details["log2_G"] + 2**point.details["log2_Q"]))
    assert point.time_log2 == pytest.approx(log2(expected), abs=2e-12)


def small_points(algorithm, profile):
    for ell in range(9):
        K = 4 + ell
        for p in (0, K):
            value = costs.evaluate_parameters(12, 4, 4, algorithm, ell=ell, p=p,
                                              block_profile=profile)
            if value is not None:
                yield value
        if K % (4 if algorithm == "QSS" else 2):
            continue
        for p in range(4, min(4, K - 1) + 1, 4):
            for d in ((0,) if algorithm == "QSS" else range(0, K - p + 1, 2)):
                V = comb(K // (4 if algorithm == "QSS" else 2), p // 4 + d // 2)
                for u in sorted(set(range(1, V // 2 + 1)) | {V}):
                    for f in range(ell + 1):
                        for b in ((0,) if algorithm == "QSS" else range(f + 1)):
                            value = costs.evaluate_parameters(
                                12, 4, 4, algorithm, ell=ell, p=p, d=d, u=u,
                                a=f - b, b=b, block_profile=profile)
                            if value is not None:
                                yield value


@pytest.mark.parametrize("algorithm", ["QSS", "QMMT+"])
def test_search_uses_block_event_and_replays_selected_cost(algorithm):
    profile = BlockProfile((6, 6), (4, 0))
    result = costs.optimize(12, 4, 4, algorithm, block_profile=profile)
    assert result.time_log2 == pytest.approx(min(c.time_log2 for c in small_points(algorithm, profile)))
    replay = costs.evaluate_parameters(
        12, 4, 4, algorithm, block_profile=profile,
        **{key: value for key, value in result.parameters.items() if key != "branch"})
    assert (result.time_log2, result.details, result.unbalanced) == (
        replay.time_log2, replay.details, replay.unbalanced)
    assert result.search["unbalanced_retention"]["applied"]


def test_qcsd_single_target_fallback_preserves_block_conditioning():
    instance = AttackInstance(
        "profiled QCSD", "msg_recovery", Problem("sd", dict(n=12, k=4, w=4)),
        targets=32, tags=("doom:qcsd",), block_profile=BlockProfile((6, 6), (4, 0)))
    options = Options(classical_algorithms=(), quantum_algorithms=("QSS",))
    actual, = estimate(instance, options=options).results
    expected, = estimate(replace(instance, tags=(), targets=1), options=options).results
    assert actual.time_log2 == expected.time_log2
    assert actual.parameters == expected.parameters
    assert actual.metadata["unbalanced"] == expected.metadata["unbalanced"]
    assert actual.metadata["doom"]["active_targets"] == 1


def test_qccf_does_not_assign_one_profile_to_heterogeneous_target_classes(monkeypatch):
    profile = BlockProfile((6, 6), (4, 0), ((0, 1), (1, 0)))
    instance = AttackInstance(
        "heterogeneous QCCF", "key_recovery", Problem("qccf", dict(n=12, k=4, w=4, q=2)),
        targets=12, tags=("doom:qccf",), block_profile=profile)

    def forbidden(*args, **kwargs):
        pytest.fail("heterogeneous QCCF must not silently use one target profile")

    monkeypatch.setattr("codebased_estimator.quantum.optimize", forbidden)
    result, = estimate(instance, options=Options(
        classical_algorithms=(), quantum_algorithms=("QSS",))).results
    assert result.status == "not_implemented"
    assert "different block-weight profiles" in result.reason


def test_corrected_search_retains_baseline_when_heuristic_misses_it(monkeypatch):
    profile = BlockProfile((12, 12), (3, 1))
    baseline = costs.optimize(24, 12, 4, "QSS")
    replay = costs.evaluate_parameters(
        24, 12, 4, "QSS", block_profile=profile,
        **{key: value for key, value in baseline.parameters.items() if key != "branch"})
    poor = costs.evaluate_parameters(24, 12, 4, "QSS", ell=8, p=0,
                                     block_profile=profile)
    assert poor.time_log2 > replay.time_log2

    def search(*args, block_profile=None, **kwargs):
        selected = baseline if block_profile is None else poor
        return replace(selected, search={"evaluated_points": 7, "global_optimum": False})

    monkeypatch.setattr(costs, "_optimize_with_matrix_retention", search)
    result = costs.optimize(24, 12, 4, "QSS", block_profile=profile)
    assert result.time_log2 == replay.time_log2
    assert result.parameters == replay.parameters
    assert result.search["unbalanced_retention"]["selected_from"] == "baseline_replay"
    assert result.search["evaluated_points"] == 15


@pytest.mark.parametrize("algorithm,matrix_profile,codewords,solutions", [
    ("QSS", DEFAULT_MATRIX_PROFILE, False, 1),
    ("QSS", M4RI_MATRIX_PROFILE, True, 3),
    ("QMMT+", DEFAULT_MATRIX_PROFILE, True, 3),
    ("QMMT+", M4RI_MATRIX_PROFILE, False, 17),
])
def test_optimizer_replays_complete_probability_and_matrix_context(algorithm, matrix_profile, codewords, solutions):
    options = dict(matrix_profile=matrix_profile, codeword_finding=codewords,
                   log2_solutions=log2(solutions), block_profile=BlockProfile((5, 7), (3, 1)))
    result = costs.optimize(12, 4, 4, algorithm, **options)
    replay = costs.evaluate_parameters(12, 4, 4, algorithm, **options,
        **{key: value for key, value in result.parameters.items() if key != "branch"})
    assert (result.time_log2, result.details, result.matrix, result.unbalanced) == (
        replay.time_log2, replay.details, replay.matrix, replay.unbalanced)
    if codewords:
        assert result.parameters["p"] != 0
    retention = result.search["unbalanced_retention"]
    assert result.time_log2 <= retention["replayed_time_log2"]
    assert result.time_log2 <= retention["baseline_time_log2"]+1e-12


@pytest.mark.parametrize("algorithm,parameters,recorded_time", [
    ("QSS", dict(ell=46, p=8, d=0, u=861577, a=20, b=0), 118.46512227382394),
    ("QMMT+", dict(ell=48, p=8, d=0, u=2097119, a=16, b=5), 117.530253241982),
])
def test_large_fixed_point_uses_finite_event_and_preserves_original_inner_cost(algorithm, parameters, recorded_time):
    n, k, w = 52436, 26218, 168
    profile = BlockProfile((13109,)*4, (29, 29, 27, 83))
    baseline = costs.evaluate_parameters(n, k, w, algorithm, **parameters)
    assert baseline.time_log2 == pytest.approx(recorded_time, abs=2e-10)
    actual = costs.evaluate_parameters(n, k, w, algorithm, **parameters, block_profile=profile)
    allocation, p = actual.unbalanced["allocation"], parameters["p"]
    # Exact coefficient enumeration for the selected allocation, independent
    # of the estimator's logarithmic hypergeometric recurrence/convolution.
    numerator = sum(prod(comb(length-tail, j)*comb(tail, weight-j)
                         for length, weight, tail, j in zip(profile.lengths, profile.weights, allocation, js))
                    for js in product(range(p+1), repeat=4) if sum(js) == p)
    event = Fraction(numerator, prod(comb(length, weight)
                                     for length, weight in zip(profile.lengths, profile.weights)))
    K = k+parameters["ell"]
    split = Fraction(comb(K//4, p//4)**4 if algorithm == "QSS" else comb(K//2, p//2)**2, comb(K, p))
    lp = log_fraction(event*split)
    assert actual.details["log2_P"] == pytest.approx(lp, abs=2e-9)
    effective = lp+baseline.details["log2_sigma"]+baseline.details["log2_rho"]
    expected = (2**baseline.details["log2_T0"] + n*2**(-effective/2) *
                (2**baseline.details["log2_G"] + 2**(parameters["a"]/2)*2**baseline.details["log2_Q"]))
    assert actual.time_log2 == pytest.approx(log2(expected), abs=2e-9)
    assert actual.time_log2 < baseline.time_log2
