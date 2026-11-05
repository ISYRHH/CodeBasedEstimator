"""Route identities, independent winners, and replayable batch output."""

import csv
import importlib
import io
import json

import pytest

from codebased_estimator import AttackInstance, Estimate, Report
from codebased_estimator.__main__ import main


def test_list_routes_includes_both_candidates_without_costing(monkeypatch, capsys):
    cli = importlib.import_module("codebased_estimator.__main__")
    monkeypatch.setattr(cli, "estimate", lambda *args, **kwargs: pytest.fail("listing ran estimator"))
    assert main(["hamming", "--list-routes", "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert len(records) == 144
    assert len({r["name"] for r in records}) == 144
    assert sum(r["route_id"] == "composite" for r in records) == 35
    assert sum(r["route_id"] == "u_only" for r in records) == 35
    mito = [r for r in records if r["parameter_set"] == "Mito-1-128"]
    assert [r["targets"] for r in mito] == [30746, 30746, 30746, 15373]
    assert [r["route_id"] for r in mito] == ["baseline", "parity", "u_only", "composite"]
    assert mito[1]["cost_proxy"]["name"] == "mito-key-parity-rank-v1"


@pytest.fixture
def different_family_winners(monkeypatch):
    cli = importlib.import_module("codebased_estimator.__main__")

    def estimate(attack, *, options):
        composite = attack.route_id == "composite"
        return Report(attack, options, {}, [
            Estimate("Prange", "classical", "computed", 90 if composite else 100, 30),
            Estimate("QSS", "quantum", "computed", 80 if composite else 70, None,
                     time_unit="quantum_bit_operations", memory_unit="not_estimated",
                     metadata={"resource_scope": "time_only"}),
        ])

    monkeypatch.setattr(cli, "estimate", estimate)
    return ["hamming", "--parameter-sets", "HARE-2", "--goal", "msg_recovery",
            "--classical-algorithms", "Prange", "--quantum-algorithms", "QSS"]


def test_json_retains_both_replayable_routes_and_independent_winners(different_family_winners, capsys):
    assert main([*different_family_winners, "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert len(records) == 2
    assert [AttackInstance.from_dict(r["instance"]).route_id for r in records] == ["u_only", "composite"]
    comparison = records[0]["route_comparison"]
    assert comparison == records[1]["route_comparison"]
    assert comparison["conclusions"]["classical"]["best"][0]["route_id"] == "composite"
    assert comparison["conclusions"]["quantum"]["best"][0]["route_id"] == "u_only"
    assert all(r["conclusions"]["classical"]["best"] for r in records)


def test_csv_marks_cross_route_winners_without_changing_local_best(different_family_winners, capsys):
    assert main([*different_family_winners, "--csv"]) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert len(rows) == 4
    assert all(r["is_best"] == "True" for r in rows)
    winners = {(r["route_id"], r["model"]) for r in rows if r["is_best_route"] == "True"}
    assert winners == {("u_only", "quantum"), ("composite", "classical")}
    assert all(r["instance_name"].endswith(r["route_id"]) for r in rows)


@pytest.mark.parametrize("details", [[], ["--details"], ["--no-brief"]])
def test_text_reports_cross_route_winners(different_family_winners, details, capsys):
    assert main([*different_family_winners, *details]) == 0
    output = capsys.readouterr().out
    assert "Best classical route: composite | Prange" in output
    assert "Best quantum route: u_only | QSS" in output


@pytest.mark.parametrize("scheme,parameters", [
    ("HARE", {"r": 11, "w": 1, "wr": 1, "we": 2}),
    ("HEP-QC", {"r": 11, "w": 1, "wr": 1, "we": 2}),
    ("NSS-HQC", {"r": 11, "wsk": 1, "wr1": 1, "wr2": 1, "we": 2}),
    ("TriQ-KEM", {"r": 11, "wx": 1, "wy": 1, "wr": 1, "we": 2}),
    ("Mito", {"r": 7, "d": 2, "wx": [1, 1], "wy": [1, 1],
              "wr": [1, 1], "wt": [1, 1], "we": 1}),
    ("QUBE", {"r": 11, "wx": 1, "wy": 1, "wf": 1, "wg": 1, "we": 2}),
])
@pytest.mark.parametrize("doom", ["auto", "none"])
def test_both_routes_reach_real_backends_and_compare(scheme, parameters, doom, monkeypatch, capsys):
    monkeypatch.setattr("codebased_estimator.hamming.HAMMING_PARAMETERS", [{
        "scheme": scheme, "parameter_set": "small", "parameters": parameters,
        "references": ["synthetic integration parameters"],
    }])
    assert main(["hamming", "--schemes", scheme, "--goal", "msg_recovery", "--doom", doom,
                 "--classical-algorithms", "Stern", "--quantum-algorithms", "QSS", "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert len(records) == 2
    for record in records:
        assert [r["status"] for r in record["results"]] == ["computed", "computed"]
        assert record["instance"]["problem"]["log2_solutions"] == 0
        if doom == "none":
            assert record["instance"]["targets"] == 1 and record["instance"]["tags"] == []
        else:
            assert record["results"][1]["metadata"]["effective_targets"] == 1
    for family in ("classical", "quantum"):
        minimum = min(r["conclusions"][family]["best"][0]["time_log2"] for r in records)
        best = records[0]["route_comparison"]["conclusions"][family]["best"]
        assert all(r["estimate"]["time_log2"] == minimum for r in best)
