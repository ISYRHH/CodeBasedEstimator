"""Independent MAGE-Stern results and comparison through the shared report."""

import csv
from dataclasses import replace
import io
import json
import sys
from types import SimpleNamespace

import pytest

from codebased_estimator import AttackInstance, Options, Problem, estimate
from codebased_estimator.__main__ import _csv_results, main


def attack(**changes):
    return replace(AttackInstance(
        "MAGE integration", "msg_recovery",
        Problem("sd", {"n": 40, "k": 20, "w": 4}, 0),
    ), **changes)


def mage_options(**changes):
    return Options(classical_algorithms=("MAGE-Stern",), quantum_algorithms=(), **changes)


@pytest.fixture
def native_search(monkeypatch):
    """Isolate dispatch from the separately tested, expensive parameter search."""
    state = SimpleNamespace(
        calls=[],
        cost=SimpleNamespace(
            time_log2=10.0, memory_log2=12.0,
            parameters={"ell": 4, "p": 1, "delta": 1, "blocks": [10, 10],
                        "repetitions": [1, 2, 1], "targets_used": 1},
            details={"log2_success_probability": -5.0},
            search={"method": "integration fixture", "global_optimum": False},
        ),
    )

    def optimize(*args, **kwargs):
        state.calls.append((args, kwargs))
        return state.cost

    monkeypatch.setitem(sys.modules, "codebased_estimator.mage_search", SimpleNamespace(optimize=optimize))
    return state


@pytest.mark.parametrize("instance", [
    attack(problem=Problem("sd", {"n": 40, "k": 20, "w": 4, "q": 3}, 0)),
    attack(problem=Problem("sd", {"n": 40, "k": 20, "w": 4}, 1)),
    attack(problem=Problem("rank_sd", {"q": 2, "m": 8, "n": 8, "k": 4, "r": 2})),
    attack(problem=Problem("qccf", {"n": 40, "k": 20, "w": 4}), tags=("doom:qccf",)),
    attack(problem=Problem("other", {})),
    attack(problem=Problem("qcsd", {"n": 40, "k": 50, "w": 4})),
    attack(structure=("regular",)),
    attack(tags=("unmodeled",)),
    attack(targets=8),
])
def test_explicit_known_algorithm_reports_unsupported_scope(instance, native_search):
    row, = estimate(instance, options=mage_options()).results
    assert row.algorithm == "MAGE-Stern"
    assert row.status == "not_implemented" and row.reason
    assert row.time_log2 is None and row.memory_log2 is None
    assert not native_search.calls


def test_unknown_algorithm_still_raises():
    with pytest.raises(ValueError, match="Unknown"):
        estimate(attack(), options=Options(classical_algorithms=("MAGE-Unknown",), quantum_algorithms=()))


def test_binary_defaults_include_mage_and_use_the_shared_comparison(native_search):
    report = estimate(attack(), options=Options(quantum_algorithms=()))
    assert "Stern" in {row.algorithm for row in report.results}
    mage, = [row for row in report.results if row.algorithm == "MAGE-Stern"]
    assert mage.status == "computed" and mage.time_log2 == native_search.cost.time_log2
    assert native_search.calls
    assert report.conclusions["classical"].best == (mage,)


def test_binary_qcsd_alias_defaults_to_its_local_candidate(native_search):
    instance = attack(problem=Problem("qcsd", {"n": 40, "k": 20, "w": 4}, 0),
                      tags=("doom:qcsd",), targets=8)
    row, = estimate(instance, options=Options(quantum_algorithms=())).results
    assert row.algorithm == "MAGE-Stern" and row.status == "computed"
    assert native_search.calls[0][1]["targets"] == 8


@pytest.mark.parametrize("problem", [
    Problem("sd", {"n": 40, "k": 20, "w": 4, "q": 3}, 0),
    Problem("rank_sd", {"q": 2, "m": 8, "n": 8, "k": 4, "r": 2}),
])
def test_other_problem_family_defaults_do_not_include_mage(problem, native_search):
    report = estimate(attack(problem=problem), options=Options(quantum_algorithms=()))
    assert report.results and "MAGE-Stern" not in {row.algorithm for row in report.results}
    assert not native_search.calls


def test_qcsd_native_cost_reaches_report_without_target_discount(native_search):
    instance = attack(tags=("doom:qcsd",), targets=32)
    native_search.cost.parameters["targets_used"] = 8
    report = estimate(instance, options=mage_options(memory_bound_log2_bits=16))
    row, = report.results
    assert native_search.calls == [((40, 20, 4), {
        "algorithm": "MAGE-Stern", "targets": 32, "memory_bound_log2_bits": 16,
    })]
    assert row.status == "computed" and row.time_log2 == 10.0
    assert row.memory_log2 == 12.0
    assert row.time_unit == "bit_operations" and row.memory_unit == "bits"
    assert row.parameters["strategy"] == "multilevel"
    assert row.metadata["selected_strategy"] == "multilevel"
    assert row.metadata["cost_model"] == "ce-mage-generator-v2"
    assert row.metadata["target_success_model"] == "independent-target-tree-union-v1"
    assert row.metadata["doom"]["active_targets"] == 8
    assert row.metadata["doom"]["available_targets"] == 32
    assert row.metadata["doom"]["postprocessing_speedup_applied"] is False
    assert row.metadata["search"] == native_search.cost.search
    assert row.metadata["cost_breakdown"] == native_search.cost.details
    assert "strategy_comparison" not in row.metadata
    json.dumps(report.to_dict(), allow_nan=False)


@pytest.mark.parametrize("kind", ["sd", "qcsd"])
def test_valid_qcsd_kind_and_sd_alias_share_native_dispatch(kind, native_search):
    instance = attack(problem=Problem(kind, {"n": 40, "k": 20, "w": 4}, 0),
                      tags=("doom:qcsd",), targets=4)
    row, = estimate(instance, options=mage_options()).results
    assert row.status == "computed"
    assert native_search.calls[0][0] == (40, 20, 4)
    assert native_search.calls[0][1]["targets"] == 4


def test_none_solution_count_keeps_ce_semantics(native_search):
    instance = attack(problem=Problem("sd", {"n": 40, "k": 20, "w": 10}))
    row, = estimate(instance, options=mage_options()).results
    assert row.status == "not_implemented"
    assert "log2_solutions=0" in row.reason
    assert not native_search.calls
    instance = attack(problem=Problem("sd", {"n": 40, "k": 20, "w": 4}))
    row, = estimate(instance, options=mage_options()).results
    assert row.status == "computed"
    assert row.metadata["effective_log2_solutions"] == 0
    assert "CE default" in row.metadata["solution_count_policy"]


@pytest.mark.parametrize("native_time,targets", [(10.0, 1), (100.0, 8)])
def test_report_compares_independent_stern_and_mage_results(targets, native_time, native_search):
    native_search.cost.time_log2 = native_time
    instance = attack(tags=("doom:qcsd",) if targets > 1 else (), targets=targets)
    report = estimate(instance, options=Options(classical_algorithms=("Stern", "MAGE-Stern"), quantum_algorithms=()))
    stern, mage = report.results
    assert stern.status == mage.status == "computed"
    assert (mage.time_log2, mage.memory_log2) == (native_time, native_search.cost.memory_log2)
    assert mage.parameters == {**native_search.cost.parameters, "strategy": "multilevel"}
    assert mage.metadata["selected_strategy"] == "multilevel"
    assert mage.metadata["cost_breakdown"] == native_search.cost.details
    assert mage.metadata["search"] == native_search.cost.search
    assert "strategy_comparison" not in mage.metadata
    if targets > 1:
        assert mage.metadata["doom"]["model"] == "mage_stern_branching"
        assert mage.metadata["doom"] != stern.metadata["doom"]
    expected = stern if stern.time_log2 < native_time else mage
    assert report.conclusions["classical"].best == (expected,)


@pytest.mark.parametrize("algorithms", [("MAGE-Stern",), ("Stern", "MAGE-Stern")])
def test_empty_native_search_is_infeasible_without_borrowing_stern(algorithms, native_search):
    native_search.cost = None
    report = estimate(attack(), options=Options(classical_algorithms=algorithms, quantum_algorithms=()))
    mage = report.results[-1]
    assert mage.status == "infeasible" and mage.reason
    assert mage.time_log2 is None and mage.memory_log2 is None
    assert mage.metadata["selected_strategy"] is None
    assert "strategy_comparison" not in mage.metadata
    if "Stern" in algorithms:
        stern = report.results[0]
        assert stern.status == "computed"
        assert report.conclusions["classical"].best == (stern,)
    else:
        assert not report.conclusions["classical"].best
    json.dumps(report.to_dict(), allow_nan=False)


@pytest.mark.parametrize("solutions,targets", [(None, 1), (0, 8)])
def test_requesting_only_mage_never_estimates_stern(solutions, targets, native_search, monkeypatch):
    from cryptographic_estimators.SDEstimator import Stern
    from codebased_estimator.backend import ClassicalModel

    dispatched = []
    original = ClassicalModel.estimate_algorithm

    def record_dispatch(self, name, instance, options):
        dispatched.append(name)
        assert name == "MAGE-Stern", "MAGE must not invoke another algorithm as a hidden fallback"
        return original(self, name, instance, options)

    def reject_stern_cost(*args, **kwargs):
        pytest.fail("Requesting only MAGE-Stern must not run the CE Stern estimator")

    monkeypatch.setattr(ClassicalModel, "estimate_algorithm", record_dispatch)
    monkeypatch.setattr(Stern, "time_complexity", reject_stern_cost)
    instance = attack(problem=Problem("sd", {"n": 40, "k": 20, "w": 4}, solutions),
                      tags=("doom:qcsd",) if targets > 1 else (), targets=targets)
    native_search.cost.time_log2 = 100.0
    row, = estimate(instance, options=mage_options()).results
    assert dispatched == ["MAGE-Stern"]
    assert row.status == "computed" and row.time_log2 == 100.0


def test_native_single_level_degeneration_is_reported_as_its_own_result(native_search):
    native_search.cost.parameters.update(blocks=[20], repetitions=[1, 1])
    native_search.cost.time_log2 = 100.0
    report = estimate(attack(), options=mage_options())
    row, = report.results
    assert row.status == "computed" and row.time_log2 == 100.0
    assert row.parameters == {**native_search.cost.parameters, "strategy": "single_level"}
    assert row.metadata["selected_strategy"] == "single_level"
    assert row.metadata["cost_breakdown"] == native_search.cost.details
    assert row.metadata["search"] == native_search.cost.search
    assert "strategy_comparison" not in row.metadata
    assert report.conclusions["classical"].best == (row,)


def test_native_cost_over_memory_bound_is_excluded_from_comparison(native_search):
    report = estimate(attack(), options=mage_options(memory_bound_log2_bits=11))
    row, = report.results
    assert row.status == "infeasible" and row.reason
    assert row.time_log2 == native_search.cost.time_log2
    assert row.memory_log2 == native_search.cost.memory_log2 > 11
    assert native_search.calls[0][1]["memory_bound_log2_bits"] == 11
    assert not report.conclusions["classical"].best
    json.dumps(report.to_dict(), allow_nan=False)


def test_cli_json_and_csv_expose_local_algorithm_and_cost_model(tmp_path, capsys, native_search):
    path = tmp_path / "attack.json"
    path.write_text(json.dumps({
        "name": "CLI MAGE", "goal": "msg_recovery",
        "problem": {"kind": "sd", "parameters": {"n": 40, "k": 20, "w": 4}, "log2_solutions": 0},
    }))
    assert main(["estimate", str(path), "--classical-algorithms", "Stern", "MAGE-Stern",
                 "--quantum-algorithms", "--json"]) == 0
    record, = json.loads(capsys.readouterr().out)
    assert [row["algorithm"] for row in record["results"]] == ["Stern", "MAGE-Stern"]
    assert record["conclusions"]["classical"]["best"][0]["algorithm"] == "MAGE-Stern"
    report = estimate(attack(), options=mage_options())
    _csv_results([report])
    row, = csv.DictReader(io.StringIO(capsys.readouterr().out))
    assert row["algorithm"] == "MAGE-Stern"
    assert row["cost_model"] == "ce-mage-generator-v2"
    assert row["time_unit"] == "bit_operations" and row["memory_unit"] == "bits"
