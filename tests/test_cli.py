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


def test_cli_defaults_to_all_upstream_classical_and_registered_quantum_algorithms(attack_file, capsys):
    assert main(["estimate", str(attack_file), "--json"]) == 0
    record, = json.loads(capsys.readouterr().out)
    classical = [row for row in record["results"] if row["model"] == "classical"]
    quantum = [row for row in record["results"] if row["model"] == "quantum"]
    upstream = SDEstimator(n=40, k=20, w=4, nsolutions=2)
    assert {row["algorithm"] for row in classical} == {
        type(algorithm).__name__ for algorithm in upstream.algorithms()
    }
    assert all(row["status"] == "computed" for row in classical)
    assert tuple(row["algorithm"] for row in quantum) == QuantumModel.algorithms
    assert all(row["status"] == "not_implemented" and row["time_log2"] is None
               and row["memory_log2"] is None for row in quantum)
    assert record["options"]["classical_algorithms"] is None
    assert record["options"]["quantum_algorithms"] == list(QuantumModel.algorithms)
    assert set(record["backends"]) == {"classical", "quantum"}
    assert record["conclusions"]["classical"]["status"] == "computed"
    assert record["conclusions"]["quantum"]["status"] == "unavailable"
    assert record["conclusions"]["quantum"]["best"] == []


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
    assert all(row["status"] == "not_implemented" for row in rows[2:])
    conclusions = records[0]["conclusions"]
    assert conclusions["classical"]["status"] == "computed"
    assert conclusions["classical"]["best"] == [min(rows[:2], key=lambda row: row["time_log2"])]
    assert conclusions["quantum"]["status"] == "unavailable"
    assert conclusions["quantum"]["best"] == []


def test_cli_prints_separate_classical_and_quantum_conclusions(attack_file, capsys):
    assert main(["estimate", str(attack_file), "--classical-algorithms", "Prange",
                 "--quantum-algorithms", "QSS"]) == 0
    output = capsys.readouterr().out
    assert "Best classical: Prange | time=2^" in output
    assert "bit_operations; memory=2^" in output
    assert "bits; parameters=" in output
    assert "Best quantum: -- (unavailable)" in output


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
    assert all(row["status"] == "not_implemented" and row["time_log2"] is None
               for row in records[0]["results"])


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
