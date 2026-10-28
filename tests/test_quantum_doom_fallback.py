"""Unavailable QCSD acceleration retains the single-target algorithm's contract."""

import json
from dataclasses import replace

import pytest

from codebased_estimator import AttackInstance, Estimate, Options, Problem, estimate
from codebased_estimator.doom_fallback import single_target_fallback
from codebased_estimator.matrix_costs import MATRIX_PROFILES


def attack(solutions=0, targets=32, **changes):
    instance = AttackInstance(
        "QCSD fallback", "msg_recovery",
        Problem("sd", {"n": 12, "k": 6, "w": 2}, solutions),
        targets=targets, tags=("doom:qcsd",),
    )
    return replace(instance, **changes)


@pytest.mark.parametrize("algorithm", ["QSS", "QMMT+"])
@pytest.mark.parametrize("targets", [1, 1 << 100])
@pytest.mark.parametrize("solutions", [None, 0, 2])
@pytest.mark.parametrize("profile", MATRIX_PROFILES)
def test_qcsd_fallback_matches_single_target_cost_parameters_and_profile(
        algorithm, targets, solutions, profile):
    original = attack(solutions, targets)
    options = Options(classical_algorithms=(), quantum_algorithms=(algorithm,),
                      quantum_matrix_profile=profile, memory_bound_log2_bits=0)
    report = estimate(original, options=options)
    row, = report.results
    baseline, = estimate(replace(original, tags=(), targets=1), options=options).results
    assert report.instance == original
    assert row.status == "computed"
    assert replace(row, reason=baseline.reason, assumptions=baseline.assumptions,
                   metadata=baseline.metadata) == baseline
    assert set(baseline.assumptions).issubset(row.assumptions)
    for key, value in baseline.metadata.items():
        if key not in ("tags", "targets"):
            assert row.metadata[key] == value
    assert row.metadata["tags"] == ["doom:qcsd"]
    assert row.metadata["targets"] == targets
    assert row.metadata["effective_tags"] == []
    assert row.metadata["effective_targets"] == 1
    assert row.metadata["effective_log2_solutions"] == (solutions or 0)
    doom = row.metadata["doom"]
    assert doom["model"] == "single_target_fallback"
    assert doom["available_targets"] == targets
    assert doom["active_targets"] == 1 and doom["applied"] is False
    assert doom["fallback_reason"] in row.reason
    assert report.conclusions["quantum"].best == (row,)
    json.dumps(report.to_dict(), allow_nan=False)


@pytest.mark.parametrize("changes,status", [
    ({"tags": ("doom:qcsd", "unmodeled")}, "not_implemented"),
    ({"structure": ("block weights",)}, "not_implemented"),
    ({"problem": Problem("sd", {"n": 12, "k": 6, "w": 2, "q": 3}, 0)},
     "not_applicable"),
    ({"problem": Problem("qcsd", {"size": 12})}, "not_applicable"),
    ({"tags": (), "problem": Problem("rank_sd", {"q": 2, "m": 8, "n": 8, "k": 4, "r": 2})},
     "not_applicable"),
])
def test_fallback_does_not_discard_unsupported_problem_constraints(monkeypatch, changes, status):
    def forbidden(*args, **kwargs):
        pytest.fail("unsupported context must not reach the single-target optimizer")

    monkeypatch.setattr("codebased_estimator.quantum.optimize", forbidden)
    rows = estimate(attack(**changes), options=Options(
        classical_algorithms=(), quantum_algorithms=("QSS", "QMMT+"))).results
    for row in rows:
        assert row.status == status and row.time_log2 is None
        assert "doom" not in row.metadata
        assert "effective_tags" not in row.metadata


@pytest.mark.parametrize("algorithm", ["QSS", "QMMT+"])
def test_fallback_preserves_optimizer_failure(monkeypatch, algorithm):
    calls = []

    def infeasible(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    monkeypatch.setattr("codebased_estimator.quantum.optimize", infeasible)
    report = estimate(attack(solutions=2), options=Options(
        classical_algorithms=(), quantum_algorithms=(algorithm,)))
    row, = report.results
    assert calls == [((12, 6, 2, algorithm), {"log2_solutions": 2})]
    assert row.status == "infeasible" and row.time_log2 is None
    assert "searched parameter domain" in row.reason
    assert row.metadata["doom"]["applied"] is False
    assert report.conclusions["quantum"].status == "unavailable"


def test_qprange_single_target_fallback_uses_fixed_point_without_optimization(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("QPrange must use its fixed point, not the optimizer")

    monkeypatch.setattr("codebased_estimator.quantum.optimize", forbidden)
    report = estimate(attack(), options=Options(
        classical_algorithms=(), quantum_algorithms=("QPrange",)))
    row, = report.results
    assert row.status == "computed"
    assert row.time_log2 is not None and row.memory_log2 is None
    assert row.parameters["ell"] == row.parameters["p"] == 0
    assert row.metadata["doom"]["model"] == "single_target_fallback"
    assert report.conclusions["quantum"].status == "computed"


def test_custom_model_owns_its_unsupported_doom_result():
    received = []
    unavailable = Estimate("QSS", "quantum", "not_implemented", reason="custom model pending")

    class CustomModel:
        name = "custom"

        def estimate(self, instance, options):
            received.append(instance)
            return [unavailable]

    original = attack()
    report = estimate(original, quantum_model=CustomModel(), options=Options(
        classical_algorithms=(), quantum_algorithms=("QSS",)))
    assert received == [original]
    assert report.results == [unavailable]
    assert report.conclusions["quantum"].status == "unavailable"


@pytest.mark.parametrize("family", ["classical", "quantum"])
@pytest.mark.parametrize("status", ["computed", "infeasible", "not_implemented"])
def test_fallback_annotation_preserves_the_baseline_contract(family, status):
    baseline = Estimate("test algorithm", family, status,
                        time_log2=20 if status == "computed" else None,
                        memory_log2=10 if status == "computed" else None,
                        assumptions=("Four acceptable solutions per syndrome.",),
                        metadata={"effective_log2_solutions": 2})
    result = single_target_fallback(baseline, attack(solutions=2), "QCSD model unavailable.")
    assert replace(result, reason=baseline.reason, assumptions=baseline.assumptions,
                   metadata=baseline.metadata) == baseline
    assert result.assumptions[:-1] == baseline.assumptions
    assert result.metadata["effective_log2_solutions"] == 2
    assert result.metadata["effective_targets"] == 1
    assert result.metadata["doom"]["applied"] is False
    disclosure = result.assumptions[-1].lower()
    assert "syndrome" in disclosure and "doom" in disclosure
    assert "one solution" not in disclosure
