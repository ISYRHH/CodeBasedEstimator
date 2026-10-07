"""Check scientific comparability and feasibility of reported minima."""

import json
from dataclasses import replace

from codebased_estimator import AttackInstance, Conclusion, Estimate, Options, Problem, Report


def report(rows, options=None):
    attack = AttackInstance("summary test", "msg_recovery",
                            Problem("sd", {"n": 40, "k": 20, "w": 4}, 0))
    return Report(attack, options or Options(quantum_algorithms=("QPrange", "QSS")),
                  {"classical": {"name": "test"}, "quantum": {"name": "test"}}, rows)


def test_each_family_has_its_own_minimum_and_preserves_exact_ties_in_order():
    first = Estimate("Stern", "classical", "computed", 80, 20, parameters={"p": 2})
    second = Estimate("Dumer", "classical", "computed", 80, 15, parameters={"p": 1})
    quantum = Estimate("QSS", "quantum", "computed", 45, 25,
                       time_unit="logical_gates", memory_unit="qubits")
    result = report([
        Estimate("Prange", "classical", "computed", 100, 10),
        first,
        Estimate("AlmostTie", "classical", "computed", 80 + 1e-10, 10),
        second,
        Estimate("QPrange", "quantum", "computed", 46, 10,
                 time_unit="logical_gates", memory_unit="qubits"),
        quantum,
    ]).conclusions
    assert set(result) == {"classical", "quantum"}
    assert all(isinstance(value, Conclusion) for value in result.values())
    assert result["classical"].status == result["quantum"].status == "computed"
    assert result["classical"].best == (first, second)
    assert result["quantum"].best == (quantum,)
    assert result["classical"].best[0].parameters == {"p": 2}


def test_unavailable_and_invalid_estimates_cannot_win_even_with_smaller_numbers():
    invalid = [
        Estimate("pending", "classical", "not_implemented", 0, 0),
        Estimate("bounded-out", "classical", "infeasible", 0, 0),
        Estimate("unknown-time", "classical", "computed", None, 0),
        Estimate("unknown-memory", "classical", "computed", 0, None),
        Estimate("nan-time", "classical", "computed", float("nan"), 0),
        Estimate("nan-memory", "classical", "computed", 0, float("nan")),
        Estimate("infinite-time", "classical", "computed", float("inf"), 0),
        Estimate("infinite-memory", "classical", "computed", 0, float("inf")),
        Estimate("negative-infinity", "classical", "computed", -float("inf"), 0),
        Estimate("bool-time", "classical", "computed", False, 0),
        Estimate("bool-memory", "classical", "computed", 0, False),
        Estimate("no-time-unit", "classical", "computed", 0, 0, time_unit=""),
        Estimate("no-memory-unit", "classical", "computed", 0, 0, memory_unit="  "),
        Estimate("unknown-time-unit", "classical", "computed", 0, 0, time_unit="unspecified"),
        Estimate("unknown-memory-unit", "classical", "computed", 0, 0, memory_unit="unspecified"),
        Estimate("different-model", "other", "computed", 0, 0),
    ]
    feasible = Estimate("Prange", "classical", "computed", 30, 12)
    assert report([*invalid, feasible]).conclusions["classical"].best == (feasible,)
    unavailable = report(invalid).conclusions
    assert all(value.status == "unavailable" and value.best == () and value.reason
               for value in unavailable.values())


def test_memory_bound_excludes_faster_rows_and_accepts_exact_boundary_in_bits():
    boundary = Estimate("Stern", "classical", "computed", 10, 10)
    result = report([
        Estimate("Prange", "classical", "computed", 5, 11),
        boundary,
        Estimate("Dumer", "classical", "computed", 12, 9),
        Estimate("bytes", "classical", "computed", 1, 1, memory_unit="bytes"),
        Estimate("QPrange", "quantum", "computed", 3, 5,
                 time_unit="logical_gates", memory_unit="qubits"),
    ], options=Options(quantum_algorithms=("QPrange",), memory_bound_log2_bits=10)).conclusions
    assert result["classical"].status == "computed"
    assert result["classical"].best == (boundary,)
    # A bound in bits cannot be checked against an unconverted qubit count.
    assert result["quantum"].status == "unavailable"
    assert result["quantum"].best == ()


def test_differing_time_units_prevent_a_minimum_only_in_the_affected_family():
    quantum = Estimate("QPrange", "quantum", "computed", 40, 10,
                       time_unit="logical_gates", memory_unit="qubits")
    result = report([
        Estimate("Prange", "classical", "computed", 20, 10),
        Estimate("Stern", "classical", "computed", 10, 10, time_unit="vector_operations"),
        # An unimplemented candidate must not make quantum units incomparable.
        Estimate("QSS", "quantum", "not_implemented", time_unit="oracle_queries"),
        quantum,
    ]).conclusions
    assert result["classical"].status == "incomparable_units"
    assert result["classical"].best == ()
    assert result["classical"].reason
    assert result["quantum"].best == (quantum,)


def test_disabled_families_are_not_requested_even_if_results_were_supplied():
    rows = [Estimate("Prange", "classical", "computed", 20, 10),
            Estimate("QPrange", "quantum", "computed", 10, 10)]
    classical_only = report(rows, Options(quantum_algorithms=())).conclusions
    assert classical_only["classical"].best == (rows[0],)
    assert classical_only["quantum"].status == "not_requested"
    assert classical_only["quantum"].best == ()
    quantum_only = report(rows, Options(classical_algorithms=(),
                                       quantum_algorithms=("QPrange",))).conclusions
    assert quantum_only["classical"].status == "not_requested"
    assert quantum_only["classical"].best == ()
    assert quantum_only["quantum"].best == (rows[1],)


def test_conclusions_serialize_as_strict_json_without_discarding_individual_results():
    winner = Estimate("Stern", "classical", "computed", 20, 10,
                      parameters={"p": 2}, references=("model source",))
    rows = [Estimate("Prange", "classical", "computed", 30, 5), winner,
            Estimate("QPrange", "quantum", "not_implemented", reason="finite model pending")]
    result = report(rows)
    serialized = json.loads(json.dumps(result.to_dict(), allow_nan=False))
    assert len(serialized["results"]) == 3
    assert set(serialized["conclusions"]) == {"classical", "quantum"}
    classical = serialized["conclusions"]["classical"]
    assert classical["status"] == "computed"
    assert isinstance(classical["best"], list)
    assert classical["best"] == [serialized["results"][1]]
    assert serialized["conclusions"]["quantum"]["status"] == "unavailable"
    assert serialized["conclusions"]["quantum"]["best"] == []
    assert result.results == rows


def test_explicit_time_only_quantum_results_compare_without_memory_constraints():
    first = Estimate("QSS", "quantum", "computed", 15, None,
                     time_unit="quantum_bit_operations", memory_unit="not_estimated",
                     metadata={"resource_scope": "time_only"})
    second = replace(first, algorithm="QMMT+")
    result = report([first, second], Options(memory_bound_log2_bits=0))
    conclusion = result.conclusions["quantum"]
    assert conclusion.status == "computed"
    assert conclusion.best == (first, second)
    assert "memory bound is not applied" in conclusion.reason
    assert "feasible memory" not in conclusion.reason
    encoded = json.loads(json.dumps(result.to_dict(), allow_nan=False))
    assert encoded["conclusions"]["quantum"]["best"][0]["memory_log2"] is None


def test_time_only_exception_does_not_relax_other_result_validation():
    valid = Estimate("QSS", "quantum", "computed", 15, None,
                     time_unit="quantum_bit_operations", memory_unit="not_estimated",
                     metadata={"resource_scope": "time_only"})
    invalid = [
        replace(valid, model="classical"),
        replace(valid, metadata={}),
        replace(valid, memory_unit="bits"),
        replace(valid, status="not_implemented"),
        replace(valid, time_log2=None),
        replace(valid, time_log2=float("nan")),
        replace(valid, time_log2=True),
        replace(valid, time_unit="unspecified"),
        replace(valid, memory_log2=10),
    ]
    result = report(invalid, Options(memory_bound_log2_bits=0)).conclusions
    assert all(row.status == "unavailable" for row in result.values())


def test_time_only_quantum_estimates_still_require_compatible_time_units():
    quantum = Estimate("QSS", "quantum", "computed", 15, None,
                       time_unit="quantum_bit_operations", memory_unit="not_estimated",
                       metadata={"resource_scope": "time_only"})
    other = Estimate("QPrange", "quantum", "computed", 10, 5, time_unit="logical_gates")
    assert report([quantum, other]).conclusions["quantum"].status == "incomparable_units"
