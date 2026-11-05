"""Exercise CLI records, algorithm selection and DOOM context end to end."""

import csv
from dataclasses import asdict, replace
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from cryptographic_estimators.SDEstimator import SDEstimator

from codebased_estimator import AttackInstance, BlockProfile, Options, Problem, estimate
from codebased_estimator.__main__ import _csv_results, _table, main
from codebased_estimator.hamming import hamming_instances
from codebased_estimator.quantum import QuantumModel


@pytest.fixture
def attack_file(tmp_path):
    path = tmp_path / "attack.json"
    path.write_text(json.dumps({
        "name": "cli-test", "goal": "msg_recovery",
        "problem": {"kind": "sd", "parameters": {"n": 40, "k": 20, "w": 4},
                    "log2_solutions": 2},
    }))
    return path


@pytest.fixture
def quantum_cost(monkeypatch):
    cost = SimpleNamespace(time_log2=19.5, parameters={"ell": 0, "p": 0},
                           details={}, search={"method": "test fixture"})
    monkeypatch.setattr("codebased_estimator.quantum.optimize", lambda *args, **kwargs: cost)
    return cost


def test_cli_defaults_include_mage_and_report_its_unsupported_multisolution_scope(attack_file, capsys):
    assert main(["estimate", str(attack_file), "--json"]) == 0
    record, = json.loads(capsys.readouterr().out)
    classical = [row for row in record["results"] if row["model"] == "classical"]
    quantum = [row for row in record["results"] if row["model"] == "quantum"]
    upstream = SDEstimator(n=40, k=20, w=4, nsolutions=2)
    assert {row["algorithm"] for row in classical} == {
        type(algorithm).__name__ for algorithm in upstream.algorithms()
    } | {"MAGE-Stern"}
    assert all(row["status"] == "computed" for row in classical if row["algorithm"] != "MAGE-Stern")
    mage, = [row for row in classical if row["algorithm"] == "MAGE-Stern"]
    assert mage["status"] == "not_implemented" and mage["reason"]
    assert mage["time_log2"] is None and mage["memory_log2"] is None
    assert mage not in record["conclusions"]["classical"]["best"]
    assert tuple(row["algorithm"] for row in quantum) == QuantumModel.algorithms
    assert quantum[0]["status"] == "computed" and quantum[0]["time_log2"] is not None
    assert all(row["status"] == "computed" and row["time_log2"] is not None
               and row["memory_log2"] is None for row in quantum[1:])
    assert record["options"]["classical_algorithms"] is None
    assert record["options"]["quantum_algorithms"] == list(QuantumModel.algorithms)
    assert set(record["backends"]) == {"classical", "quantum"}
    assert record["conclusions"]["classical"]["status"] == "computed"
    assert record["conclusions"]["quantum"]["status"] == "computed"
    assert record["conclusions"]["quantum"]["best"]


@pytest.mark.parametrize("disabled,enabled", [("classical", "quantum"), ("quantum", "classical")])
def test_cli_empty_algorithm_list_disables_only_that_family(attack_file, capsys, disabled, enabled):
    assert main(["estimate", str(attack_file), f"--{disabled}-algorithms", "--json"]) == 0
    record, = json.loads(capsys.readouterr().out)
    assert record["results"]
    assert {row["model"] for row in record["results"]} == {enabled}
    assert set(record["backends"]) == {enabled}
    assert record["conclusions"][disabled]["status"] == "not_requested"
    assert record["conclusions"][enabled]["status"] != "not_requested"


def test_cli_combines_independent_algorithm_lists_in_one_record(attack_file, capsys):
    assert main(["estimate", str(attack_file), "--classical-algorithms", "Prange", "Stern",
                 "--quantum-algorithms", "QPrange", "QSS", "QMMT+", "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert len(records) == 1
    assert set(records[0]["backends"]) == {"classical", "quantum"}
    rows = records[0]["results"]
    assert [(row["model"], row["algorithm"]) for row in rows] == [
        ("classical", "Prange"), ("classical", "Stern"),
        ("quantum", "QPrange"), ("quantum", "QSS"), ("quantum", "QMMT+"),
    ]
    assert all(row["status"] == "computed" for row in rows[:2])
    assert rows[2]["status"] == "computed"
    assert all(row["status"] == "computed" for row in rows[3:])
    conclusions = records[0]["conclusions"]
    assert conclusions["classical"]["status"] == "computed"
    assert conclusions["classical"]["best"] == [min(rows[:2], key=lambda row: row["time_log2"])]
    assert conclusions["quantum"]["status"] == "computed"
    assert conclusions["quantum"]["best"] == [min(rows[2:], key=lambda row: row["time_log2"])]


def test_cli_prints_separate_classical_and_quantum_conclusions(attack_file, capsys):
    assert main(["estimate", str(attack_file), "--classical-algorithms", "Prange",
                 "--quantum-algorithms", "QSS"]) == 0
    output = capsys.readouterr().out
    assert "Best classical: Prange | time=2^" in output
    assert "bit_operations; memory=2^" in output
    assert "bits; parameters=" not in output
    assert "Best quantum: QSS | time=2^" in output


def test_cli_doom_flags_preserve_solutions_and_algorithm_names(attack_file, capsys):
    assert main(["estimate", str(attack_file), "--classical-algorithms", "Prange", "Stern",
                 "--quantum-algorithms", "QPrange", "QSS", "QMMT+",
                 "--doom", "qcsd", "--targets", "32", "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert len(records) == 1
    attack = records[0]["instance"]
    assert attack["tags"] == ["doom:qcsd"]
    assert attack["targets"] == 32
    assert attack["problem"]["log2_solutions"] == 2
    assert [row["algorithm"] for row in records[0]["results"]] == [
        "Prange", "Stern", "QPrange", "QSS", "QMMT+",
    ]
    classical = records[0]["results"][:2]
    quantum = records[0]["results"][2:]
    assert all(row["status"] == "computed" and row["time_log2"] is not None
               and row["metadata"]["doom"]["available_targets"] == 32
               for row in classical)
    assert quantum[0]["status"] == "computed" and quantum[0]["time_log2"] is not None
    assert all(row["status"] == "computed" and row["time_log2"] is not None
               and row["metadata"]["effective_log2_solutions"] == 2 for row in quantum[1:])
    for row in quantum:
        assert row["metadata"]["doom"]["model"] == "single_target_fallback"
        assert row["metadata"]["doom"]["available_targets"] == 32
        assert row["metadata"]["effective_targets"] == 1
        assert row["metadata"]["effective_tags"] == []


def test_cli_qccf_uses_ce_solution_counts_and_preserves_the_original_instance(attack_file, capsys):
    from math import log2

    data = json.loads(attack_file.read_text())
    data["problem"]["kind"] = "cfp"
    data["problem"].pop("log2_solutions")
    attack_file.write_text(json.dumps(data))
    assert main(["estimate", str(attack_file), "--classical-algorithms", "Prange", "Stern",
                 "--quantum-algorithms", "QPrange", "QSS", "QMMT+", "--doom", "qccf",
                 "--targets", "3", "--json"]) == 0
    record, = json.loads(capsys.readouterr().out)
    attack = record["instance"]
    assert attack["problem"]["kind"] == "cfp"
    assert attack["problem"]["log2_solutions"] is None
    assert attack["tags"] == ["doom:qccf"]
    assert attack["targets"] == 3
    classical, quantum = record["results"][:2], record["results"][2:]
    direct = {type(algorithm).__name__: algorithm for algorithm in
              SDEstimator(n=40, k=20, w=4, nsolutions=log2(3)).algorithms()}
    for row in classical:
        assert row["status"] == "computed"
        assert row["time_log2"] == pytest.approx(direct[row["algorithm"]].time_complexity())
        assert row["metadata"]["doom"]["model"] == "ce_nsolutions"
        assert row["metadata"]["effective_log2_solutions"] == log2(3)
    assert quantum[0]["status"] in ("not_applicable", "not_implemented")
    for row in quantum[1:]:
        assert row["status"] == "computed"
        assert row["metadata"]["effective_log2_solutions"] == log2(3)
        assert row["parameters"]["p"] > 0


@pytest.mark.parametrize("flag", ("--log2-solutions", "--nsolutions"))
def test_cli_solution_override_reaches_both_models(attack_file, capsys, flag):
    assert main(["estimate", str(attack_file), flag, "3",
                 "--classical-algorithms", "Prange", "--quantum-algorithms", "QSS", "--json"]) == 0
    record, = json.loads(capsys.readouterr().out)
    assert record["instance"]["problem"]["log2_solutions"] == 3
    classical, quantum = record["results"]
    expected = SDEstimator(n=40, k=20, w=4, nsolutions=3).prange.time_complexity()
    assert classical["time_log2"] == pytest.approx(expected)
    assert quantum["status"] == "computed"
    assert quantum["metadata"]["effective_log2_solutions"] == 3
    assert quantum["metadata"]["cost_breakdown"]["log2_solutions"] == 3


@pytest.mark.parametrize("value", ("-1", "nan", "inf"))
def test_cli_solution_override_rejects_invalid_counts(attack_file, capsys, value):
    with pytest.raises(SystemExit) as exc:
        main(["estimate", str(attack_file), "--nsolutions", value,
              "--classical-algorithms", "--quantum-algorithms", "QSS"])
    assert exc.value.code == 2
    assert "log2_solutions" in capsys.readouterr().err


def test_cli_qccf_does_not_double_count_a_solution_override(attack_file, capsys):
    data = json.loads(attack_file.read_text())
    data["problem"] = {"kind": "cfp", "parameters": {"n": 40, "k": 20, "w": 4}}
    attack_file.write_text(json.dumps(data))
    with pytest.raises(SystemExit) as exc:
        main(["estimate", str(attack_file), "--doom", "qccf", "--targets", "8",
              "--nsolutions", "3", "--classical-algorithms", "--quantum-algorithms", "QSS"])
    assert exc.value.code == 2
    assert "double counting" in capsys.readouterr().err


def test_cli_demo_has_one_record_per_instance_with_hamming_quantum_rows(capsys, quantum_cost):
    assert main(["demo", "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    names = [record["instance"]["name"] for record in records]
    assert len(names) == len(set(names)) == 6
    hamming = [record for record in records if record["instance"]["parameter_set"] == "hamming"]
    assert len(hamming) == 2
    assert {record["instance"]["goal"] for record in hamming} == {"key_recovery", "msg_recovery"}
    for record in hamming:
        quantum = [row for row in record["results"] if row["model"] == "quantum"]
        assert [row["algorithm"] for row in quantum] == ["QPrange", "QSS", "QMMT+"]
        assert any(row["model"] == "classical" and row["status"] == "computed"
                   for row in record["results"])


@pytest.mark.parametrize("detail", [[], ["--no-brief"]])
def test_cli_prints_time_only_quantum_result_without_claiming_memory_feasibility(
    attack_file, capsys, quantum_cost, detail,
):
    data = json.loads(attack_file.read_text())
    data["problem"]["log2_solutions"] = 0
    attack_file.write_text(json.dumps(data))
    assert main(["estimate", str(attack_file), "--classical-algorithms",
                 "--quantum-algorithms", "QSS", "--memory-bound", "0", *detail]) == 0
    output = capsys.readouterr().out
    assert "Best quantum: QSS | time=2^19.500 quantum_bit_operations" in output
    assert "memory=not estimated" in output
    assert "memory bound is not applied" in output
    assert "feasible memory" not in output


@pytest.mark.parametrize("detail", [[], ["--no-brief"]])
def test_cli_text_keeps_doom_fallback_visible(attack_file, capsys, quantum_cost, detail):
    assert main(["estimate", str(attack_file), "--doom", "qcsd", "--targets", "32",
                 "--classical-algorithms", "--quantum-algorithms", "QSS", *detail]) == 0
    output = capsys.readouterr().out
    assert "DOOM fallback: QSS use single-target SD (targets=1)." in output
    assert "Best quantum: QSS" in output
    assert "Heuristic time-only estimate;" not in output


def test_cli_rejects_removed_model_flag(attack_file, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["estimate", str(attack_file), "--model", "doom"])
    assert exc.value.code == 2
    assert "--model" in capsys.readouterr().err


def test_cli_reports_unknown_quantum_algorithm(attack_file, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["estimate", str(attack_file), "--classical-algorithms", "Prange",
              "--quantum-algorithms", "QUnknown", "--json"])
    assert exc.value.code == 2
    assert "QUnknown" in capsys.readouterr().err


def _json_normalized(value):
    return json.loads(json.dumps(value, allow_nan=False))


def test_profile_api_roundtrip_matches_fresh_cli_process(tmp_path):
    attack = AttackInstance("profile replay", "key_recovery",
        Problem("sd", {"n": 24, "k": 12, "w": 4}, 0), targets=6,
        tags=("doom:qcsd",), block_profile=BlockProfile((12, 12), (1, 3)))
    algorithms = ("Prange", "Stern", "Dumer", "BallCollision", "BothMay", "BJMMplus",
                  "BJMM", "MayOzerov", "BJMMdw", "BJMMpdw", "MAGE-Stern")
    options = Options(classical_algorithms=algorithms, quantum_algorithms=("QSS", "QMMT+"))
    source = _json_normalized(asdict(attack))
    expected = _json_normalized(estimate(attack, options=options).to_dict())
    replayed = _json_normalized(estimate(AttackInstance.from_dict(source), options=options).to_dict())
    assert _json_normalized(asdict(attack)) == source
    path = tmp_path/"instance.json"
    path.write_text(json.dumps(source))
    process = subprocess.run([sys.executable, "-m", "codebased_estimator", "estimate", str(path),
        "--classical-algorithms", *algorithms, "--quantum-algorithms", "QSS", "QMMT+", "--json"],
        cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True, check=True, timeout=60)
    actual, = json.loads(process.stdout)
    for field in ("instance", "options", "results", "conclusions"):
        assert actual[field] == expected[field] == replayed[field]


def test_profile_qccf_output_uses_selected_codewords(capsys):
    attack = AttackInstance("QCCF profile", "key_recovery",
        Problem("cfp", {"n": 20, "k": 10, "w": 3}), targets=6, tags=("doom:qccf",),
        block_profile=BlockProfile((10, 10), (0, 3), ((0, 1), (1, 0))))
    report = estimate(attack, options=Options(
        classical_algorithms=("Prange", "MAGE-Stern"), quantum_algorithms=()))
    assert all(row.metadata["doom"]["active_codewords"] == 3 for row in report.results)
    _csv_results([report])
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert all(row["targets"] == "6" and row["effective_targets"] == "3" for row in rows)
    _table([report], brief=False)
    assert "Codewords used: Prange=3, MAGE-Stern=3" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["auto", "none"])
def test_catalogue_profiles_match_cli_route_export(mode, capsys):
    assert main(["hamming", "--list-routes", "--unbalanced", mode, "--json"]) == 0
    actual = json.loads(capsys.readouterr().out)
    expected = hamming_instances(unbalanced=mode)
    assert len(actual) == len(expected) == 144
    for row, attack in zip(actual, expected):
        assert row["name"] == attack.name
        assert row["problem"] == _json_normalized(asdict(attack.problem))
        assert row["block_profile"] == (attack.block_profile.to_dict() if attack.block_profile else None)


def test_cli_disabled_profile_matches_python_baseline(tmp_path, capsys):
    attack = AttackInstance("profile baseline", "key_recovery",
        Problem("sd", {"n": 24, "k": 12, "w": 4}, 0),
        block_profile=BlockProfile((12, 12), (1, 3)))
    path = tmp_path/"instance.json"
    path.write_text(json.dumps(asdict(attack)))
    assert main(["estimate", str(path), "--classical-algorithms", "Dumer", "--quantum-algorithms",
                 "QMMT+", "--unbalanced", "none", "--json"]) == 0
    actual, = json.loads(capsys.readouterr().out)
    expected = _json_normalized(estimate(replace(attack, block_profile=None), options=Options(
        classical_algorithms=("Dumer",), quantum_algorithms=("QMMT+",))).to_dict())
    assert actual["instance"]["block_profile"] is None
    assert actual["results"] == expected["results"]
