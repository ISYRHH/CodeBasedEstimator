"""Public selection and disclosure of the optional matrix cost profile."""

import csv
import io
import json
from dataclasses import replace
from math import log2

import pytest

from codebased_estimator import AttackInstance, Options, Problem, estimate
from codebased_estimator.__main__ import main
from codebased_estimator.matrix_costs import (
    DEFAULT_MATRIX_PROFILE, M4RI_MATRIX_PROFILE, MATRIX_PROFILES,
    cost_model_for_profile, matrix_budget,
)
from codebased_estimator.models import Report
from codebased_estimator.quantum_costs import evaluate_parameters, optimize


def attack(**changes):
    original = AttackInstance("matrix-interface", "msg_recovery",
                              Problem("sd", {"n": 24, "k": 12, "w": 4}, 0))
    return replace(original, **changes)


def options(profile=DEFAULT_MATRIX_PROFILE, **changes):
    return Options(classical_algorithms=(), quantum_algorithms=("QSS",),
                   quantum_matrix_profile=profile, **changes)


@pytest.mark.parametrize("profile", MATRIX_PROFILES)
def test_options_round_trip_selects_only_supported_profiles(profile):
    report = Report(attack(), options(profile), (), {})
    assert json.loads(json.dumps(report.to_dict()))["options"]["quantum_matrix_profile"] == profile
    assert Options().quantum_matrix_profile == DEFAULT_MATRIX_PROFILE


@pytest.mark.parametrize("invalid", ["m4ri", "", None, True, [], {}])
def test_options_reject_invalid_matrix_profiles(invalid):
    with pytest.raises(ValueError, match="matrix profile"):
        options(invalid)


@pytest.mark.parametrize("profile", MATRIX_PROFILES)
def test_profile_is_routed_to_optimizer_and_identified_in_public_json(monkeypatch, profile):
    point = evaluate_parameters(24, 12, 4, "QSS", ell=4, p=4, u=2, a=1,
                                matrix_profile=profile)
    calls = []

    def optimize(*args, **kwargs):
        calls.append((args, kwargs))
        return point

    monkeypatch.setattr("codebased_estimator.quantum.optimize", optimize)
    report = estimate(attack(), options=options(profile, memory_bound_log2_bits=0))
    row, = report.results
    assert calls == [((24, 12, 4, "QSS"), {} if profile == DEFAULT_MATRIX_PROFILE else
                     {"matrix_profile": profile})]
    assert row.status == "computed"
    assert row.time_log2 == point.time_log2
    assert row.parameters == point.parameters
    assert row.metadata["cost_breakdown"] == point.details
    assert row.metadata["search"] == point.search
    assert row.metadata["cost_model"] == cost_model_for_profile(profile)
    assert row.metadata["matrix_profile"] == profile
    assert report.backends["quantum"]["cost_model"] == cost_model_for_profile(profile)
    assert report.backends["quantum"]["matrix_profile"] == profile
    assert row.memory_log2 is None and row.metadata["memory_bound_applied"] is False
    assert report.conclusions["quantum"].best == (row,)
    if profile == DEFAULT_MATRIX_PROFILE:
        assert "matrix" not in row.metadata
        assert len(row.assumptions) == 3
    else:
        budget = matrix_budget(24, 12, point.parameters["ell"], profile)
        assert row.metadata["matrix"] == point.matrix
        assert row.metadata["matrix"]["block_size"] == budget.block_size
        assert row.metadata["matrix"]["log2_G_total"] == log2(budget.total)
        assert row.metadata["matrix"]["search"]["complete"] is True
        assert "h" not in row.parameters and "block_size" not in row.parameters
        assumptions = " ".join(row.assumptions)
        for disclosure in ("coherent", "pivot", "history", "cleanup", "not a quantum memory"):
            assert disclosure in assumptions
    json.dumps(report.to_dict(), allow_nan=False)


@pytest.mark.parametrize("changes", [
    {"tags": ("doom:qcsd",)}, {"targets": 2}, {"structure": ("quasi-cyclic",)},
    {"problem": Problem("sd", {"n": 24, "k": 12, "w": 4}, 1)},
    {"problem": Problem("sd", {"n": 24, "k": 12, "w": 4, "q": 3}, 0)},
])
def test_optional_profile_does_not_bypass_quantum_applicability(monkeypatch, changes):
    def forbidden(*args, **kwargs):
        pytest.fail("unsupported contexts must not reach the optimizer")

    monkeypatch.setattr("codebased_estimator.quantum.optimize", forbidden)
    row, = estimate(attack(**changes), options=options(M4RI_MATRIX_PROFILE)).results
    assert row.status in ("not_implemented", "not_applicable")
    assert row.time_log2 is None and "matrix" not in row.metadata
    assert row.metadata["matrix_profile"] == M4RI_MATRIX_PROFILE


def test_optional_profile_does_not_implement_qprange():
    settings = Options(classical_algorithms=(), quantum_algorithms=("QPrange",),
                       quantum_matrix_profile=M4RI_MATRIX_PROFILE)
    row, = estimate(attack(), options=settings).results
    assert row.status == "not_implemented" and row.time_log2 is None


@pytest.mark.parametrize("command", ["estimate", "demo", "hamming"])
def test_all_cli_commands_forward_profile_selection(monkeypatch, tmp_path, capsys, command):
    instance = attack()
    input_path = tmp_path / "attack.json"
    input_path.write_text(json.dumps({"name": instance.name, "goal": instance.goal,
        "problem": {"kind": "sd", "parameters": instance.problem.parameters,
                    "log2_solutions": 0}}))
    received = []

    def capture(instance, *, options):
        received.append(options)
        return Report(instance, options, (), {})

    monkeypatch.setattr("codebased_estimator.__main__.estimate", capture)
    monkeypatch.setattr("codebased_estimator.__main__.hamming_instances", lambda **kwargs: [instance])
    argv = [command] + ([str(input_path)] if command == "estimate" else [])
    assert main([*argv, "--quantum-matrix-profile", M4RI_MATRIX_PROFILE, "--json"]) == 0
    assert received and all(item.quantum_matrix_profile == M4RI_MATRIX_PROFILE for item in received)
    records = json.loads(capsys.readouterr().out)
    assert all(row["options"]["quantum_matrix_profile"] == M4RI_MATRIX_PROFILE for row in records)


@pytest.mark.parametrize("profile", MATRIX_PROFILES)
@pytest.mark.parametrize("algorithm", ["QSS", "QMMT+"])
def test_cli_profiles_serialize_actual_search_results_and_replay(tmp_path, capsys, profile, algorithm):
    input_path = tmp_path / "attack.json"
    input_path.write_text(json.dumps({"name": "small", "goal": "msg_recovery",
        "problem": {"kind": "sd", "parameters": {"n": 12, "k": 6, "w": 2},
                    "log2_solutions": 0}}))
    argv = ["estimate", str(input_path), "--classical-algorithms", "--quantum-algorithms", algorithm]
    if profile != DEFAULT_MATRIX_PROFILE:
        argv += ["--quantum-matrix-profile", profile]
    assert main([*argv, "--json"]) == 0
    report, = json.loads(capsys.readouterr().out)
    row, = report["results"]
    assert row["status"] == "computed" and row["algorithm"] == algorithm
    assert report["options"]["quantum_matrix_profile"] == profile
    assert row["metadata"]["matrix_profile"] == profile
    assert row["metadata"]["cost_model"] == cost_model_for_profile(profile)
    if profile == M4RI_MATRIX_PROFILE:
        assert row["metadata"]["matrix"]["profile"] == profile
        assert "legacy_retention" in row["metadata"]["search"]
    parameters = {key: value for key, value in row["parameters"].items() if key != "branch"}
    replay = evaluate_parameters(12, 6, 2, algorithm, matrix_profile=profile, **parameters)
    assert replay.time_log2 == row["time_log2"]
    assert main(argv) == 0
    output = capsys.readouterr().out
    assert "Best quantum: " + algorithm in output
    if profile == M4RI_MATRIX_PROFILE:
        assert "Quantum matrix profile: " + profile in output


def test_cli_rejects_unknown_matrix_profile(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["demo", "--quantum-matrix-profile", "m4ri"])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


@pytest.mark.parametrize("profile", MATRIX_PROFILES)
def test_csv_identifies_cost_profile_without_changing_classical_metadata(monkeypatch, capsys, profile):
    instance = attack()
    expected = {algorithm: optimize(24, 12, 4, algorithm, matrix_profile=profile)
                for algorithm in ("QSS", "QMMT+")}
    monkeypatch.setattr("codebased_estimator.__main__.hamming_instances", lambda **kwargs: [instance])
    assert main(["hamming", "--csv", "--classical-algorithms", "Prange",
                 "--quantum-algorithms", "QSS", "QMMT+", "QPrange",
                 "--quantum-matrix-profile", profile]) == 0
    classical, qss, qmmt, pending = csv.DictReader(io.StringIO(capsys.readouterr().out))
    assert classical["matrix_profile"] == classical["matrix_block_size"] == ""
    for quantum in (qss, qmmt):
        assert quantum["cost_model"] == cost_model_for_profile(profile)
        assert quantum["matrix_profile"] == pending["matrix_profile"] == profile
        point = expected[quantum["algorithm"]]
        assert float(quantum["time_log2"]) == point.time_log2
        if profile == M4RI_MATRIX_PROFILE:
            assert int(quantum["matrix_block_size"]) == point.matrix["block_size"]
        else:
            assert quantum["matrix_block_size"] == ""
    assert pending["cost_model"] == pending["matrix_block_size"] == ""
    assert pending["status"] == "not_implemented"


def test_optional_selection_does_not_change_classical_costs():
    def classical(profile):
        return estimate(attack(), options=Options(classical_algorithms=("Prange",),
            quantum_algorithms=(), quantum_matrix_profile=profile))
    before, after = classical(DEFAULT_MATRIX_PROFILE), classical(M4RI_MATRIX_PROFILE)
    assert before.results == after.results
    assert before.backends == after.backends
    assert "quantum" not in after.backends
