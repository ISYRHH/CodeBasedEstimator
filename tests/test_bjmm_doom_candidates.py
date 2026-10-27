"""BJMM's empirical QCSD candidate is independently optimized CE depth three."""

from dataclasses import replace
import json
from math import inf, log2, nextafter

import pytest

from codebased_estimator import AttackInstance, Options, Problem, estimate
from codebased_estimator.backend import (
    _ce_bjmm_depth3, _install_ce_outer_probability, _with_bjmm_depth3_candidate,
)
from codebased_estimator.models import Estimate
from codebased_estimator.unbalanced import BlockProfile


def instance(*, n=40, k=20, w=4, targets=32, solutions=0, profile=None):
    return AttackInstance(
        "BJMM candidate test", "key_recovery",
        Problem("sd", {"n": n, "k": k, "w": w, "q": 2}, solutions),
        targets=targets, tags=("doom:qcsd",), block_profile=profile,
    )


def options(bound=None):
    return Options(classical_algorithms=("BJMM",), quantum_algorithms=(),
                   memory_bound_log2_bits=bound)


def explicit_candidate(time=100.0):
    return Estimate(
        "BJMM", "classical", "computed", time, 10.0,
        {"depth": 2, "targets_used": 7},
        metadata={"doom": {"strategy": "explicit_doom", "search": {"method": "test"},
                           "baseline_time_log2": 120.0},
                  "cost_breakdown": {"explicit_time": time}},
    )


@pytest.mark.parametrize("solutions", [None, 0, 2.5])
@pytest.mark.parametrize("bound", [None, 17.0])
def test_fixed_depth_three_optimizes_all_own_parameters_like_fresh_ce(solutions, bound):
    from cryptographic_estimators.SDEstimator import SDProblem
    from cryptographic_estimators.SDEstimator.SDAlgorithms.bjmm import BJMMd3

    attack = instance(n=100, k=50, w=10, solutions=solutions)
    kwargs = {"memory_bound": inf if bound is None else bound}
    if solutions is not None:
        kwargs["nsolutions"] = solutions
    upstream = BJMMd3(SDProblem(100, 50, 10, **kwargs),
                      bit_complexities=1, complexity_type=0, memory_access=0)
    actual = _ce_bjmm_depth3(attack, options(bound))
    assert actual.status == "computed"
    assert actual.time_log2 == upstream.time_complexity()
    assert actual.memory_log2 == upstream.memory_complexity()
    assert actual.parameters == {"depth": 3, **upstream.get_optimal_parameters_dict()}
    assert actual.metadata["effective_log2_solutions"] == upstream.problem.nsolutions


def test_candidate_does_not_discount_the_ce_parents_selected_depth_two():
    from cryptographic_estimators.SDEstimator import SDProblem
    from cryptographic_estimators.SDEstimator.SDAlgorithms.bjmm import BJMM

    attack = instance(n=100, k=50, w=10, targets=64)
    parent = BJMM(SDProblem(100, 50, 10, nsolutions=0),
                  bit_complexities=1, complexity_type=0, memory_access=0)
    parent_time = parent.time_complexity()
    assert parent.get_optimal_parameters_dict()["depth"] == 2
    raw = _ce_bjmm_depth3(attack, options())
    result = _with_bjmm_depth3_candidate(attack, options(), explicit_candidate())
    assert result.parameters == raw.parameters
    assert result.parameters["depth"] == 3 and "p2" in result.parameters
    assert result.time_log2 == raw.time_log2-log2(64)/2
    assert result.time_log2 != pytest.approx(parent_time-log2(64)/2)
    assert result.memory_log2 == raw.memory_log2
    assert result.metadata["doom"]["bjmm_depth3_comparison"]["depth_two_sqrt_discount_applied"] is False


@pytest.mark.parametrize("solutions", [0, 1.5])
def test_public_depth_three_winner_replays_one_discount_and_unchanged_solution_count(solutions):
    attack = instance(targets=1024, solutions=solutions)
    raw = _ce_bjmm_depth3(attack, options())
    report = estimate(attack, options=options())
    json.dumps(report.to_dict(), allow_nan=False)
    result, = report.results
    assert result.metadata["doom"]["strategy"] == "ce_depth3_sqrt_targets"
    assert result.time_log2 == max(0.0, raw.time_log2-log2(attack.targets)/2)
    assert result.memory_log2 == raw.memory_log2
    assert result.parameters == raw.parameters
    assert result.metadata["effective_log2_solutions"] == solutions
    assert result.metadata["doom"]["active_targets"] == 1024


def test_profile_candidate_uses_existing_outer_hook_and_only_preserving_subgroup():
    from cryptographic_estimators.SDEstimator import SDProblem
    from cryptographic_estimators.SDEstimator.SDAlgorithms.bjmm import BJMMd3

    profile = BlockProfile((20, 20), (0, 4), ((0, 1), (1, 0)))
    attack = instance(profile=profile, targets=32)
    upstream = BJMMd3(SDProblem(40, 20, 4, nsolutions=0),
                      bit_complexities=1, complexity_type=0, memory_access=0)
    details = _install_ce_outer_probability(upstream, profile)
    raw_time = upstream.time_complexity()
    result, = estimate(attack, options=options()).results
    doom = result.metadata["doom"]
    assert doom["strategy"] == "profile_ce_depth3_sqrt_targets"
    assert doom["active_targets"] == profile.preserving_targets(32) == 16
    assert result.time_log2 == raw_time-log2(16)/2
    assert result.memory_log2 == upstream.memory_complexity()
    assert result.parameters == {"depth": 3, **upstream.get_optimal_parameters_dict()}
    original_details = details(upstream.get_optimal_parameters_dict())
    for key in ("tail_size", "information_weight", "log2_repetition_gain", "inner_costs"):
        assert result.metadata["unbalanced"][key] == original_details[key]
    candidates = doom["bjmm_depth3_comparison"]["candidates"]
    assert [candidate["active_targets"] for candidate in candidates] == [32, 16]
    assert "unbalanced" not in candidates[0] and candidates[1]["unbalanced"]["applied"]


def test_profile_default_solution_count_is_shared_by_both_depth_three_candidates():
    profile = BlockProfile((10, 10), (0, 8), ((0, 1), (1, 0)))
    attack = instance(n=20, k=10, w=8, targets=32, solutions=None, profile=profile)
    implicit, = estimate(attack, options=options()).results
    explicit, = estimate(replace(attack, problem=replace(attack.problem, log2_solutions=0)),
                         options=options()).results
    assert implicit.time_log2 == explicit.time_log2
    assert implicit.parameters == explicit.parameters
    assert implicit.metadata["effective_log2_solutions"] == 0
    candidates = implicit.metadata["doom"]["bjmm_depth3_comparison"]["candidates"]
    assert all(candidate["effective_log2_solutions"] == 0 for candidate in candidates)


def test_generic_candidate_keeps_full_orbit_and_same_count_with_an_unhelpful_profile(monkeypatch):
    import codebased_estimator.backend as backend

    profile = BlockProfile((20, 20), (1, 3), ((0, 1), (1, 0)))
    attack = instance(profile=profile, targets=64, solutions=2.5)
    calls = []

    def fake_child(candidate, selected_options):
        calls.append(candidate)
        return Estimate("BJMM", "classical", "computed",
                        100.0 if candidate.block_profile is None else 101.0,
                        10.0, {"depth": 3, "p2": 2},
                        metadata={"effective_log2_solutions": candidate.problem.log2_solutions})

    monkeypatch.setattr(backend, "_ce_bjmm_depth3", fake_child)
    result = _with_bjmm_depth3_candidate(attack, options(), explicit_candidate(110.0))
    assert len(calls) == 2
    assert all(call.problem.log2_solutions == 2.5 for call in calls)
    assert all(call.targets == 1 and call.tags == () for call in calls)
    assert result.time_log2 == 97.0
    assert result.metadata["doom"]["active_targets"] == 64
    assert result.metadata["unbalanced"]["strategy"] == "generic_full_orbit"
    assert result.metadata["unbalanced"]["applied"] is False


def test_existing_explicit_winner_gets_no_extra_discount_or_changed_details():
    explicit = explicit_candidate(1.0)
    result = _with_bjmm_depth3_candidate(instance(), options(), explicit)
    assert result.time_log2 == explicit.time_log2
    assert result.memory_log2 == explicit.memory_log2
    assert result.parameters == explicit.parameters
    assert result.metadata["cost_breakdown"] == explicit.metadata["cost_breakdown"]
    assert result.metadata["doom"]["strategy"] == "explicit_doom"
    assert result.metadata["doom"]["search"] == explicit.metadata["doom"]["search"]


@pytest.mark.parametrize("profile", [None, BlockProfile((20, 20), (0, 4))])
def test_depth_three_cannot_evade_memory_bound(profile):
    attack = instance(profile=profile, targets=1024)
    raw = _ce_bjmm_depth3(attack, options())
    bound = nextafter(raw.memory_log2, 0)
    limited = _ce_bjmm_depth3(attack, options(bound))
    assert limited.status != "computed" or limited.memory_log2 <= bound
    result, = estimate(attack, options=options(0)).results
    assert result.status != "computed"
    candidates = result.metadata["doom"]["bjmm_depth3_comparison"]["candidates"]
    assert all(candidate["status"] != "computed" for candidate in candidates)


@pytest.mark.parametrize("route", ["single_target", "ordinary", "qccf", "other_algorithm"])
def test_new_depth_three_candidate_is_isolated_to_multitarget_qcsd_bjmm(monkeypatch, route):
    import codebased_estimator.backend as backend

    def unexpected(*args, **kwargs):
        raise AssertionError("QCSD depth-three candidate reached an unchanged route")

    monkeypatch.setattr(backend, "_ce_bjmm_depth3", unexpected)
    attack = instance()
    selected_options = options()
    if route == "single_target":
        attack = replace(attack, targets=1)
    elif route == "ordinary":
        attack = replace(attack, targets=1, tags=())
    elif route == "qccf":
        attack = replace(attack, tags=("doom:qccf",),
                         problem=replace(attack.problem, kind="cfp", log2_solutions=None))
    else:
        selected_options = replace(selected_options, classical_algorithms=("BothMay",))
    result, = estimate(attack, options=selected_options).results
    assert result.status == "computed"


def test_extreme_target_count_clamps_depth_three_time_at_zero():
    attack = instance(targets=1 << 100)
    result = _with_bjmm_depth3_candidate(attack, options(), explicit_candidate())
    assert result.time_log2 == 0.0
    assert result.metadata["doom"]["log2_proxy_speedup"] == 50.0
    assert result.metadata["doom"]["realized_log2_proxy_speedup"] < 50.0


@pytest.mark.parametrize("n,k,w,profile", [
    (100, 80, 12, None),
    (100, 50, 10, None),
    (100, 50, 10, BlockProfile((50, 50), (0, 10))),
])
def test_ce_baseline_records_real_depth_two_seed_without_reoptimizing(monkeypatch, n, k, w, profile):
    from cryptographic_estimators.SDEstimator import SDProblem
    from cryptographic_estimators.SDEstimator.SDAlgorithms.bjmm import BJMMd2

    expected = BJMMd2(SDProblem(n, k, w, nsolutions=0),
                      bit_complexities=1, complexity_type=0, memory_access=0)
    if profile is not None:
        _install_ce_outer_probability(expected, profile)
    expected_time = expected.time_complexity()
    expected_memory = expected.memory_complexity()
    calls = []
    original = BJMMd2._find_optimal_parameters

    def count_search(child):
        calls.append(child)
        return original(child)

    monkeypatch.setattr(BJMMd2, "_find_optimal_parameters", count_search)
    attack = replace(instance(n=n, k=k, w=w, targets=1, profile=profile), tags=())
    result, = estimate(attack, options=options()).results
    assert result.metadata["ce_depth_two_parameters"] == expected.get_optimal_parameters_dict()
    assert result.metadata["ce_depth_two_time_log2"] == expected_time
    assert result.metadata["ce_depth_two_memory_log2"] == expected_memory
    assert len(calls) == (2 if profile is not None else 1)
    assert len({id(child) for child in calls}) == len(calls)
    if k == 80:
        assert result.parameters["depth"] == 3
        assert "p2" not in result.metadata["ce_depth_two_parameters"]


def test_infeasible_depth_two_child_does_not_publish_a_seed():
    attack = replace(instance(targets=1), tags=())
    result, = estimate(attack, options=options()).results
    assert result.status == "computed" and result.parameters["depth"] == 3
    assert "ce_depth_two_parameters" not in result.metadata
