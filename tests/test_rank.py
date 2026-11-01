"""Rank adapter wiring and report contracts, without checking algorithm formulas."""

from dataclasses import asdict, replace
import json

import pytest

from codebased_estimator import AttackInstance, Options, Problem, estimate
from codebased_estimator import rank
from codebased_estimator.models import Report


def generic_instance():
    return AttackInstance("rank test", "key_recovery", Problem(
        "rank_sd", {"q": 2, "m": 8, "n": 8, "k": 4, "r": 2}))


def test_catalogue_routes_and_json_replay():
    catalogue = rank.rank_catalogue()
    assert len(catalogue) == 17
    instances = rank.rank_instances()
    assert len(instances) == 34
    assert {row.scheme for row in instances} == set(rank.RANK_SCHEMES)
    for instance in instances:
        replay = AttackInstance.from_dict(json.loads(json.dumps(asdict(instance))))
        assert replay == instance
        assert rank.RankModel.applicability("Rank-OJ", replay) is None
        assert rank.rank_algorithms(instance, "quantum") == ()
    catalogue[0]["parameters"]["m"] = 0
    assert rank.rank_catalogue()[0]["parameters"]["m"] > 0


@pytest.mark.parametrize("kwargs", [
    {"schemes": []}, {"schemes": ["unknown"]}, {"parameter_sets": []},
    {"schemes": ["BRA"], "parameter_sets": ["BRQC-128"]}, {"goal": "unknown"},
])
def test_invalid_catalogue_selection(kwargs):
    with pytest.raises(ValueError):
        rank.rank_instances(**kwargs)


def test_scheme_selected_algorithm_and_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(rank.specialized, "loong_oj", lambda *args: calls.append(args) or 12.5)
    monkeypatch.setattr(rank.specialized, "loong_mm", lambda *args: pytest.fail("Unselected MM ran"))
    instance = rank.rank_instances(schemes=["BAG-Loong"], parameter_sets=["BAG-Loong-128"],
                                   goal="msg_recovery")[0]
    report = estimate(instance, options=Options(classical_algorithms=("Rank-OJ",), quantum_algorithms=()))
    assert calls == [(42, 10, 5, 5, 3, 47, 2, 2.8)]
    assert [row.algorithm for row in report.results] == ["Rank-OJ"]
    assert report.results[0].time_log2 == 12.5
    assert report.results[0].is_time_only
    assert report.conclusions["classical"].status == "computed"
    assert report.conclusions["quantum"].status == "not_requested"
    json.dumps(report.to_dict(), allow_nan=False)
    bounded = replace(report, options=replace(report.options, memory_bound_log2_bits=100))
    assert bounded.conclusions["classical"].status == "unavailable"


def test_generic_local_dispatch_preserves_source_fields(monkeypatch):
    calls = []

    def fake_be(parameters):
        calls.append(parameters)
        return rank.generic.Estimate("source attack", "combinatorial", log2_bits=12.5,
                                     bits=12, log2_ops=10, optimal={"a": 3}, source="source", notes="note")

    monkeypatch.setitem(rank._GENERIC, "Rank-BE", fake_be)
    report = estimate(generic_instance(), options=Options(
        classical_algorithms=("Rank-BE",), quantum_algorithms=()))
    assert len(calls) == 1
    assert calls[0] == rank.generic.Params(q=2, m=8, n=8, k=4, r=2)
    result, = report.results
    assert result.algorithm == "Rank-BE"
    assert result.time_log2 == 12.5
    assert result.parameters == {"a": 3}
    assert result.references == ("source",)
    assert result.metadata["reported_bits"] == 12
    assert result.reason == "note"


def test_quantum_dispatch(monkeypatch):
    monkeypatch.setattr(rank.generic, "wt23_quantum_grs", lambda p: rank.generic.Estimate(
        "WT23", "quantum", log2_bits=9, log2_ops=9))
    report = estimate(generic_instance(), options=Options(
        classical_algorithms=(), quantum_algorithms=("Rank-WT23",)))
    result, = report.results
    assert result.algorithm == "Rank-WT23"
    assert result.model == "quantum"
    assert result.time_unit == "quantum_bit_operations"
    assert result.is_time_only_quantum
    assert report.conclusions["quantum"].status == "computed"


def test_generic_invalid_field_is_unavailable_for_local_algorithms():
    instance = replace(generic_instance(), problem=Problem(
        "rank_sd", {"q": 6, "m": 8, "n": 8, "k": 4, "r": 2}))
    for name in ("Rank-BE", "Rank-WT23"):
        assert "prime power" in rank.RankModel.applicability(name, instance)
        assert rank.RankModel().estimate_algorithm(name, instance, Options()).status == "not_implemented"


@pytest.mark.parametrize("field,value", [("t1", 5.0), ("instance", True)])
def test_replayed_scheme_rejects_wrong_parameter_types(monkeypatch, field, value):
    instance = rank.rank_instances(parameter_sets=["BAG-Loong-128"], goal="key_recovery")[0]
    changed = replace(instance, problem=Problem("rank_scheme", {
        **instance.problem.parameters, field: value}))
    monkeypatch.setattr(rank, "_scheme_cost", lambda *args: pytest.fail("Invalid input computed"))
    assert rank.RankModel().estimate_algorithm("Rank-PRR", changed, Options()).status == "not_implemented"


@pytest.mark.parametrize("change", [
    {"targets": 2}, {"tags": ("extra",)}, {"structure": ("extra",)},
    {"parameter_set": "missing"},
    {"problem": Problem("rank_scheme", {"m": 1})},
])
def test_unsupported_scheme_input_does_not_compute(monkeypatch, change):
    instance = rank.rank_instances(schemes=["BRA"], goal="key_recovery")[0]
    monkeypatch.setattr(rank, "_scheme_cost", lambda *args: pytest.fail("Unsupported input computed"))
    result = rank.RankModel().estimate_algorithm("Rank-OJ", replace(instance, **change), Options())
    assert result.status == "not_implemented"
    assert result.time_log2 is None


@pytest.mark.parametrize("cost", [None, float("inf"), float("nan")])
def test_nonfinite_script_outputs_are_json_safe(monkeypatch, cost):
    monkeypatch.setattr(rank, "_scheme_cost", lambda *args: (cost, {}))
    instance = rank.rank_instances(schemes=["BRA"], goal="key_recovery")[0]
    options = Options(classical_algorithms=("Rank-MM",), quantum_algorithms=())
    rows = rank.RankModel().estimate(instance, options)
    assert rows[0].status == "not_applicable"
    assert rows[0].time_log2 is None
    json.dumps(Report(instance, options, {}, rows).to_dict(), allow_nan=False)


@pytest.mark.parametrize("scheme,goal,algorithm,function,output", [
    ("BAG-Loong", "key_recovery", "Rank-PRR", "loong_prr", 100),
    ("BAG-Loong", "key_recovery", "Rank-MM", "loong_mm", 100),
    ("BAG-Piglet", "key_recovery", "Rank-OJ", "piglet_oj_31", 100),
    ("BAG-Piglet", "msg_recovery", "Rank-OJ", "piglet_oj_42", 100),
    ("BAG-Piglet", "key_recovery", "Rank-MM", "piglet_mm_31", 100),
    ("BAG-Piglet", "msg_recovery", "Rank-MM", "piglet_mm_42", 100),
    ("BAG-Piglet", "msg_recovery", "Rank-PRR", "piglet_prr", 100),
    ("BRA", "key_recovery", "Rank-MM", "bra_mm_at", (100, 12, 10)),
    ("BRQC", "msg_recovery", "Rank-AGHT", "bra_aght", 100),
    ("BRQC", "key_recovery", "Rank-PRR", "bra_prr", 100),
    ("BRA", "msg_recovery", "Rank-OJ", "bra_oj_c", (100, 3)),
    ("C-Multi-UR-AG", "key_recovery", "Rank-MM", "cmulti_mm", (100, 3)),
    ("C-Multi-UR-AG", "msg_recovery", "Rank-SM", "cmulti_sm_best", (100, 1, 2, 3)),
    ("C-Multi-UR-AG", "key_recovery", "Rank-AGHT", "bra_aght", 100),
    ("C-Multi-UR-AG", "msg_recovery", "Rank-OJ", "bra_oj_c", (100, 3)),
    ("C-Multi-UR-AG", "key_recovery", "Rank-RSL-AGHT", "bra_aght", 100),
    ("C-Multi-UR-AG", "msg_recovery", "Rank-RSL-OJ", "bra_oj_c", (100, 3)),
])
def test_scheme_branches_call_selected_script(monkeypatch, scheme, goal, algorithm, function, output):
    calls = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return output

    monkeypatch.setattr(rank.specialized, function, fake)
    instance = rank.rank_instances(schemes=[scheme], goal=goal)[0]
    options = Options(classical_algorithms=(algorithm,), quantum_algorithms=())
    result, = rank.RankModel().estimate(instance, options)
    assert len(calls) == 1
    assert result.algorithm == algorithm
    assert result.status == "computed"
    assert result.is_time_only
    json.dumps(asdict(result), allow_nan=False)
