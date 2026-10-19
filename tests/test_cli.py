"""Exercise CLI records, algorithm selection and DOOM context end to end."""

import json
from types import SimpleNamespace

import pytest

from cryptographic_estimators.SDEstimator import SDEstimator

from codebased_estimator.__main__ import main
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
    monkeypatch.setattr("codebased_estimator.quantum.optimize", lambda *args: cost)
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
    assert quantum[0]["status"] == "not_implemented"
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
    assert rows[2]["status"] == "not_implemented"
    assert all(row["status"] == "computed" for row in rows[3:])
    conclusions = records[0]["conclusions"]
    assert conclusions["classical"]["status"] == "computed"
    assert conclusions["classical"]["best"] == [min(rows[:2], key=lambda row: row["time_log2"])]
    assert conclusions["quantum"]["status"] == "computed"
    assert conclusions["quantum"]["best"] == [min(rows[3:], key=lambda row: row["time_log2"])]


def test_cli_prints_separate_classical_and_quantum_conclusions(attack_file, capsys):
    assert main(["estimate", str(attack_file), "--classical-algorithms", "Prange",
                 "--quantum-algorithms", "QSS"]) == 0
    output = capsys.readouterr().out
    assert "Best classical: Prange | time=2^" in output
    assert "bit_operations; memory=2^" in output
    assert "bits; parameters=" in output
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
    assert quantum[0]["status"] == "not_implemented" and quantum[0]["time_log2"] is None
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


def test_cli_prints_time_only_quantum_result_without_claiming_memory_feasibility(
    attack_file, capsys, quantum_cost,
):
    data = json.loads(attack_file.read_text())
    data["problem"]["log2_solutions"] = 0
    attack_file.write_text(json.dumps(data))
    assert main(["estimate", str(attack_file), "--classical-algorithms",
                 "--quantum-algorithms", "QSS", "--memory-bound", "0"]) == 0
    output = capsys.readouterr().out
    assert "Best quantum: QSS | time=2^19.500 quantum_bit_operations" in output
    assert "memory=not estimated" in output
    assert "memory bound is not applied" in output
    assert "feasible memory" not in output


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
