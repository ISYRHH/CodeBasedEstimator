"""Returned assumptions describe the selected classical model, not its competitors."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from codebased_estimator import AttackInstance, BlockProfile, Options, Problem, estimate
from codebased_estimator.assumptions import BLOCK_OUTER, BLOCK_SOLUTIONS, CLASSICAL_COST, SINGLE_SYNDROME
from codebased_estimator.backend import _with_bjmm_depth3_candidate
from codebased_estimator.models import Estimate


def attack(*, codewords=False, weights=(1, 2), targets=6, profile=True):
    return AttackInstance(
        "assumption audit", "key_recovery",
        Problem("cfp" if codewords else "sd", {"n": 20, "k": 10, "w": sum(weights)},
                None if codewords else 0),
        tags=("doom:qccf" if codewords else "doom:qcsd",), targets=targets,
        block_profile=BlockProfile((10, 10), weights, ((0, 1), (1, 0))) if profile else None,
    )


def row(instance, algorithm):
    return estimate(instance, options=Options(
        classical_algorithms=(algorithm,), quantum_algorithms=(),
    )).results[0]


def test_selected_ce_baseline_does_not_claim_explicit_doom_probability():
    instance = attack(targets=1, profile=False)
    ordinary = row(replace(instance, tags=()), "Prange")
    selected = row(instance, "Prange")
    assert selected.metadata["doom"]["strategy"] == "single_target_baseline"
    assert (selected.time_log2, selected.memory_log2, selected.parameters) == (
        ordinary.time_log2, ordinary.memory_log2, ordinary.parameters)
    assert set(ordinary.assumptions).issubset(selected.assumptions)
    assert CLASSICAL_COST in selected.assumptions
    assert SINGLE_SYNDROME in selected.assumptions
    assert "linear-union" not in " ".join(selected.assumptions)


@pytest.mark.parametrize("weights,targets,strategy", [
    ((0, 3), 6, "profile_single_target"),
    ((1, 2), 20, "profile_preserving_batch"),
    ((1, 2), 6, "generic_full_orbit"),
])
def test_profile_doom_assumptions_follow_the_winning_strategy(weights, targets, strategy):
    result = row(attack(weights=weights, targets=targets), "Prange")
    text = " ".join(result.assumptions)
    assert result.metadata["doom"]["strategy"] == strategy
    assert (BLOCK_OUTER in result.assumptions) == result.metadata["unbalanced"]["applied"]
    assert (BLOCK_SOLUTIONS in result.assumptions) == result.metadata["unbalanced"]["applied"]
    if strategy == "profile_single_target":
        assert result.metadata["doom"]["active_targets"] == 1
        assert SINGLE_SYNDROME in result.assumptions
        assert "linear-union" not in text
    else:
        assert result.metadata["doom"]["active_targets"] > 1
        assert "linear-union" in text
        assert SINGLE_SYNDROME not in result.assumptions


@pytest.mark.parametrize("weights,profile_used", [((0, 3), True), ((1, 2), False)])
def test_qccf_assumptions_keep_selected_codewords_distinct_from_syndromes(weights, profile_used):
    result = row(attack(codewords=True, weights=weights, targets=8), "Prange")
    text = " ".join(result.assumptions)
    assert result.metadata["unbalanced"]["applied"] is profile_used
    assert result.metadata["doom"]["active_codewords"] == (4 if profile_used else 8)
    assert "nonzero codewords" in text
    assert (BLOCK_OUTER in result.assumptions) is profile_used
    assert (BLOCK_SOLUTIONS in result.assumptions) is profile_used
    assert SINGLE_SYNDROME not in result.assumptions


def test_sqrt_target_winner_does_not_inherit_discarded_profile_assumptions():
    result = row(attack(targets=8), "BothMay")
    text = " ".join(result.assumptions)
    assert result.metadata["doom"]["model"] == "sqrt_targets_approximation"
    assert result.metadata["unbalanced"]["strategy"] == "generic_full_orbit"
    assert "sqrt(M)" in text
    assert BLOCK_OUTER not in result.assumptions
    assert BLOCK_SOLUTIONS not in result.assumptions
    assert SINGLE_SYNDROME not in result.assumptions


@pytest.mark.parametrize("codewords", [pytest.param(False, id="qcsd"), pytest.param(True, id="qccf")])
@pytest.mark.parametrize("profile_wins,inner_strategy", [
    pytest.param(False, "block_profile", id="uniform-full-orbit"),
    pytest.param(True, "block_profile", id="profile-quotas"),
    pytest.param(True, "uniform", id="profile-search-uniform-fallback"),
])
def test_mage_sampling_description_matches_selected_candidate(monkeypatch, codewords,
                                                              profile_wins, inner_strategy):
    # The winning search branch and its inner probability model are distinct:
    # a profile search may return the uniform first-block fallback.
    def fake_search(n, k, w, **options):
        profile_candidate = "block_profile" in options
        parameters = {"blocks": [k], "targets_used": options["targets"]}
        details = {"unbalanced": {"selected_strategy": inner_strategy}} if profile_candidate else {}
        if "codewords" in options:
            parameters["codewords"] = options["codewords"]
            details["codeword_sampling_model"] = (
                "block_profile_first_transition_proxy"
                if profile_candidate and inner_strategy == "block_profile" else "uniform_weight_support_proxy"
            )
        return SimpleNamespace(
            time_log2=8.0 if profile_candidate == profile_wins else 10.0,
            memory_log2=7.0, parameters=parameters, details=details, search={},
        )

    monkeypatch.setattr("codebased_estimator.mage_search.optimize", fake_search)
    result = row(attack(codewords=codewords, weights=(0, 3), targets=8), "MAGE-Stern")
    text = " ".join(result.assumptions)
    assert result.time_log2 == 8.0 and result.memory_log2 == 7.0
    assert (result.metadata["unbalanced"]["selected_strategy"] == "block_profile") is profile_wins
    if profile_wins:
        assert result.metadata["cost_breakdown"]["unbalanced"]["selected_strategy"] == inner_strategy
    profile_applied = profile_wins and inner_strategy == "block_profile"
    assert ("first-pivot allocation" in text) is profile_applied
    assert BLOCK_OUTER not in result.assumptions
    if codewords:
        assert ("conditioned on block weights" in text) is profile_applied
        assert ("uniform weight supports" in text) is not profile_applied
        assert result.metadata["doom"]["active_codewords"] == (4 if profile_wins else 8)
        assert result.metadata["effective_syndrome_targets"] == 1
        assert result.metadata["codeword_sampling_model"] == result.metadata["cost_breakdown"]["codeword_sampling_model"]
        assert result.metadata["codeword_sampling_model"] == (
            "block_profile_first_transition_proxy" if profile_applied else "uniform_weight_support_proxy")
    else:
        assert result.metadata["doom"]["active_targets"] == (4 if profile_wins else 8)
        assert result.metadata["effective_log2_solutions"] == 0


@pytest.mark.parametrize("codewords", [pytest.param(False, id="qcsd"), pytest.param(True, id="qccf")])
def test_mage_single_candidate_does_not_assert_multiple_candidate_independence(monkeypatch, codewords):
    monkeypatch.setattr("codebased_estimator.mage_search.optimize", lambda *args, **kwargs: SimpleNamespace(
        time_log2=8.0, memory_log2=7.0,
        parameters={"blocks": [10], "targets_used": 1, **({"codewords": 1} if codewords else {})},
        details={}, search={},
    ))
    result = row(attack(codewords=codewords, targets=8, profile=False), "MAGE-Stern")
    active = "active_codewords" if codewords else "active_targets"
    assert result.metadata["doom"][active] == 1
    assert not any("Whole-tree failures" in item for item in result.assumptions)


@pytest.mark.parametrize("codewords", [False, True])
def test_infeasible_mage_does_not_claim_a_strategy_was_selected(monkeypatch, codewords):
    monkeypatch.setattr("codebased_estimator.mage_search.optimize", lambda *args, **kwargs: None)
    result = row(attack(codewords=codewords, targets=8, profile=False), "MAGE-Stern")
    assert result.status == "infeasible"
    assert result.metadata["selected_strategy"] is None
    assert "selected" not in " ".join(result.assumptions).lower()


@pytest.mark.parametrize("profile_wins", [False, True])
def test_bjmm_depth_three_describes_only_selected_profile(monkeypatch, profile_wins):
    def fake_child(instance, options):
        profiled = instance.block_profile is not None
        return Estimate(
            "BJMM", "classical", "computed", 80.0 if profiled == profile_wins else 100.0,
            10.0, {"depth": 3}, metadata={"unbalanced": {"applied": profiled}},
        )

    monkeypatch.setattr("codebased_estimator.backend._ce_bjmm_depth3", fake_child)
    explicit = Estimate("BJMM", "classical", "computed", 120.0, 10.0,
                        metadata={"doom": {"strategy": "explicit_doom", "search": {},
                                           "baseline_time_log2": 120.0}})
    result = _with_bjmm_depth3_candidate(attack(targets=8), Options(), explicit)
    text = " ".join(result.assumptions)
    assert result.metadata["unbalanced"]["applied"] is profile_wins
    assert result.metadata["doom"]["active_targets"] == (4 if profile_wins else 8)
    assert (BLOCK_OUTER in result.assumptions) is profile_wins
    assert (BLOCK_SOLUTIONS in result.assumptions) is profile_wins
    assert "sqrt(M)" in text
    assert "linear-union" not in text
