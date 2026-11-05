"""Official HQC inputs, conditional route scope and the browser job contract."""

import json

import pytest

from codebased_estimator import AttackInstance
from codebased_estimator.__main__ import main
from codebased_estimator.hamming import hamming_catalogue, hamming_instances
from codebased_estimator.web import prepare_job
from test_web import request, running_server, wait_for_job


# Specification 2026-10-12, Table 8. Its n2 is in bytes, whereas this
# catalogue follows the existing Hamming convention of bit lengths.
PARAMETERS = [
    (1, 17669, 46, 48, 17664, 128, 67, 76),
    (3, 35851, 56, 80, 35840, 192, 101, 114),
    (5, 57637, 90, 80, 57600, 256, 132, 150),
]


@pytest.mark.parametrize("level,r,n1,n2_bytes,length,message,w,wr", PARAMETERS)
def test_hqc_source_snapshot_distinguishes_bits_bytes_and_ring_length(
        level, r, n1, n2_bytes, length, message, w, wr):
    entry = next(row for row in hamming_catalogue()
                 if row["parameter_set"] == f"HQC-{level}")
    assert entry["scheme"] == "HQC" and entry["usage"] == "example"
    assert entry["parameters"] == {
        "r": r, "w": w, "wr": wr, "we": wr, "n1": n1, "n2": n2_bytes * 8,
        "code_length": length, "message_bits": message,
    }
    assert length == n1 * n2_bytes * 8 and message < length < r
    assert "2026-10-12, Table 8" in " ".join(entry["references"])
    assert f"{n2_bytes} bytes" in " ".join(entry["notes"])


@pytest.mark.parametrize("doom", ["auto", "none"])
@pytest.mark.parametrize("unbalanced", ["auto", "none"])
def test_hqc_configuration_preserves_conditional_scope_and_block_weights(doom, unbalanced):
    routes = hamming_instances(schemes=["HQC"], parameter_sets=["HQC-1"],
                               doom=doom, unbalanced=unbalanced)
    key, u_only, composite = routes
    assert [instance.route_id for instance in routes] == [None, "u_only", "composite"]
    assert composite.problem.parameters == {"n": 53007, "k": 17669, "w": 228, "q": 2}
    assert "Conditional full-length known-mask core" in composite.route
    key_notes, u_notes, c_notes = [" ".join(instance.assumptions) for instance in routes]
    assert "compressed seedKEM is not modeled" in key_notes
    assert "public concatenated-code decoding" in u_notes
    assert "postprocessing cost is not included" in u_notes
    assert "missing r-L tail" in c_notes and "message mask Encode(m)" in c_notes
    assert "supplied for free" in c_notes
    assert "not a DOOM orbit of the actual truncated unknown-message ciphertext" in c_notes
    for instance, weights in zip(routes, [(67, 67), (76, 76), (76, 76, 76)]):
        assert "Estimator example" in " ".join(instance.assumptions)
        assert instance.targets == (17669 if doom == "auto" else 1)
        assert instance.tags == (("doom:qcsd",) if doom == "auto" else ())
        assert instance.problem.log2_solutions == 0
        if unbalanced == "auto":
            assert instance.block_profile.lengths == (17669,) * len(weights)
            assert instance.block_profile.weights == weights
        else:
            assert instance.block_profile is None


def test_hqc_cli_lists_example_inputs_and_all_routes(capsys):
    assert main(["hamming", "--schemes", "HQC", "--list", "--json"]) == 0
    entries = json.loads(capsys.readouterr().out)
    assert {entry["parameter_set"] for entry in entries} == {"HQC-1", "HQC-3", "HQC-5"}
    assert all(entry["usage"] == "example" for entry in entries)
    assert main(["hamming", "--schemes", "HQC", "--list-routes", "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert len(records) == 9 and len({record["name"] for record in records}) == 9
    assert {record["scheme"] for record in records} == {"HQC"}
    assert sum(record["route_id"] == "composite" for record in records) == 3
    assert {record["parameter_set"] for record in records} == {"HQC-1", "HQC-3", "HQC-5"}


def test_hqc_whole_scheme_web_selection_includes_both_goals():
    instances, _ = prepare_job({"scheme": "HQC", "scope": "scheme", "goal": "both"})
    assert len(instances) == 9
    assert {instance.parameter_set for instance in instances} == {"HQC-1", "HQC-3", "HQC-5"}
    assert sum(instance.goal == "key_recovery" for instance in instances) == 3
    assert sum(instance.goal == "msg_recovery" for instance in instances) == 6


def test_hqc_http_preview_and_background_job_compute_classical_and_quantum_costs(tmp_path):
    body = {
        "scheme": "HQC", "parameter_set": "HQC-1", "goal": "both",
        "doom": "none", "unbalanced": "none",
        "options": {"classical_algorithms": ["Prange"], "quantum_algorithms": ["QPrange"]},
    }
    expected_instances, _ = prepare_job(body)
    with running_server(tmp_path) as server:
        status, catalogue, _ = request(server, "GET", "/api/catalogue")
        assert status == 200 and "HQC" in catalogue["schemes"]
        entries = [entry for entry in catalogue["parameter_sets"] if entry["scheme"] == "HQC"]
        assert len(entries) == 3 and all(entry["usage"] == "example" for entry in entries)
        status, preview, _ = request(
            server, "GET", "/api/routes?scheme=HQC&parameter_set=HQC-1&goal=both&doom=none&unbalanced=none")
        assert status == 200 and len(preview["instances"]) == 3
        assert preview["availability"]["classical"]["Prange"]["available"]
        assert preview["availability"]["quantum"]["QPrange"]["available"]
        status, started, _ = request(server, "POST", "/api/jobs", body)
        assert status == 202
        job = wait_for_job(server, started["id"])
        assert job["status"] == "completed", job
        assert job["progress"] == {"completed": 3, "total": 3}
        assert [AttackInstance.from_dict(report["instance"]) for report in job["reports"]] == expected_instances
        for report in job["reports"]:
            results = {result["algorithm"]: result for result in report["results"]}
            assert set(results) == {"Prange", "QPrange"}
            assert all(result["status"] == "computed" and result["time_log2"] > 0
                       for result in results.values())
            assert results["Prange"]["time_unit"] == "bit_operations"
            assert results["QPrange"]["time_unit"] == "quantum_bit_operations"
            assert results["QPrange"]["memory_log2"] is None
        assert len(job["comparisons"]) == 2
        assert all(comparison["conclusions"][family]["status"] == "computed"
                   for comparison in job["comparisons"] for family in ("classical", "quantum"))
        json.dumps(job, allow_nan=False)
