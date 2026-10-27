"""Fixed-point reuse and strict applicability for the generic adapter."""
from dataclasses import replace
import json
from math import comb, fsum, log, log2, log1p

import pytest

from codebased_estimator import AttackInstance, Options, Problem, estimate
from codebased_estimator.matrix_costs import MATRIX_PROFILES, matrix_budget
from codebased_estimator.qprange import evaluate_qprange
from codebased_estimator.quantum_costs import evaluate_parameters


def attack(**changes):
    original = AttackInstance("generic QPrange", "msg_recovery",
                              Problem("sd", {"n": 12, "k": 6, "w": 4}, 0))
    return replace(original, **changes)


def result(instance, profile=MATRIX_PROFILES[0], **changes):
    return estimate(instance, options=Options(classical_algorithms=(),
        quantum_algorithms=("QPrange",), quantum_matrix_profile=profile, **changes)).results[0]


@pytest.mark.parametrize("n,k,w", [(4, 3, 1), (12, 6, 4), (15, 9, 3), (40, 20, 20)])
@pytest.mark.parametrize("profile", MATRIX_PROFILES)
@pytest.mark.parametrize("solutions", [0, 2, 1024])
def test_fixed_point_exactly_reuses_existing_cost(n, k, w, profile, solutions):
    got = evaluate_qprange(n, k, w, matrix_profile=profile, log2_solutions=solutions)
    anchor = evaluate_parameters(n, k, w, "QSS", ell=0, p=0,
                                matrix_profile=profile, log2_solutions=solutions)
    assert got.time_log2 == anchor.time_log2
    assert all(got.details[key] == value for key, value in anchor.details.items())
    assert got.parameters["ell"] == got.parameters["p"] == 0
    assert got.search["attack_parameter_search"] is False
    assert got.matrix["profile"] == profile


@pytest.mark.parametrize("profile", MATRIX_PROFILES)
def test_independent_single_solution_formula(profile):
    n, k, w = 12, 6, 4
    m = n - k
    probability = comb(m, w) / comb(n, w)
    log_rho = (fsum(log1p(-2.0 ** -j) for j in range(1, m + 1))
               - fsum(log1p(-2.0 ** -j) for j in range(k + 1, n + 1))) / log(2)
    budget = matrix_budget(n, k, 0, profile)
    expected = log2(n * (m + 1) + n * (budget.total + 1) /
                    (probability * 2 ** log_rho) ** .5)
    got = evaluate_qprange(n, k, w, matrix_profile=profile)
    assert got.time_log2 == pytest.approx(expected, abs=1e-12)
    assert got.details["log2_rho"] == pytest.approx(log_rho, abs=1e-12)


@pytest.mark.parametrize("profile", MATRIX_PROFILES)
@pytest.mark.parametrize("solutions", [None, 0, 2])
def test_public_and_qcsd_fallback_keep_direct_point(profile, solutions, monkeypatch):
    monkeypatch.setattr("codebased_estimator.quantum.optimize",
                        lambda *a, **k: pytest.fail("fixed point must not optimize"))
    plain = attack(problem=Problem("sd", {"n": 12, "k": 6, "w": 4}, solutions))
    row = result(plain, profile, memory_bound_log2_bits=0)
    fallback = result(replace(plain, targets=32, tags=("doom:qcsd",)), profile,
                      memory_bound_log2_bits=0)
    assert row.status == fallback.status == "computed"
    assert row.time_log2 == fallback.time_log2
    assert row.parameters == fallback.parameters
    assert fallback.metadata["effective_targets"] == 1
    assert fallback.metadata["doom"]["applied"] is False
    assert row.memory_log2 is None and row.memory_unit == "not_estimated"
    assert row.metadata["memory_bound_applied"] is False
    json.dumps(row.__dict__, allow_nan=False)


@pytest.mark.parametrize("changes", [
    {"targets": 2}, {"tags": ("unknown",)}, {"structure": ("truncated",)},
    {"problem": Problem("cfp", {"n": 12, "k": 6, "w": 4}),
     "targets": 8, "tags": ("doom:qccf",)},
    {"problem": Problem("sd", {"n": 12, "k": 6, "w": 4, "q": 3}, 0)},
])
def test_unsupported_contexts_do_not_reach_direct_evaluator(changes, monkeypatch):
    monkeypatch.setattr("codebased_estimator.qprange.evaluate_qprange",
                        lambda *a, **k: pytest.fail("unsupported context reached direct point"))
    row = result(attack(**changes))
    assert row.status in ("not_implemented", "not_applicable")
    assert row.time_log2 is None


@pytest.mark.parametrize("arguments", [(True, 1, 1), (8.0, 4, 1), (8, 8, 1), (8, 4, 5)])
def test_invalid_problem_rejected(arguments):
    with pytest.raises(ValueError):
        evaluate_qprange(*arguments)


@pytest.mark.parametrize("bad", [True, -1, float("nan"), float("inf")])
def test_invalid_solutions_rejected(bad):
    with pytest.raises(ValueError):
        evaluate_qprange(12, 6, 4, log2_solutions=bad)
