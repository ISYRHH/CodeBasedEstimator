"""Mito parity route integration, proxy disclosure, and backend boundaries."""

import csv
from dataclasses import asdict, replace
import io
import json

import pytest

from codebased_estimator import AttackInstance, Options, Problem, compare_routes, estimate
from codebased_estimator.__main__ import main
from codebased_estimator.hamming import HammingScheme


# Independently transcribed from the reviewed sampler parameters, not derived
# from the route implementation (including the corrected 32261 ring length).
EXPECTED = {
    "Mito-1-128": (61492, 30744, 172, 2),
    "Mito-1-256": (135308, 67652, 269, 2),
    "Mito-1-512": (425044, 212520, 527, 2),
    "Mito-1-E-128": (58484, 29240, 172, 2),
    "Mito-1-E-256": (129044, 64520, 269, 2),
    "Mito-1-E-512": (409748, 204872, 527, 2),
    "Mito-2-E-128": (82024, 41008, 186, 4),
    "Mito-2-E-256": (172184, 86088, 284, 4),
    "Mito-2-E-512": (522344, 261168, 544, 4),
}


@pytest.mark.parametrize("parameter_set,expected", EXPECTED.items())
@pytest.mark.parametrize("doom", ["auto", "none"])
def test_all_mito_key_routes_preserve_source_and_add_only_independent_parities(parameter_set, expected, doom):
    n, k, w, d = expected
    baseline, parity = HammingScheme("Mito").instances(parameter_set, "key_recovery", doom=doom)
    assert [baseline.route_id, parity.route_id] == ["baseline", "parity"]
    assert baseline.problem.parameters == {"n": n, "k": k + d, "w": w, "q": 2}
    assert parity.problem.parameters == {"n": n, "k": k, "w": w, "q": 2}
    assert baseline.problem.log2_solutions == parity.problem.log2_solutions == 0
    assert baseline.targets == parity.targets == (n // 2 if doom == "auto" else 1)
    assert baseline.tags == parity.tags == (("doom:qcsd",) if doom == "auto" else ())
    assert parity.structure == ()  # The input Problem is explicitly the random SD proxy.
    assert baseline.cost_proxy is None
    descriptor = parity.cost_proxy
    assert descriptor["effective_parameters"] == parity.problem.parameters
    assert descriptor["baseline_parameters"] == baseline.problem.parameters
    assert descriptor["source_targets"] == parity.targets
    assert descriptor["constraints"]["added_rank"] == d
    assert descriptor["constraints"]["augmented_rank"] == n - k
    assert descriptor["constraints"]["doom"]["requires_permuted_parity_rhs"] is True
    assert descriptor["heuristic"] is True
    assert "random" in descriptor["effective_model"]
    assert "not a dedicated structured P attack" in descriptor["scope"]
    assert AttackInstance.from_dict(json.loads(json.dumps(asdict(parity), allow_nan=False))) == parity


@pytest.fixture
def small_mito(monkeypatch):
    monkeypatch.setattr("codebased_estimator.hamming.HAMMING_PARAMETERS", [{
        "scheme": "Mito", "parameter_set": "small", "parameters": {
            "r": 7, "d": 2, "wx": [1, 2], "wy": [2, 1],
            "wr": [1, 1], "wt": [1, 1], "we": 1,
        }, "references": ["synthetic parity integration parameters"],
    }])
    return HammingScheme("Mito")


@pytest.mark.parametrize("doom", ["auto", "none"])
def test_parity_cost_is_the_declared_proxy_without_additional_discounts(small_mito, doom):
    options = Options(classical_algorithms=("Prange", "Stern"), quantum_algorithms=("QSS", "QMMT+"))
    baseline, parity = small_mito.instances("small", "key_recovery", doom=doom)
    direct = AttackInstance("direct random SD", "key_recovery", parity.problem,
                            targets=parity.targets, tags=parity.tags)
    report = estimate(parity, options=options)
    assert report.results == estimate(direct, options=options).results
    assert all(row.status == "computed" for row in report.results)
    if doom == "auto":
        for row in report.results:
            if row.model == "quantum":
                assert row.metadata["effective_targets"] == 1
                assert row.metadata["doom"]["model"] == "single_target_fallback"
    comparison = compare_routes([estimate(baseline, options=options), report])[0]
    for family in ("classical", "quantum"):
        assert comparison.conclusions[family].best
        assert all(best.route_id in ("baseline", "parity") for best in comparison.conclusions[family].best)


@pytest.mark.parametrize("extra", [{"structure": ("unknown constraints",)}, {"tags": ("unknown",)}])
def test_cost_proxy_metadata_does_not_bypass_structure_or_tag_rejection(small_mito, extra):
    parity = small_mito.instances("small", "key_recovery", doom="none")[1]
    report = estimate(replace(parity, **extra), options=Options(
        classical_algorithms=("Prange",), quantum_algorithms=("QSS",)))
    assert all(row.status == "not_implemented" for row in report.results)


@pytest.mark.parametrize("proxy", [[], "proxy", {"gain": float("inf")}, {"gain": float("nan")},
                                   {"object": object()}, {"name": []}, {"name": {}}, {"name": " "}])
def test_proxy_provenance_requires_finite_json_data(proxy):
    with pytest.raises(ValueError, match="cost_proxy"):
        AttackInstance("invalid", "key_recovery", Problem("sd", {"n": 40, "k": 20, "w": 4}), cost_proxy=proxy)


def test_proxy_provenance_copies_nested_input():
    data = {"source": {"weights": [1, 2]}}
    instance = AttackInstance("copy", "key_recovery", Problem("sd", {"n": 40, "k": 20, "w": 4}), cost_proxy=data)
    data["source"]["weights"][0] = 100
    assert instance.cost_proxy["source"]["weights"] == [1, 2]


def test_cli_target_override_keeps_source_provenance_separate(small_mito, capsys, tmp_path):
    path = tmp_path / "parity.json"
    path.write_text(json.dumps(asdict(small_mito.instances("small", "key_recovery")[1])))
    assert main(["estimate", str(path), "--targets", "3",
                 "--classical-algorithms", "Prange", "--quantum-algorithms", "--json"]) == 0
    parity = json.loads(capsys.readouterr().out)[0]
    assert parity["instance"]["targets"] == 3
    assert parity["instance"]["cost_proxy"]["source_targets"] == 14
    assert parity["results"][0]["metadata"]["targets"] == 3


@pytest.mark.parametrize("format", ["text", "details", "no-brief", "json", "csv", "list"])
def test_parity_comparison_stays_visible_with_proxy_provenance_in_structured_output(small_mito, capsys, format):
    args = ["hamming", "--schemes", "Mito", "--goal", "key_recovery",
            "--classical-algorithms", "Prange", "--quantum-algorithms"]
    if format != "text":
        args.append("--list-routes" if format == "list" else f"--{format}")
    assert main(args) == 0
    output = capsys.readouterr().out
    if format == "json":
        records = json.loads(output)
        assert [r["instance"]["route_id"] for r in records] == ["baseline", "parity"]
        assert records[0]["route_comparison"] == records[1]["route_comparison"]
        assert AttackInstance.from_dict(records[1]["instance"]).cost_proxy
    elif format == "csv":
        records = list(csv.DictReader(io.StringIO(output)))
        assert {r["route_id"] for r in records} == {"baseline", "parity"}
        assert any(r["is_best_route"] == "True" for r in records)
        assert records[1]["cost_proxy"] == "mito-key-parity-rank-v1"
    else:
        assert "parity" in output
        assert "mito-key-parity-rank-v1" not in output
        assert "Cost proxy:" not in output
        assert "heuristic random-SD cost" not in output
        if format != "list":
            assert "Best classical route:" in output
