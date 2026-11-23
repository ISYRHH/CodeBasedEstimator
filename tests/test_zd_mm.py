"""Regression checks against the ZD-MM comparison and stage tables in the report."""

import json

import pytest

from codebased_estimator import Options, estimate, rank_instances
from codebased_estimator.__main__ import main
from codebased_estimator.rank import rank_algorithms
from codebased_estimator.web import _finite_json, catalogue


@pytest.mark.parametrize("parameter_set,key_bits,message_bits", [
    ("BAG-Loong-128", 113.074, 115.749),
    ("BAG-Loong-256", 212.315, 228.984),
    ("BAG-Loong-384", 299.061, 342.041),
    ("BAG-Loong-512", 444.080, 386.708),
    ("BAG-Piglet-128", 114.644, 158.899),
    ("BAG-Piglet-256", 254.033, 283.041),
    ("BAG-Piglet-384", 394.160, 450.550),
    ("BAG-Piglet-512", 567.599, 603.808),
    ("BRA-128", 112.088, 160.318),
    ("BRA-256", 161.840, 264.251),
    ("BRA-512", 316.802, 522.091),
    ("BRQC-128", 211.948, 185.575),
    ("BRQC-256", 304.468, 328.490),
    ("BRQC-512", 578.878, 590.891),
    ("C-Multi-UR-AG-128", 168.212, 209.247),
    ("C-Multi-UR-AG-256", 283.854, 315.661),
    ("C-Multi-UR-AG-512", 515.782, 657.968),
])
def test_reported_zd_mm_costs(parameter_set, key_bits, message_bits):
    options = Options(classical_algorithms=("Rank-ZD-MM",), quantum_algorithms=())
    instances = rank_instances(parameter_sets=[parameter_set])
    assert {instance.goal for instance in instances} == {"key_recovery", "msg_recovery"}
    for instance in instances:
        assert "Rank-ZD-MM" in rank_algorithms(instance)
        result, = estimate(instance, options=options).results
        assert result.status == "computed", result.reason
        assert result.is_time_only
        expected = key_bits if instance.goal == "key_recovery" else message_bits
        assert round(result.time_log2, 3) == expected
        assert result.metadata["omega"] == (2.8 if parameter_set.startswith("BAG-") else 2.0)


@pytest.mark.parametrize("parameter_set,goal,d,m,k,lengths,block,directions", [
    ("BAG-Loong-128", "key_recovery", 1, 47, 42, (42, 43), 2, 63),
    ("BAG-Piglet-256", "key_recovery", 2, 79, 39, (39, 39, 39), 2, 5461),
    ("BAG-Piglet-256", "msg_recovery", 3, 79, 52, (26, 26, 26, 26), 2, 585),
    ("BRA-128", "key_recovery", 1, 121, 67, (67, 67), 2, 63),
    ("BRQC-128", "msg_recovery", 1, 127, 122, (119, 119, 119), 1, 63),
    ("C-Multi-UR-AG-128", "msg_recovery", 1, 79, 38, (81,), 1, 1023),
])
def test_structured_working_parameters(parameter_set, goal, d, m, k, lengths, block, directions):
    instance, = rank_instances(parameter_sets=[parameter_set], goal=goal)
    options = Options(classical_algorithms=("Rank-ZD-MM",), quantum_algorithms=())
    result, = estimate(instance, options=options).results
    p = result.parameters
    assert (p["d"], p["m"], p["k"], tuple(p["lengths"])) == (d, m, k, lengths)
    assert (p["block"], p["directions"]) == (block, directions)
    assert p["variables"] - p["equations"] == p["kernel_dimension"] > 1
    assert min(p["equations"], p["equations_after"]) >= p["variables_after"] - 1


def test_loong_key_stage_ledger():
    instance, = rank_instances(parameter_sets=["BAG-Loong-128"], goal="key_recovery")
    options = Options(classical_algorithms=("Rank-ZD-MM",), quantum_algorithms=())
    result, = estimate(instance, options=options).results
    p = result.parameters
    assert tuple(p["guesses"]) == (7, 0)
    assert tuple(p["punctures"]) == (0, 0)
    assert (p["variables"], p["equations"], p["kernel_dimension"]) == (249131981, 246551613, 2580368)
    assert (p["contraction_rank"], p["contraction_rows"]) == (18907147, 20148492)
    assert round(result.metadata["success_neglog2"], 3) == 35.000
    rounded_stages = {key: round(bits, 3) for key, bits in result.metadata["stage_log2"].items()}
    assert rounded_stages == {
        "setup": 65.337, "kernel": 113.072, "prepare": 83.057,
        "update": 86.541, "solve": 103.580, "recover": 73.132,
    }


def test_cli_compares_mm_and_zd_mm_and_replays_instance(tmp_path, capsys):
    selection = ["--classical-algorithms", "Rank-MM", "Rank-ZD-MM",
                 "--quantum-algorithms", "--json"]
    assert main(["rank", "--parameter-sets", "BRA-128", "--goal", "key_recovery", *selection]) == 0
    record, = json.loads(capsys.readouterr().out)
    rows = {row["algorithm"]: row for row in record["results"]}
    assert set(rows) == {"Rank-MM", "Rank-ZD-MM"}
    assert round(rows["Rank-MM"]["time_log2"], 1) == 194.6
    assert round(rows["Rank-ZD-MM"]["time_log2"], 3) == 112.088
    assert record["conclusions"]["classical"]["best"] == [rows["Rank-ZD-MM"]]

    path = tmp_path / "instance.json"
    path.write_text(json.dumps(record["instance"]), encoding="utf-8")
    assert main(["estimate", str(path), *selection]) == 0
    replayed, = json.loads(capsys.readouterr().out)
    assert replayed["results"] == record["results"]


def test_web_catalogue_exposes_zd_mm_for_builtin_schemes():
    families = catalogue()["algorithm_families"]
    assert "Rank-ZD-MM" in families["rank_scheme"]
    assert "Rank-ZD-MM" not in families["rank"]


def test_web_preserves_large_minor_counts_in_reports_and_conclusions():
    instance, = rank_instances(parameter_sets=["BRA-512"], goal="key_recovery")
    report = estimate(instance, options=Options(classical_algorithms=("Rank-ZD-MM",), quantum_algorithms=()))
    exact = report.results[0].parameters["variables"]
    assert exact >= 2**53
    record = _finite_json(report.to_dict())
    row, = record["results"]
    assert row["parameters"]["variables"] == str(exact)
    assert row["parameters"]["block"] == 2
    assert record["conclusions"]["classical"]["best"] == [row]
