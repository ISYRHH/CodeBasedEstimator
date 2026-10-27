"""Disclosures describe the selected quantum branch and its actual assumptions."""

from math import log2

import pytest

from codebased_estimator import AttackInstance, Options, Problem, estimate
from codebased_estimator.assumptions import BLOCK_OUTER, BLOCK_SOLUTIONS
from codebased_estimator.matrix_costs import DEFAULT_MATRIX_PROFILE, M4RI_MATRIX_PROFILE
from codebased_estimator.quantum_costs import evaluate_parameters
from codebased_estimator.unbalanced import BlockProfile


def attack(*, solutions=0, codewords=None, block=False, n=24, k=12, w=4):
    return AttackInstance(
        "assumption check", "key_recovery" if codewords is not None else "msg_recovery",
        Problem("cfp" if codewords is not None else "sd", dict(n=n, k=k, w=w, q=2),
                None if codewords is not None else solutions),
        targets=codewords if codewords is not None else 1,
        tags=("doom:qccf",) if codewords is not None else (),
        block_profile=BlockProfile((12, 12), (2, 2)) if block else None,
    )


def fixed_result(monkeypatch, instance, *, algorithm="QSS", profile=DEFAULT_MATRIX_PROFILE,
                 **parameters):
    p = instance.problem.parameters
    codeword_finding = "doom:qccf" in instance.tags
    point = evaluate_parameters(
        p["n"], p["k"], p["w"], algorithm, matrix_profile=profile,
        log2_solutions=log2(instance.targets) if codeword_finding else instance.problem.log2_solutions or 0,
        codeword_finding=codeword_finding, block_profile=instance.block_profile, **parameters,
    )
    assert point is not None
    monkeypatch.setattr("codebased_estimator.quantum.optimize", lambda *args, **kwargs: point)
    result, = estimate(instance, options=Options(
        classical_algorithms=(), quantum_algorithms=(algorithm,), quantum_matrix_profile=profile,
    )).results
    assert result.time_log2 == point.time_log2
    assert result.parameters == point.parameters
    assert result.metadata["cost_breakdown"] == point.details
    return result


@pytest.mark.parametrize("algorithm,parameters,branch,survival", [
    ("QSS", dict(ell=0, p=0), "direct", False),
    ("QMMT+", dict(ell=0, p=0), "direct", False),
    ("QSS", dict(ell=4, p=4, u=1), "walk", False),
    ("QMMT+", dict(ell=4, p=4, u=1), "walk", False),
    ("QMMT+", dict(ell=4, p=4, u=1, b=1), "walk", True),
    ("QSS", dict(ell=4, p=4, u=4), "full_list", False),
    ("QMMT+", dict(ell=4, p=4, u=8, b=1), "full_list", True),
])
def test_list_and_survival_disclosures_follow_the_selected_branch(
        monkeypatch, algorithm, parameters, branch, survival):
    result = fixed_result(monkeypatch, attack(), algorithm=algorithm, **parameters)
    assert result.parameters["branch"] == branch
    text = " ".join(result.assumptions).lower()
    assert "random-code" in text and "coherent" in text
    assert ("ordered-list" in text) is (branch != "direct")
    assert ("average-load" in text) is (branch != "direct")
    assert ("representation survival" in text) is survival
    assert "independent" not in text
    assert BLOCK_OUTER.lower() not in text
    assert "self-collision" not in text


@pytest.mark.parametrize("solutions", [None, 0, 2])
@pytest.mark.parametrize("parameters", [dict(ell=0, p=0), dict(ell=4, p=4, u=1)])
def test_block_conditions_and_common_rank_apply_to_direct_and_list_models(monkeypatch, solutions, parameters):
    result = fixed_result(monkeypatch, attack(solutions=solutions, block=True), **parameters)
    text = " ".join(result.assumptions).lower()
    multiple = bool(solutions)
    assert "unstructured" not in text
    assert BLOCK_OUTER in result.assumptions and BLOCK_SOLUTIONS in result.assumptions
    assert ("independent" in text) is multiple
    assert ("common rank" in text) is multiple
    assert result.metadata["effective_log2_solutions"] == (solutions or 0)


@pytest.mark.parametrize("targets", [1, 8])
def test_qccf_discloses_independent_codewords_only_when_more_than_one_is_counted(monkeypatch, targets):
    result = fixed_result(monkeypatch, attack(codewords=targets, block=True), ell=4, p=4, u=1)
    text = " ".join(result.assumptions).lower()
    assert "zero-syndrome" in text and "self-collision" in text
    assert ("independent" in text) is (targets > 1)
    assert ("common rank" in text) is (targets > 1)
    assert BLOCK_SOLUTIONS in result.assumptions
    assert result.metadata["codeword_finding"] is True
    assert result.metadata["effective_log2_solutions"] == log2(targets)


@pytest.mark.parametrize("n,k,w,ell,p,has_tables", [
    (4, 2, 1, 0, 0, False), (24, 12, 4, 4, 4, True),
])
def test_m4ri_lookup_assumption_requires_an_actual_table(monkeypatch, n, k, w, ell, p, has_tables):
    instance = attack(n=n, k=k, w=w)
    ordinary = fixed_result(monkeypatch, instance, ell=ell, p=p)
    assert not any("M4RI" in item or "pivot" in item for item in ordinary.assumptions)
    result = fixed_result(monkeypatch, instance, profile=M4RI_MATRIX_PROFILE, ell=ell, p=p)
    assert bool(result.metadata["matrix"]["block_size"]) is has_tables
    text = " ".join(result.assumptions).lower()
    assert ("row-table lookup" in text) is has_tables
    assert ("cleanup" in text) is has_tables
    assert "coherent" in text


def test_combined_model_retains_shared_conditions_as_separate_entries(monkeypatch):
    result = fixed_result(monkeypatch, attack(codewords=8, block=True), algorithm="QMMT+",
                          profile=M4RI_MATRIX_PROFILE, ell=4, p=4, u=1, b=1)
    text = " ".join(result.assumptions).lower()
    assert all(term in text for term in ("random-code", "coherent", "average-load",
                                        "representation survival", "common rank", "independent",
                                        "zero-syndrome", "self-collision", "row-table lookup"))
    assert BLOCK_OUTER in result.assumptions and BLOCK_SOLUTIONS in result.assumptions


def test_failed_search_does_not_claim_a_selected_list_or_matrix_strategy(monkeypatch):
    monkeypatch.setattr("codebased_estimator.quantum.optimize", lambda *args, **kwargs: None)
    result, = estimate(attack(), options=Options(classical_algorithms=(), quantum_algorithms=("QSS",),
                      quantum_matrix_profile=M4RI_MATRIX_PROFILE)).results
    assert result.status == "infeasible"
    text = " ".join(result.assumptions).lower()
    assert "ordered-list" not in text
    assert "representation survival" not in text
    assert "row-table lookup" not in text
