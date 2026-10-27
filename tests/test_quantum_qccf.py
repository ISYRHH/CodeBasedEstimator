"""Quantum solution counts reach optimization with complete route semantics."""

import json
from math import log2
from types import SimpleNamespace

import pytest

from codebased_estimator import AttackInstance, Options, Problem, estimate
from codebased_estimator.matrix_costs import DEFAULT_MATRIX_PROFILE, M4RI_MATRIX_PROFILE
from codebased_estimator.quantum_costs import OUTER_PROBABILITY_MODEL, optimize


def qccf_report(*, kind="cfp", targets=3, parameters=None, algorithm="QMMT+",
                tags=("doom:qccf",), structure=(), matrix_profile=DEFAULT_MATRIX_PROFILE):
    attack = AttackInstance(
        "quantum QCCF", "key_recovery",
        Problem(kind, {"n": 24, "k": 12, "w": 4} if parameters is None else parameters),
        targets=targets, tags=tags, structure=structure,
    )
    report = estimate(attack, options=Options(
        classical_algorithms=(), quantum_algorithms=(algorithm,),
        quantum_matrix_profile=matrix_profile,
    ))
    json.dumps(report.to_dict(), allow_nan=False)
    return report


@pytest.mark.parametrize("solutions", [0.5, 4])
@pytest.mark.parametrize("profile", [DEFAULT_MATRIX_PROFILE, M4RI_MATRIX_PROFILE])
def test_explicit_solution_count_is_passed_before_quantum_optimization(monkeypatch, solutions, profile):
    calls = []

    def capture(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(time_log2=23, parameters={"ell": 4, "p": 4},
                               details={}, search={})

    monkeypatch.setattr("codebased_estimator.quantum.optimize", capture)
    attack = AttackInstance("multiple solutions", "msg_recovery",
                            Problem("sd", {"n": 40, "k": 20, "w": 4}, solutions))
    report = estimate(attack, options=Options(
        classical_algorithms=(), quantum_algorithms=("QSS", "QMMT+"),
        quantum_matrix_profile=profile,
    ))
    kwargs = {"log2_solutions": solutions}
    if profile != DEFAULT_MATRIX_PROFILE:
        kwargs["matrix_profile"] = profile
    assert calls == [((40, 20, 4, name), kwargs) for name in ("QSS", "QMMT+")]
    for row in report.results:
        assert row.time_log2 == 23  # No final-result discount after optimization.
        assert row.metadata["effective_log2_solutions"] == solutions
        assert row.metadata["outer_probability_model"] == OUTER_PROBABILITY_MODEL
        assert row.metadata["codeword_finding"] is False
    assert report.instance == attack


@pytest.mark.parametrize("kind", ["cfp", "qccf"])
@pytest.mark.parametrize("targets", [1, 3])
@pytest.mark.parametrize("algorithm", ["QSS", "QMMT+"])
def test_qccf_matches_nonzero_core_proxy_and_retains_original_context(kind, targets, algorithm):
    report = qccf_report(kind=kind, targets=targets, algorithm=algorithm)
    row, = report.results
    direct = optimize(24, 12, 4, algorithm, log2_solutions=log2(targets), codeword_finding=True)
    assert direct is not None
    assert row.status == "computed"
    assert row.time_log2 == direct.time_log2
    assert row.parameters == direct.parameters
    assert row.parameters["p"] > 0
    assert row.metadata["cost_breakdown"] == direct.details
    assert row.metadata["effective_log2_solutions"] == log2(targets)
    assert row.metadata["codeword_finding"] is True
    assert row.metadata["tags"] == ["doom:qccf"]
    assert row.metadata["targets"] == targets
    doom = row.metadata["doom"]
    assert doom["source_problem_kind"] == kind
    assert doom["available_targets"] == targets
    assert doom["effective_log2_solutions"] == log2(targets)
    assert doom["postprocessing_speedup_applied"] is False
    assert doom["cost_model"] == OUTER_PROBABILITY_MODEL
    assert report.instance.problem.kind == kind
    assert report.instance.problem.parameters == {"n": 24, "k": 12, "w": 4}
    assert report.instance.problem.log2_solutions is None
    assert report.instance.targets == targets


@pytest.mark.parametrize("algorithm", ["QSS", "QMMT+"])
def test_qccf_cannot_fall_back_to_direct_zero_codeword(algorithm):
    row, = qccf_report(parameters={"n": 24, "k": 12, "w": 1},
                       algorithm=algorithm).results
    assert row.status == "infeasible"
    assert row.time_log2 is None
    assert row.metadata["codeword_finding"] is True


@pytest.mark.parametrize("overrides,status", [
    ({"algorithm": "QPrange"}, "not_implemented"),
    ({"tags": ()}, "not_applicable"),
    ({"tags": ("doom:qccf", "unmodeled")}, "not_implemented"),
    ({"structure": ("block weights",)}, "not_implemented"),
    ({"parameters": {"n": 24, "k": 12, "w": 4, "q": 3}}, "not_applicable"),
])
def test_qccf_does_not_discard_unsupported_context(monkeypatch, overrides, status):
    def unexpected(*args, **kwargs):
        pytest.fail("Unsupported QCCF context reached optimization")

    monkeypatch.setattr("codebased_estimator.quantum.optimize", unexpected)
    row, = qccf_report(**overrides).results
    assert row.status == status
    assert row.time_log2 is None and row.reason


@pytest.mark.parametrize("parameters", [
    {"n": 24},
    {"n": 24, "k": 12, "w": 4, "extra": 1},
    {"n": 24, "k": 24, "w": 4},
    {"n": 24, "k": 12, "w": 13},
    {"n": 24, "k": 12, "w": True},
])
def test_qccf_validates_decoding_parameters(parameters):
    with pytest.raises(ValueError):
        qccf_report(parameters=parameters)


def test_qccf_large_candidate_count_remains_finite_and_preserved():
    report = qccf_report(targets=1 << 1024)
    row, = report.results
    assert row.status == "computed"
    assert row.metadata["effective_log2_solutions"] == 1024
    assert row.metadata["doom"]["effective_log2_solutions"] == 1024
    assert report.instance.targets == 1 << 1024
    assert row.parameters["p"] > 0
