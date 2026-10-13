"""Cross-route minima retain resource eligibility and replayable identities."""

import json
from dataclasses import replace

import pytest

from codebased_estimator import (
    AttackInstance, Estimate, Options, Problem, Report, RouteComparison,
    RouteConclusion, RouteEstimate, compare_routes,
)


def report(route_id, rows, *, options=None, scheme="HARE", parameter_set="level-1",
           goal="msg_recovery"):
    instance = AttackInstance(
        name=f"{parameter_set}/{goal}/{route_id}", goal=goal,
        problem=Problem("sd", {"n": 40, "k": 20, "w": 4}, 0),
        scheme=scheme, parameter_set=parameter_set,
        route=f"description for {route_id}", route_id=route_id,
    )
    return Report(instance, options or Options(), {}, rows)


def classical(time, memory=5, algorithm="Prange", **kwargs):
    return Estimate(algorithm, "classical", "computed", time, memory, **kwargs)


def quantum(time, **kwargs):
    return Estimate("QPrange", "quantum", "computed", time, None,
                    time_unit="quantum_bit_operations", memory_unit="not_estimated",
                    metadata={"resource_scope": "time_only"}, **kwargs)


def test_independent_family_winners_preserve_exact_ties_and_route_identity():
    first = report("u_only", [classical(20), quantum(10)])
    second = report("composite", [classical(19), classical(19, algorithm="Stern"), quantum(11)])
    third = report("third", [classical(19), classical(19 + 1e-10, algorithm="AlmostTie")])
    result, = compare_routes(iter([first, second, third]))
    assert isinstance(result, RouteComparison)
    assert result.routes == tuple(item.instance.name for item in [first, second, third])
    assert isinstance(result.conclusions["classical"], RouteConclusion)
    best = result.conclusions["classical"].best
    assert all(isinstance(item, RouteEstimate) for item in best)
    assert [item.name for item in best] == [second.instance.name, second.instance.name, third.instance.name]
    assert [item.estimate.algorithm for item in best] == ["Prange", "Stern", "Prange"]
    assert best[0].route == second.instance.route
    assert best[0].route_id == "composite"
    assert best[0].estimate is second.results[0]
    assert result.conclusions["quantum"].best[0].name == first.instance.name
    assert "limited to this evaluation" in result.conclusions["classical"].reason


def test_memory_constraints_and_unavailable_routes_do_not_win():
    options = Options(memory_bound_log2_bits=10)
    first = report("u_only", [classical(1, memory=11), classical(25, memory=10)], options=options)
    second = report("composite", [classical(20, memory=9)], options=options)
    invalid = report("invalid", [Estimate("Stern", "classical", "infeasible", 0, 0)], options=options)
    result, = compare_routes([first, second, invalid])
    assert result.conclusions["classical"].best[0].name == second.instance.name
    assert "2/3 eligible" in result.conclusions["classical"].reason
    assert result.conclusions["quantum"].status == "unavailable"


@pytest.mark.parametrize("within_route", [False, True])
def test_incomparable_time_units_block_only_affected_family(within_route):
    first_rows = [classical(20), quantum(9)]
    second_rows = [classical(10, time_unit="oracle_calls"), quantum(8)]
    if within_route:
        second_rows.append(classical(30))
    result, = compare_routes([report("u_only", first_rows), report("composite", second_rows)])
    assert result.conclusions["classical"].status == "incomparable_units"
    assert result.conclusions["classical"].best == ()
    assert result.conclusions["quantum"].best[0].route_id == "composite"


def test_ineligible_units_do_not_make_routes_incomparable():
    options = Options(memory_bound_log2_bits=10)
    first = report("u_only", [classical(20)], options=options)
    second = report("composite", [classical(1, memory=11, time_unit="oracle_calls"),
                                  classical(15)], options=options)
    result, = compare_routes([first, second])
    assert result.conclusions["classical"].status == "computed"
    assert result.conclusions["classical"].best[0].route_id == "composite"


def test_time_only_quantum_does_not_claim_memory_feasibility():
    options = Options(memory_bound_log2_bits=0, classical_algorithms=())
    result, = compare_routes([
        report("u_only", [quantum(20)], options=options),
        report("composite", [quantum(15)], options=options),
    ])
    assert result.conclusions["quantum"].best[0].route_id == "composite"
    assert "memory bound is not applied" in result.conclusions["quantum"].reason
    assert "feasible memory" not in result.conclusions["quantum"].reason
    assert result.conclusions["classical"].status == "not_requested"


def test_groups_separate_schemes_parameters_and_goals_in_input_order():
    rows = [classical(10)]
    reports = [
        report("u_only", rows),
        report("u_only", rows, scheme="QUBE"),
        report("u_only", rows, parameter_set="level-3"),
        report("u_only", rows, goal="key_recovery"),
        report("composite", rows),
    ]
    groups = compare_routes(reports)
    assert [(item.scheme, item.parameter_set, item.goal) for item in groups] == [
        ("HARE", "level-1", "msg_recovery"),
        ("QUBE", "level-1", "msg_recovery"),
        ("HARE", "level-3", "msg_recovery"),
        ("HARE", "level-1", "key_recovery"),
    ]
    assert groups[0].routes == (reports[0].instance.name, reports[4].instance.name)
    assert all(len(item.routes) == 1 for item in groups[1:])
    assert compare_routes([]) == []


def test_options_must_match_within_each_group_but_not_across_groups():
    first = report("u_only", [classical(20)])
    second = report("composite", [classical(15)], options=Options(memory_bound_log2_bits=10))
    with pytest.raises(ValueError, match="different options"):
        compare_routes([first, second])
    other_group = replace(second, instance=replace(second.instance, parameter_set="other"))
    assert len(compare_routes([first, other_group])) == 2


def test_duplicate_names_are_rejected_within_a_group():
    first = report("u_only", [classical(20)])
    with pytest.raises(ValueError, match="Duplicate route instance name"):
        compare_routes([first, first])


def test_all_disabled_or_unavailable_have_no_winners():
    options = Options(classical_algorithms=(), quantum_algorithms=())
    result, = compare_routes([
        report("u_only", [classical(0), quantum(0)], options=options),
        report("composite", [], options=options),
    ])
    assert all(item.status == "not_requested" and item.best == ()
               for item in result.conclusions.values())
    unavailable, = compare_routes([report("u_only", []), report("composite", [])])
    assert all(item.status == "unavailable" and item.best == ()
               for item in unavailable.conclusions.values())


def test_serialization_preserves_estimate_and_route_references():
    winner = classical(10, parameters={"p": 2}, references=("cost source",))
    first = report("u_only", [classical(20)])
    second = report("composite", [winner])
    result, = compare_routes([first, second])
    encoded = json.loads(json.dumps(result.to_dict(), allow_nan=False))
    assert encoded["scheme"] == "HARE"
    assert encoded["routes"] == [first.instance.name, second.instance.name]
    assert encoded["options"]["memory_bound_log2_bits"] is None
    assert encoded["conclusions"]["classical"]["best"] == [{
        "name": second.instance.name, "route": second.instance.route,
        "route_id": "composite", "estimate": second.to_dict()["results"][0]
        | {"references": ["cost source"], "assumptions": []},
    }]
    assert encoded["conclusions"]["quantum"]["best"] == []
    assert second.results == [winner]
