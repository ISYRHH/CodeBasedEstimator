"""Run the Hamming adapter and DOOM dispatch together on small test parameters."""

import csv
from dataclasses import replace
import io
import json
from math import log2

import pytest

from codebased_estimator import AttackInstance, Options, estimate
from codebased_estimator.__main__ import main
from codebased_estimator.hamming import HammingScheme, hamming_instances
from codebased_estimator.quantum_costs import COST_MODEL, OUTER_PROBABILITY_MODEL


@pytest.fixture
def small_adapted_bike(monkeypatch):
    # Only the source parameter snapshot is replaced: adapter, CLI serialization,
    # classical optimizers and quantum optimizers all run normally.
    monkeypatch.setattr("codebased_estimator.hamming.HAMMING_PARAMETERS", [{
        "scheme": "BIKE_MLThre", "parameter_set": "BIKE-test",
        "parameters": {"r": 11, "w": 4, "t": 3, "dv": 2},
        "references": ["synthetic parameters for integration testing"],
        "notes": ["Not a submitted BIKE parameter set."],
    }])
    return "BIKE-test"


def test_default_automatic_mode_preserves_the_two_different_target_semantics(small_adapted_bike):
    default = hamming_instances(schemes=["BIKE_MLThre"])
    explicit = hamming_instances(schemes=["BIKE_MLThre"], doom="auto")
    assert default == explicit
    key, message = default
    assert key.problem.kind == "cfp" and key.tags == ("doom:qccf",)
    assert message.problem.kind == "sd" and message.tags == ("doom:qcsd",)
    assert key.targets == message.targets == 11
    assert key.problem.log2_solutions is None
    assert message.problem.log2_solutions == 0
    # The adapter must not also encode the orbit count as per-syndrome solutions.
    with pytest.raises(ValueError, match="double counting"):
        replace(key, problem=replace(key.problem, log2_solutions=log2(11)))


def test_cli_json_costs_adapted_qccf_and_falls_back_for_quantum_qcsd(small_adapted_bike, capsys):
    assert main(["hamming", "--schemes", "BIKE_MLThre", "--json",
                 "--classical-algorithms", "Prange", "Stern", "MAGE-Stern",
                 "--quantum-algorithms", "QSS", "QMMT+"]) == 0
    key, message = json.loads(capsys.readouterr().out)
    for record in (key, message):
        assert record["instance"]["targets"] == 11
        # Exported input can be replayed without changing any target semantics.
        restored = AttackInstance.from_dict(record["instance"])
        assert restored == HammingScheme("BIKE_MLThre").instances(
            small_adapted_bike, record["instance"]["goal"])[0]
        assert record["conclusions"]["classical"]["status"] == "computed"
    assert key["instance"]["problem"]["kind"] == "cfp"
    assert key["instance"]["problem"]["log2_solutions"] is None
    assert key["instance"]["tags"] == ["doom:qccf"]
    for row in key["results"]:
        assert row["status"] == "computed"
        assert row["metadata"]["effective_log2_solutions"] == pytest.approx(log2(11))
        assert row["metadata"]["doom"]["effective_log2_solutions"] == pytest.approx(log2(11))
        if row["model"] == "quantum":
            assert row["parameters"]["p"] > 0
            assert row["metadata"]["doom"]["postprocessing_speedup_applied"] is False
        elif row["algorithm"] == "MAGE-Stern":
            assert row["parameters"]["codewords"] == 11
            assert row["metadata"]["effective_syndrome_targets"] == 1
            assert row["metadata"]["doom"]["model"] == "mage_stern_codeword_proxy"
            assert "active_targets" not in row["metadata"]["doom"]
    assert key["conclusions"]["quantum"]["status"] == "computed"
    assert message["instance"]["problem"]["kind"] == "sd"
    assert message["instance"]["problem"]["log2_solutions"] == 0
    assert message["instance"]["tags"] == ["doom:qcsd"]
    for row in message["results"]:
        if row["model"] == "classical":
            assert row["status"] == "computed"
            assert row["metadata"]["effective_log2_solutions"] == 0
            assert 1 <= row["metadata"]["doom"]["active_targets"] <= 11
        else:
            assert row["status"] == "computed"
            assert row["time_log2"] is not None and row["memory_log2"] is None
            assert row["metadata"]["doom"]["model"] == "single_target_fallback"
            assert row["metadata"]["doom"]["applied"] is False
            assert row["metadata"]["effective_targets"] == 1
            assert row["metadata"]["effective_log2_solutions"] == 0
            assert "without DOOM" in row["reason"]
    assert message["conclusions"]["quantum"]["status"] == "computed"


def test_cli_csv_distinguishes_requested_orbit_context_from_effective_fallback(small_adapted_bike, capsys):
    assert main(["hamming", "--schemes", "BIKE_MLThre", "--csv",
                 "--classical-algorithms", "Stern", "MAGE-Stern", "--quantum-algorithms", "QSS"]) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert len(rows) == 6
    for row in rows:
        assert row["targets"] == "11"
        if row["goal"] == "key_recovery":
            assert row["problem_kind"] == "cfp" and row["doom"] == "doom:qccf"
            assert row["status"] == "computed" and float(row["time_log2"]) > 0
            assert row["cost_model"]
            assert row["effective_doom"] == "doom:qccf"
            assert row["effective_targets"] == "11"
            if row["model"] == "quantum":
                assert row["cost_model"] == COST_MODEL
                assert row["cost_model"] != OUTER_PROBABILITY_MODEL
            elif row["algorithm"] == "MAGE-Stern":
                assert row["cost_model"] == "ce-mage-qccf-codewords-v1"
                assert row["active_targets"] == ""
        else:
            assert row["problem_kind"] == "sd" and row["doom"] == "doom:qcsd"
            if row["model"] == "classical":
                assert row["status"] == "computed"
                assert 1 <= int(row["active_targets"]) <= 11
                assert row["cost_model"] == ("ce-mage-generator-v2" if row["algorithm"] == "MAGE-Stern"
                                              else "ce-doom-finite-v2")
                assert row["effective_doom"] == "doom:qcsd"
                assert row["effective_targets"] == row["active_targets"]
            else:
                assert row["status"] == "computed"
                assert float(row["time_log2"]) > 0 and row["memory_log2"] == ""
                assert row["active_targets"] == row["effective_targets"] == "1"
                assert row["effective_doom"] == ""
                assert row["is_best"] == "True" and "without DOOM" in row["reason"]


def test_cli_none_restores_single_target_costs_and_quantum_sd(small_adapted_bike, capsys):
    assert main(["hamming", "--schemes", "BIKE_MLThre", "--doom", "none", "--json",
                 "--classical-algorithms", "Stern", "--quantum-algorithms", "QSS"]) == 0
    baseline_records = json.loads(capsys.readouterr().out)
    for record in baseline_records:
        instance = record["instance"]
        assert instance["problem"]["kind"] == "sd"
        assert instance["problem"]["log2_solutions"] == 0
        assert instance["tags"] == [] and instance["targets"] == 1
        assert all(row["status"] == "computed" for row in record["results"])
        assert all(row["metadata"]["effective_log2_solutions"] == 0 for row in record["results"])
        assert all("doom" not in row["metadata"] for row in record["results"])
        auto = HammingScheme("BIKE_MLThre").instances(small_adapted_bike, instance["goal"])[0]
        optimized = estimate(auto, options=Options(classical_algorithms=("Stern",), quantum_algorithms=()))
        baseline_classical = next(row for row in record["results"] if row["model"] == "classical")
        assert optimized.results[0].time_log2 <= baseline_classical["time_log2"] + 1e-10
        if instance["goal"] == "msg_recovery":
            fallback, = estimate(auto, options=Options(
                classical_algorithms=(), quantum_algorithms=("QSS",))).results
            baseline_quantum = next(row for row in record["results"] if row["model"] == "quantum")
            assert fallback.time_log2 == baseline_quantum["time_log2"]
            assert fallback.parameters == baseline_quantum["parameters"]


@pytest.mark.parametrize("mode", ["qccf", "qcsd", "", None])
def test_adapter_rejects_unrecognized_doom_modes(mode):
    with pytest.raises(ValueError, match="doom must be auto or none"):
        HammingScheme("BIKE_MLThre").instances("BIKE_MLThre-128", "key_recovery", doom=mode)
