"""Rank catalogue, selection, rendering and replay through the shared CLI."""

import csv
import io
import json

import pytest

from codebased_estimator.__main__ import main


def test_rank_catalogue_listing_does_not_estimate(monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        pytest.fail("Listing must not start an estimator")

    monkeypatch.setattr("codebased_estimator.__main__.estimate", unexpected)
    assert main(["rank", "--list", "--json"]) == 0
    catalogue = json.loads(capsys.readouterr().out)
    assert len(catalogue) == 17
    assert {row["scheme"] for row in catalogue} == {
        "BAG-Loong", "BAG-Piglet", "BRA", "BRQC", "C-Multi-UR-AG",
    }
    assert main(["rank", "--parameter-sets", "BAG-Loong-128", "--list-routes", "--json"]) == 0
    routes = json.loads(capsys.readouterr().out)
    assert len(routes) == 2
    assert {row["goal"] for row in routes} == {"key_recovery", "msg_recovery"}
    assert {row["problem"]["kind"] for row in routes} == {"rank_scheme"}


def test_rank_json_output_and_instance_replay(tmp_path, capsys):
    assert main(["rank", "--parameter-sets", "BAG-Loong-128", "--goal", "key_recovery",
                 "--classical-algorithms", "Rank-OJ", "--progress", "--json"]) == 0
    captured = capsys.readouterr()
    record, = json.loads(captured.out)
    assert "[1/1]" in captured.err
    assert record["options"]["quantum_algorithms"] == []
    row, = record["results"]
    assert row["algorithm"] == "Rank-OJ" and row["status"] == "computed"
    assert row["memory_log2"] is None and row["memory_unit"] == "not_estimated"
    assert record["conclusions"]["classical"]["best"] == [row]
    path = tmp_path / "rank.json"
    path.write_text(json.dumps(record["instance"]))
    assert main(["estimate", str(path), "--classical-algorithms", "Rank-OJ",
                 "--quantum-algorithms", "--json"]) == 0
    replayed, = json.loads(capsys.readouterr().out)
    assert replayed["results"] == record["results"]


def test_rank_csv_keeps_rank_parameters_and_missing_memory(capsys):
    assert main(["rank", "--parameter-sets", "C-Multi-UR-AG-128", "--goal", "key_recovery",
                 "--classical-algorithms", "Rank-OJ", "--csv"]) == 0
    row, = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert row["m"] == "79" and row["r"] == "8"
    assert row["status"] == "computed"
    assert row["memory_log2"] == "" and row["memory_unit"] == "not_estimated"
    assert row["is_best"] == "True"


@pytest.mark.parametrize("bound", [[], ["--memory-bound", "100"]])
def test_rank_text_renders_time_only_conclusion(capsys, bound):
    assert main(["rank", "--parameter-sets", "BAG-Loong-128", "--goal", "key_recovery",
                 "--classical-algorithms", "Rank-OJ", *bound]) == 0
    output = capsys.readouterr().out
    assert "not estimated" in output
    if bound:
        assert "Best classical: -- (unavailable)" in output
        assert "excluded from minima under a memory bound" in output
    else:
        assert "Best classical: Rank-OJ" in output
        assert "memory=not estimated" in output


def test_rank_rejects_parameter_set_from_another_scheme(capsys):
    with pytest.raises(SystemExit) as error:
        main(["rank", "--schemes", "BRA", "--parameter-sets", "BAG-Loong-128", "--list"])
    assert error.value.code == 2
    assert "Unknown parameter sets" in capsys.readouterr().err
