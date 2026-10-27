"""HTTP contracts, real background estimates, cancellation and local-only access."""

from contextlib import contextmanager
import http.client
import json
import threading
import time
from unittest.mock import Mock

import pytest

from codebased_estimator.web import (
    APIError, EstimatorServer, JobManager, MAX_BODY_BYTES, algorithm_availability,
    catalogue, prepare_job,
)


def _slow_worker(connection, instances, options):
    """A process that must be stopped rather than merely hidden by the UI."""
    time.sleep(30)


def _crashing_worker(connection, instances, options):
    connection.close()


def custom_request(**changes):
    return {
        "mode": "custom",
        "instance": {"name": "web-test", "goal": "msg_recovery", "problem": {
            "kind": "sd", "parameters": {"n": 40, "k": 20, "w": 4},
            "log2_solutions": 0,
        }},
        "options": {"classical_algorithms": ["Prange"], "quantum_algorithms": []},
        **changes,
    }


def availability_for(data):
    return algorithm_availability(*prepare_job(data))


@contextmanager
def running_server(tmp_path, manager=None):
    assets = tmp_path / "web_assets"
    assets.mkdir(exist_ok=True)
    (assets / "index.html").write_text("<!doctype html><title>Estimator</title>", encoding="utf-8")
    (tmp_path / "private.txt").write_text("private data", encoding="utf-8")
    server = EstimatorServer(("127.0.0.1", 0), assets=assets, manager=manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def request(server, method, path, data=None, headers=None, raw=None):
    connection = http.client.HTTPConnection(*server.server_address, timeout=5)
    body = json.dumps(data).encode() if data is not None else raw
    supplied_headers = {"Content-Type": "application/json"} if body is not None else {}
    supplied_headers.update(headers or {})
    try:
        connection.request(method, path, body=body, headers=supplied_headers)
        response = connection.getresponse()
        payload = response.read()
        result = json.loads(payload) if response.getheader("Content-Type", "").startswith("application/json") else payload
        return response.status, result, dict(response.getheaders())
    finally:
        connection.close()


def wait_for_job(server, job_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status, job, _ = request(server, "GET", f"/api/jobs/{job_id}")
        assert status == 200
        if job["status"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.03)
    pytest.fail("Background job did not finish")


def test_catalogue_and_route_preview_preserve_domain_provenance(tmp_path):
    with running_server(tmp_path) as server:
        status, data, _ = request(server, "GET", "/api/catalogue")
        assert status == 200
        assert data["limits"]["job_seconds"] is None
        assert "Mito" in data["schemes"]
        assert data["algorithms"]["quantum"] == ["QPrange", "QSS", "QMMT+"]
        assert "Prange" in data["algorithm_families"]["binary"]
        assert "MAGE-Stern" in data["algorithm_families"]["binary"]
        selected = next(row for row in data["parameter_sets"] if row["scheme"] == "HARE")
        status, preview, _ = request(server, "GET", "/api/routes?scheme=HARE&parameter_set="
                                     + selected["parameter_set"] + "&goal=msg_recovery&unbalanced=none")
        assert status == 200
        assert [item["route_id"] for item in preview["instances"]] == ["u_only", "composite"]
        assert all(item["block_profile"] is None for item in preview["instances"])
        assert all(item["assumptions"] and item["references"] for item in preview["instances"])
        assert preview["instances"][1]["problem"]["parameters"]["n"] == 3 * selected["parameters"]["r"]


def test_http_runs_real_estimator_and_returns_comparisons(tmp_path):
    with running_server(tmp_path) as server:
        status, started, _ = request(server, "POST", "/api/jobs", custom_request())
        assert status == 202
        job = wait_for_job(server, started["id"])
        assert job["status"] == "completed", job
        assert job["progress"] == {"completed": 1, "total": 1}
        report, = job["reports"]
        result, = report["results"]
        assert result["algorithm"] == "Prange" and result["status"] == "computed"
        assert result["time_log2"] > 0 and result["memory_log2"] > 0
        assert result["time_unit"] == "bit_operations"
        assert report["conclusions"]["quantum"]["status"] == "not_requested"
        comparison, = job["comparisons"]
        assert comparison["conclusions"]["classical"]["best"][0]["estimate"] == result
        status, unchanged, _ = request(server, "DELETE", f"/api/jobs/{started['id']}")
        assert status == 200 and unchanged["status"] == "completed"


@pytest.mark.parametrize("block", [False, True])
def test_http_qprange_job_matches_the_shared_backend(tmp_path, block):
    from codebased_estimator import estimate

    body = custom_request(options={"classical_algorithms": [], "quantum_algorithms": ["QPrange"]})
    if block:
        body["instance"]["block_profile"] = {"lengths": [20, 20], "weights": [1, 3]}
    instances, options = prepare_job(body)
    expected, = estimate(instances[0], options=options).results
    with running_server(tmp_path) as server:
        status, preview, _ = request(server, "POST", "/api/availability", body)
        assert status == 200 and preview["availability"]["quantum"]["QPrange"]["available"]
        status, started, _ = request(server, "POST", "/api/jobs", body)
        assert status == 202
        job = wait_for_job(server, started["id"])
        assert job["status"] == "completed", job
        result, = job["reports"][0]["results"]
        assert result["algorithm"] == "QPrange" and result["status"] == "computed"
        assert result["time_log2"] == expected.time_log2
        assert result["time_unit"] == "quantum_bit_operations"
        assert result["memory_log2"] is None and result["memory_unit"] == "not_estimated"
        if block:
            assert result["metadata"]["unbalanced"] == json.loads(json.dumps(expected.metadata["unbalanced"]))


def test_qprange_preflight_stops_before_finite_cost_evaluation(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Preflight evaluated QPrange finite costs")

    monkeypatch.setattr("codebased_estimator.qprange.evaluate_qprange", forbidden)
    body = custom_request(options={"classical_algorithms": [], "quantum_algorithms": ["QPrange"]})
    assert availability_for(body)["quantum"]["QPrange"]["available"]
    body["instance"].update(tags=["doom:qcsd"], targets=8)
    assert availability_for(body)["quantum"]["QPrange"]["available"]
    body["instance"].update(tags=["doom:qccf"])
    body["instance"]["problem"]["kind"] = "cfp"
    body["instance"]["problem"].pop("log2_solutions")
    assert not availability_for(body)["quantum"]["QPrange"]["available"]


def test_block_qprange_preflight_retains_native_profile_and_guards(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Preflight evaluated block QPrange finite costs")

    monkeypatch.setattr("codebased_estimator.qprange.evaluate_qprange", forbidden)
    body = custom_request(options={"classical_algorithms": [], "quantum_algorithms": ["QPrange"]})
    body["instance"]["block_profile"] = {"lengths": [20, 20], "weights": [1, 3]}
    assert availability_for(body)["quantum"]["QPrange"]["available"]
    body["instance"].update(tags=["doom:qcsd"], targets=8)
    assert availability_for(body)["quantum"]["QPrange"]["available"]
    body["instance"]["structure"] = ["truncated"]
    assert not availability_for(body)["quantum"]["QPrange"]["available"]


def test_both_goals_preview_and_job_keep_distinct_comparisons(tmp_path):
    selected = next(row for row in catalogue()["parameter_sets"] if row["scheme"] == "HARE")
    body = {"mode": "catalogue", "scheme": "HARE", "parameter_set": selected["parameter_set"],
            "goal": "both", "options": {"classical_algorithms": [], "quantum_algorithms": ["QPrange"]}}
    with running_server(tmp_path) as server:
        status, preview, _ = request(server, "GET", "/api/routes?scheme=HARE&parameter_set="
                                     + selected["parameter_set"] + "&goal=both")
        assert status == 200
        assert [item["goal"] for item in preview["instances"]] == [
            "key_recovery", "msg_recovery", "msg_recovery"]
        status, started, _ = request(server, "POST", "/api/jobs", body)
        assert status == 202
        job = wait_for_job(server, started["id"])
        assert job["status"] == "completed", job
        assert job["progress"] == {"completed": 3, "total": 3}
        assert [report["instance"] for report in job["reports"]] == preview["instances"]
        assert [comparison["goal"] for comparison in job["comparisons"]] == ["key_recovery", "msg_recovery"]


def test_whole_scheme_jobs_keep_parameter_sets_and_goals_separate(tmp_path):
    parameter_sets = [row["parameter_set"] for row in catalogue()["parameter_sets"] if row["scheme"] == "QCTM"]
    body = {"mode": "catalogue", "scope": "scheme", "scheme": "QCTM", "goal": "both",
            "options": {"classical_algorithms": ["Prange"], "quantum_algorithms": []}}
    with running_server(tmp_path) as server:
        status, preview, _ = request(server, "GET", "/api/routes?scope=scheme&scheme=QCTM&goal=both")
        assert status == 200
        identities = [(parameter_set, goal) for parameter_set in parameter_sets
                      for goal in ("key_recovery", "msg_recovery")]
        assert [(item["parameter_set"], item["goal"]) for item in preview["instances"]] == identities
        assert preview["availability"]["classical"]["Prange"]["available"]
        assert "3 of 6" in preview["availability"]["classical"]["Prange"]["reason"]
        assert preview["availability"]["quantum"]["QPrange"]["available"]
        assert "3 of 6" in preview["availability"]["quantum"]["QPrange"]["reason"]
        status, started, _ = request(server, "POST", "/api/jobs", body)
        assert status == 202
        job = wait_for_job(server, started["id"])
        assert job["status"] == "completed", job
        assert job["progress"] == {"completed": len(identities), "total": len(identities)}
        assert [(item["parameter_set"], item["goal"]) for item in job["comparisons"]] == identities
        assert all(report["results"][0]["status"] == (
            "not_implemented" if report["instance"]["goal"] == "key_recovery" else "computed")
            for report in job["reports"])


def test_availability_never_runs_parameter_optimization(monkeypatch):
    from cryptographic_estimators.base_algorithm import BaseAlgorithm

    def forbidden(*args, **kwargs):
        pytest.fail("Preflight attempted parameter optimization")

    for name in ("time_complexity", "memory_complexity", "_find_optimal_parameters", "get_optimal_parameters_dict"):
        monkeypatch.setattr(BaseAlgorithm, name, forbidden)
    for target in ("codebased_estimator.quantum.optimize", "codebased_estimator.mage_search.optimize",
                   "codebased_estimator.classical_doom.estimate_doom", "codebased_estimator.backend._seed_bounded_m4ri",
                   "codebased_estimator.qprange.evaluate_qprange"):
        monkeypatch.setattr(target, forbidden)
    for scheme in catalogue()["schemes"]:
        availability = availability_for({"scope": "scheme", "scheme": scheme, "goal": "both"})
        assert any(item["available"] for item in availability["classical"].values())
    rank = custom_request()
    rank["instance"]["problem"] = {"kind": "rank_sd", "parameters": {"n": 40, "k": 20, "m": 10, "r": 3, "q": 2}}
    assert availability_for(rank)["classical"]["GRS"]["available"]


def test_custom_preflight_accepts_empty_selection_and_retains_validation(tmp_path):
    data = custom_request(options={"classical_algorithms": [], "quantum_algorithms": []})
    with running_server(tmp_path) as server:
        status, preview, _ = request(server, "POST", "/api/availability", data)
        assert status == 200
        assert preview["availability"]["classical"]["Prange"]["available"]
        assert preview["availability"]["classical"]["MAGE-Stern"]["available"]
        assert preview["availability"]["quantum"]["QSS"]["available"]
        assert preview["availability"]["quantum"]["QPrange"]["available"]
        assert server.jobs._jobs == {}
        data["instance"]["problem"]["parameters"]["k"] = 100
        status, error, _ = request(server, "POST", "/api/availability", data)
        assert status == 400 and "error" in error


def test_rejected_qcsd_constructor_never_reaches_doom_optimizer(monkeypatch):
    from types import SimpleNamespace
    from codebased_estimator.backend import ClassicalModel

    original_resolve = ClassicalModel._resolve

    def rejected_resolve(cls, problem):
        resolved = original_resolve(problem)
        if resolved is None:
            return None
        family, parameters, _, all_classes, candidates = resolved
        return (family, parameters, lambda **kwargs: SimpleNamespace(algorithms=lambda: []),
                all_classes, candidates)

    def forbidden(*args, **kwargs):
        pytest.fail("Rejected QCSD constructor reached target-aware optimization")

    monkeypatch.setattr(ClassicalModel, "_resolve", classmethod(rejected_resolve))
    monkeypatch.setattr("codebased_estimator.classical_doom.estimate_doom", forbidden)
    monkeypatch.setattr("codebased_estimator.backend._with_bjmm_depth3_candidate", forbidden)
    data = custom_request()
    data["instance"].update(tags=["doom:qcsd"], targets=4)
    availability = availability_for(data)
    for name in ("Prange", "Stern", "Dumer", "BJMM"):
        assert not availability["classical"][name]["available"]
        reason = availability["classical"][name]["reason"].lower()
        assert "upstream" in reason and "reject" in reason


@pytest.mark.parametrize("kind,parameters,expected_classical", [
    ("sd", {"n": 40, "k": 20, "w": 4, "q": 3}, {"Prange", "Stern", "LeeBrickell"}),
    ("rank_sd", {"n": 40, "k": 20, "m": 10, "r": 3, "q": 2}, None),
])
def test_availability_excludes_wrong_families_and_quantum(kind, parameters, expected_classical):
    data = custom_request()
    data["instance"]["problem"] = {"kind": kind, "parameters": parameters}
    availability = availability_for(data)
    supported = {name for name, item in availability["classical"].items() if item["available"]}
    if expected_classical is not None:
        assert supported == expected_classical
    else:
        assert "GRS" in supported and "Prange" not in supported
    assert not any(item["available"] for item in availability["quantum"].values())
    assert not availability["classical"]["MAGE-Stern"]["available"]


@pytest.mark.parametrize("solution_count,block_profile", [
    (2, None),
    (None, None),
    (None, {"lengths": [20, 20], "weights": [2, 3]}),
])
def test_mage_preflight_matches_explicit_default_and_block_solution_guards(solution_count, block_profile):
    data = custom_request()
    data["instance"]["problem"] = {"kind": "sd", "parameters": {"n": 40, "k": 30, "w": 5},
                                    "log2_solutions": solution_count}
    data["instance"]["block_profile"] = block_profile
    availability = availability_for(data)
    assert not availability["classical"]["MAGE-Stern"]["available"]
    assert "solution" in availability["classical"]["MAGE-Stern"]["reason"]
    assert availability["classical"]["Prange"]["available"]
    data["instance"]["problem"]["log2_solutions"] = 0
    assert availability_for(data)["classical"]["MAGE-Stern"]["available"]


def test_preflight_rejects_unknown_structures_and_preserves_quantum_qcsd_fallback():
    data = custom_request()
    data["instance"].update(tags=["doom:qcsd"], targets=4)
    availability = availability_for(data)
    assert availability["quantum"]["QSS"]["available"]
    assert availability["classical"]["MAGE-Stern"]["available"]
    data["instance"]["structure"] = ["shared support"]
    availability = availability_for(data)
    assert not any(item["available"] for family in availability.values() for item in family.values())


def test_qccf_preflight_respects_quantum_profile_orbit_guard():
    data = custom_request()
    data["instance"].update(tags=["doom:qccf"], targets=2, block_profile={
        "lengths": [20, 20], "weights": [1, 3], "target_permutations": [[0, 1], [1, 0]]})
    data["instance"]["problem"]["kind"] = "cfp"
    del data["instance"]["problem"]["log2_solutions"]
    availability = availability_for(data)
    assert not availability["quantum"]["QSS"]["available"]
    assert "block-weight profiles" in availability["quantum"]["QSS"]["reason"]
    assert availability["classical"]["Prange"]["available"]
    assert availability["classical"]["MAGE-Stern"]["available"]
    data["unbalanced"] = "none"
    assert availability_for(data)["quantum"]["QSS"]["available"]


def test_unsupported_scheme_goal_has_no_selectable_algorithms(tmp_path):
    with running_server(tmp_path) as server:
        for scheme in ("QCTM", "UVW-KEM"):
            status, preview, _ = request(server, "GET", f"/api/routes?scope=scheme&scheme={scheme}&goal=key_recovery")
            assert status == 200
            assert not any(item["available"] for family in preview["availability"].values() for item in family.values())


def test_catalogue_scope_validation_and_backward_compatible_default():
    defaults = catalogue()["defaults"]
    single, _ = prepare_job(defaults)
    old_request = {key: value for key, value in defaults.items() if key != "scope"}
    assert prepare_job(old_request)[0] == single
    with pytest.raises(ValueError, match="scope must"):
        prepare_job({**defaults, "scope": "unknown"})
    with pytest.raises(ValueError, match="parameter_set must"):
        prepare_job({"scheme": defaults["scheme"], "goal": "both"})
    all_sets, _ = prepare_job({"scheme": defaults["scheme"], "goal": "both", "scope": "scheme"})
    assert len({item.parameter_set for item in all_sets}) > 1


def test_cancellation_stops_process_and_releases_capacity(tmp_path):
    manager = JobManager(max_active=1, worker=_slow_worker)
    with running_server(tmp_path, manager) as server:
        _, started, _ = request(server, "POST", "/api/jobs", custom_request())
        process = manager._jobs[started["id"]]["process"]
        assert process.is_alive()
        status, rejected, _ = request(server, "POST", "/api/jobs", custom_request())
        assert status == 429 and "busy" in rejected["error"]
        status, cancelled, _ = request(server, "DELETE", f"/api/jobs/{started['id']}")
        assert status == 200 and cancelled["status"] == "cancelled"
        assert not process.is_alive()
        assert cancelled["progress"]["completed"] == 0
        status, second, _ = request(server, "POST", "/api/jobs", custom_request())
        assert status == 202 and second["id"] != started["id"]
    assert not manager._jobs[second["id"]]["process"].is_alive()


def test_failed_workers_are_reported(tmp_path):
    manager = JobManager(worker=_crashing_worker)
    with running_server(tmp_path, manager) as server:
        _, started, _ = request(server, "POST", "/api/jobs", custom_request())
        job = wait_for_job(server, started["id"])
        assert job["status"] == "failed" and "exited unexpectedly" in job["error"]


def test_long_running_batch_can_finish_without_a_deadline(monkeypatch):
    manager = JobManager()
    reports = [{"name": "first route"}, {"name": "second route"}]
    comparisons = [{"best_route": "second route"}]
    receiver = Mock()
    receiver.poll.side_effect = [False, True, False, True, True]
    receiver.recv.side_effect = [
        *({"type": "report", "report": report} for report in reports),
        {"type": "complete", "comparisons": comparisons},
    ]
    process = Mock()
    process.is_alive.return_value = True
    stop = Mock()
    monkeypatch.setattr(manager, "_stop_process", stop)
    data = {"status": "running", "reports": [], "comparisons": [],
            "progress": {"completed": 0, "total": 2}}
    # Reproduce a job older than the former 30-minute cutoff without waiting.
    job = {"data": data, "process": process, "receiver": receiver,
           "started": time.monotonic() - 3601}
    manager._monitor(job)
    assert data["status"] == "completed" and "error" not in data
    assert data["reports"] == reports and data["comparisons"] == comparisons
    assert data["progress"] == {"completed": 2, "total": 2}
    receiver.close.assert_called_once()
    stop.assert_called_once_with(process)


def test_completed_job_history_is_bounded():
    manager = JobManager(max_stored=1, worker=_slow_worker)
    instances, options = prepare_job(custom_request())
    try:
        first = manager.submit(instances, options)
        manager.cancel(first["id"])
        second = manager.submit(instances, options)
        assert len(manager._jobs) == 1
        with pytest.raises(APIError, match="Job not found"):
            manager.get(first["id"])
        assert manager.get(second["id"])["status"] == "running"
    finally:
        manager.close()


@pytest.mark.parametrize("changes,message", [
    ({"options": {"classical_algorithms": ["UnknownAlgorithm"]}}, "Unknown classical"),
    ({"options": {"quantum_algorithms": ["UnknownAlgorithm"]}}, "Unknown quantum"),
    ({"options": {"classical_algorithms": [], "quantum_algorithms": []}}, "at least one"),
    ({"options": {"memory_bound_log2_bits": -1}}, "nonnegative"),
    ({"options": {"quantum_matrix_profile": "missing"}}, "matrix profile"),
    ({"unbalanced": "invalid"}, "unbalanced"),
    ({"mode": "missing"}, "mode must"),
    ({"extra": "unused"}, "Unknown request"),
])
def test_invalid_jobs_are_rejected_before_worker_creation(tmp_path, changes, message):
    with running_server(tmp_path) as server:
        status, result, _ = request(server, "POST", "/api/jobs", custom_request(**changes))
        assert status == 400 and message in result["error"]
        assert server.jobs._jobs == {}


def test_invalid_parameter_set_and_oversized_dimensions():
    defaults = catalogue()["defaults"]
    with pytest.raises(ValueError, match="Unknown parameter set"):
        prepare_job({"mode": "catalogue", **defaults, "parameter_set": "missing"})
    data = custom_request()
    data["instance"]["problem"]["parameters"]["n"] = 1_000_001
    with pytest.raises(ValueError, match="exceeds the web limit"):
        prepare_job(data)


def test_static_paths_headers_origin_and_host_are_constrained(tmp_path):
    with running_server(tmp_path) as server:
        status, page, headers = request(server, "GET", "/")
        assert status == 200 and b"Estimator" in page
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        for path in ("/../private.txt", "/%2e%2e/private.txt", "/%2e%2e/pyproject.toml", "/api/jobs/missing"):
            status, result, _ = request(server, "GET", path)
            assert status == 404 and "error" in result
        for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"},
                        {"Sec-Fetch-Site": "cross-site"}):
            status, result, _ = request(server, "POST", "/api/jobs", custom_request(), headers=headers)
            assert status == 403 and "error" in result
        assert server.jobs._jobs == {}
        local_origin = "http://127.0.0.1:" + str(server.server_address[1])
        status, _, _ = request(server, "GET", "/api/catalogue", headers={"Origin": local_origin})
        assert status == 200


def test_json_protocol_rejects_invalid_and_oversized_payloads(tmp_path):
    with running_server(tmp_path) as server:
        cases = [
            (b"{", {}, 400),
            (b"{\"options\": NaN}", {}, 400),
            (b"{}", {"Content-Type": "text/plain"}, 415),
            (b"{}", {"Content-Length": str(MAX_BODY_BYTES + 1)}, 413),
            (b"{}", {"Transfer-Encoding": "chunked"}, 400),
        ]
        for body, headers, expected in cases:
            status, result, _ = request(server, "POST", "/api/jobs", raw=body, headers=headers)
            assert status == expected and "error" in result


def test_server_rejects_nonloopback_binding():
    with pytest.raises(ValueError, match="must bind"):
        EstimatorServer(("0.0.0.0", 8000))
