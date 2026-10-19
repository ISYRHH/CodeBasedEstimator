"""QCCF uses CE's solution count before each algorithm's optimization."""

import json
from math import inf, log2

import pytest

from cryptographic_estimators.SDEstimator import SDEstimator

from codebased_estimator import AttackInstance, Options, Problem, estimate


ALGORITHMS = {
    "BallCollision", "BJMMdw", "BJMMpdw", "BJMM", "BJMMplus", "BothMay",
    "Dumer", "MayOzerov", "Prange", "Stern",
}


def qccf_report(*, kind="cfp", targets=1, parameters=None, algorithms=None,
                memory_bound=None, tags=("doom:qccf",), structure=()):
    attack = AttackInstance(
        "QCCF test", "key_recovery",
        Problem(kind, {"n": 40, "k": 20, "w": 4} if parameters is None else parameters),
        targets=targets, tags=tags, structure=structure,
    )
    report = estimate(attack, options=Options(
        classical_algorithms=algorithms, quantum_algorithms=(),
        memory_bound_log2_bits=memory_bound,
    ))
    json.dumps(report.to_dict(), allow_nan=False)
    return report


def fresh_ce(*, n=40, k=20, w=4, solutions=0, bound=None):
    return {type(algorithm).__name__: algorithm for algorithm in SDEstimator(
        n=n, k=k, w=w, nsolutions=solutions,
        bit_complexities=1, complexity_type=0, memory_access=0,
        memory_bound=inf if bound is None else bound,
    ).algorithms()}


@pytest.mark.parametrize("kind", ("cfp", "qccf"))
@pytest.mark.parametrize("targets", (1, 3))
def test_default_ce_algorithms_keep_qccf_costs_and_mage_reports_unsupported(kind, targets):
    report = qccf_report(kind=kind, targets=targets)
    upstream = fresh_ce(solutions=log2(targets))
    assert set(upstream) == ALGORITHMS
    assert {row.algorithm for row in report.results} == ALGORITHMS | {"MAGE-Stern"}
    mage, = [row for row in report.results if row.algorithm == "MAGE-Stern"]
    assert mage.status == "not_implemented" and mage.reason
    assert mage.time_log2 is None and mage.memory_log2 is None
    assert mage not in report.conclusions["classical"].best
    for row in (row for row in report.results if row.algorithm in upstream):
        direct = upstream[row.algorithm]
        assert row.status == "computed"
        assert row.time_log2 == pytest.approx(direct.time_complexity(), abs=1e-10)
        assert row.memory_log2 == pytest.approx(direct.memory_complexity(), abs=1e-10)
        assert row.parameters == direct.get_optimal_parameters_dict()
        assert row.metadata["effective_log2_solutions"] == log2(targets)
        assert row.metadata["tags"] == ["doom:qccf"]
        doom = row.metadata["doom"]
        assert doom["model"] == "ce_nsolutions"
        assert doom["cost_model"] == "ce-qccf-nsolutions-v1"
        assert doom["available_targets"] == targets
        assert doom["effective_log2_solutions"] == log2(targets)
        assert "proxy" in " ".join(row.assumptions).lower()
    assert report.instance.problem.kind == kind
    assert report.instance.problem.parameters == {"n": 40, "k": 20, "w": 4}
    assert report.instance.problem.log2_solutions is None
    assert report.instance.tags == ("doom:qccf",)
    assert report.instance.targets == targets


def test_one_qccf_candidate_overrides_positive_expected_solution_default():
    parameters = {"n": 40, "k": 20, "w": 10}
    row, = qccf_report(parameters=parameters, algorithms=("Prange",)).results
    direct = fresh_ce(**parameters, solutions=0)["Prange"]
    expected_default = SDEstimator(**parameters).problem.nsolutions
    assert expected_default > 0
    assert row.metadata["effective_log2_solutions"] == 0
    assert row.time_log2 == pytest.approx(direct.time_complexity())
    assert row.time_log2 > fresh_ce(**parameters, solutions=expected_default)["Prange"].time_complexity()


def test_qccf_saturates_ce_permutations_instead_of_dividing_the_final_cost():
    ordinary, = qccf_report(targets=1, algorithms=("Prange",)).results
    saturated, = qccf_report(targets=32, algorithms=("Prange",)).results
    enormous, = qccf_report(targets=1 << 30, algorithms=("Prange",)).results
    assert saturated.time_log2 == enormous.time_log2
    assert saturated.time_log2 == pytest.approx(fresh_ce(solutions=5)["Prange"].time_complexity())
    assert enormous.time_log2 > ordinary.time_log2 - 30
    assert enormous.time_log2 > 0


def test_repeated_target_counts_optimize_fresh_objects_without_cache_contamination():
    rows = [qccf_report(targets=targets, algorithms=("Stern",)).results[0]
            for targets in (1, 16, 3, 1)]
    for row, targets in zip(rows, (1, 16, 3, 1)):
        direct = fresh_ce(solutions=log2(targets))["Stern"]
        assert row.time_log2 == pytest.approx(direct.time_complexity())
        assert row.parameters == direct.get_optimal_parameters_dict()
    assert rows[0].parameters == rows[-1].parameters
    assert rows[0].time_log2 == rows[-1].time_log2
    assert rows[0].parameters != rows[1].parameters


def test_qccf_passes_the_memory_bound_to_ce_before_optimization():
    row, = qccf_report(targets=8, algorithms=("Stern",), memory_bound=11).results
    direct = fresh_ce(solutions=3, bound=11)["Stern"]
    assert row.status == "computed"
    assert row.time_log2 == pytest.approx(direct.time_complexity())
    assert row.memory_log2 == pytest.approx(direct.memory_complexity())
    assert row.memory_log2 <= 11
    assert row.parameters == direct.get_optimal_parameters_dict()
    infeasible, = qccf_report(targets=8, algorithms=("Stern",), memory_bound=0).results
    assert infeasible.status in ("infeasible", "not_applicable")
    assert infeasible.reason


@pytest.mark.parametrize("options", [
    {"parameters": {"n": 40, "k": 20, "w": 4, "q": 3}},
    {"tags": ()},
    {"tags": ("doom:qccf", "unmodeled tag")},
    {"structure": ("block weights",)},
])
def test_qccf_does_not_discard_unmodeled_context(options):
    rows = qccf_report(targets=8, algorithms=("Prange", "Stern"), **options).results
    assert all(row.status == "not_implemented" for row in rows)
    assert all(row.time_log2 is None and row.memory_log2 is None and row.reason for row in rows)


@pytest.mark.parametrize("parameters", [
    {"n": 40},
    {"n": 40, "k": 20, "w": 4, "extra": 1},
    {"n": 40, "k": 40, "w": 4},
    {"n": 40, "k": 20, "w": 21},
    {"n": 40, "k": 20, "w": True},
])
def test_builtin_qccf_validates_decoding_parameters(parameters):
    with pytest.raises(ValueError):
        qccf_report(parameters=parameters, algorithms=("Prange",))


def test_qccf_rejects_an_additional_explicit_solution_count():
    with pytest.raises(ValueError, match="log2_solutions"):
        AttackInstance("double count", "key_recovery",
                       Problem("cfp", {"n": 40, "k": 20, "w": 4}, 0),
                       targets=8, tags=("doom:qccf",))


def test_qccf_preserves_counts_outside_the_upstream_numeric_range():
    report = qccf_report(targets=1 << 1024, algorithms=("Stern",))
    row, = report.results
    assert row.status == "not_implemented"
    assert "numeric range" in row.reason.lower()
    assert row.time_log2 is None and row.memory_log2 is None
    assert report.instance.targets == 1 << 1024
    assert row.metadata["effective_log2_solutions"] == 1024
    assert row.metadata["doom"]["effective_log2_solutions"] == 1024
