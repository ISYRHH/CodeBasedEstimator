"""Local browser interface with cancellable background estimator jobs.

Run with ``python -m codebased_estimator.web``.  Each evaluation runs in a
separate spawned process, leaving HTTP requests and cancellation responsive.
This is a loopback-only research interface, not a public hosting service.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
import multiprocessing
from pathlib import Path
import threading
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlsplit
import uuid

from .comparison import compare_routes
from .estimator import estimate
from .hamming import GOALS, HAMMING_SCHEMES, HammingScheme, hamming_catalogue
from .matrix_costs import DEFAULT_MATRIX_PROFILE, MATRIX_PROFILES
from .models import AttackInstance, Options, Problem, QUANTUM_ALGORITHMS
from .rank import (RANK_SCHEMES, RANK_GENERIC_ALGORITHMS, RANK_SCHEME_ALGORITHMS,
                   RANK_CLASSICAL_ALGORITHMS, RANK_QUANTUM_ALGORITHMS,
                   RankModel, RankScheme, rank_catalogue)


MAX_BODY_BYTES = 64 * 1024
MAX_ACTIVE_JOBS = 2
MAX_STORED_JOBS = 16
MAX_CUSTOM_DIMENSION = 1_000_000
ASSET_DIRECTORY = Path(__file__).with_name("web_assets")
TERMINAL_STATUSES = frozenset(("completed", "failed", "cancelled"))
DEFAULT_OPTIONS = {
    "classical_algorithms": ["Prange"],
    "quantum_algorithms": [],
    "memory_bound_log2_bits": None,
    "quantum_matrix_profile": DEFAULT_MATRIX_PROFILE,
}


class APIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@lru_cache(maxsize=1)
def _algorithm_families() -> dict[str, list[str]]:
    from .backend import ClassicalModel

    families = {
        key: sorted(ClassicalModel._family_algorithms(family, base)[2])
        for key, family, base in (
            ("binary", "SDEstimator", "SDAlgorithm"),
            ("qary", "SDFqEstimator", "SDFqAlgorithm"),
            ("rank", "RankSDEstimator", "RankSDAlgorithm"),
        )
    }
    families["binary"].extend(ClassicalModel.local_algorithms)
    families["rank"].extend(RANK_GENERIC_ALGORITHMS)
    families["rank_scheme"] = list(RANK_SCHEME_ALGORITHMS)
    return families


def catalogue() -> dict[str, Any]:
    families = _algorithm_families()
    first = hamming_catalogue()[0]
    return {
        "schemes": list(HAMMING_SCHEMES + RANK_SCHEMES),
        "parameter_sets": hamming_catalogue() + rank_catalogue(),
        "algorithms": {
            "classical": sorted({name for names in families.values() for name in names}),
            "quantum": list(QUANTUM_ALGORITHMS + RANK_QUANTUM_ALGORITHMS),
        },
        "algorithm_families": deepcopy(families),
        "matrix_profiles": list(MATRIX_PROFILES),
        "defaults": {
            "scheme": first["scheme"], "parameter_set": first["parameter_set"],
            "scope": "parameter_set",
            "goal": "key_recovery", "doom": "auto", "unbalanced": "auto",
            "options": deepcopy(DEFAULT_OPTIONS),
        },
        "limits": {"active_jobs": MAX_ACTIVE_JOBS, "job_seconds": None,
                   "body_bytes": MAX_BODY_BYTES, "custom_dimension": MAX_CUSTOM_DIMENSION},
    }


def _object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _only_fields(value: dict, allowed: set[str], label: str) -> None:
    unexpected = set(value) - allowed
    if unexpected:
        raise ValueError(f"Unknown {label} fields: {', '.join(sorted(unexpected))}")


def catalogue_instances(data: dict) -> list[AttackInstance]:
    scope = data.get("scope", "parameter_set")
    if scope not in ("parameter_set", "scheme"):
        raise ValueError("scope must be parameter_set or scheme")
    required = ("scheme", "goal", "parameter_set") if scope == "parameter_set" else ("scheme", "goal")
    for key in required:
        if not isinstance(data.get(key), str):
            raise ValueError(f"{key} must be a string")
    is_rank = data["scheme"] in RANK_SCHEMES
    scheme = RankScheme(data["scheme"]) if is_rank else HammingScheme(data["scheme"])
    goals = GOALS if data["goal"] == "both" else (data["goal"],)
    parameter_sets = scheme.parameter_sets if scope == "scheme" else (data["parameter_set"],)
    route_options = {} if is_rank else {
        "doom": data.get("doom", "auto"), "unbalanced": data.get("unbalanced", "auto"),
    }
    return [instance for parameter_set in parameter_sets for goal in goals
            for instance in scheme.instances(parameter_set, goal, **route_options)]


def prepare_job(data: Any, *, require_selection: bool = True) -> tuple[list[AttackInstance], Options]:
    """Validate the complete request before allocating a worker process."""
    data = _object(data, "Request")
    mode = data.get("mode", "catalogue")
    common = {"mode", "unbalanced", "options"}
    if mode == "catalogue":
        _only_fields(data, common | {"scheme", "parameter_set", "goal", "doom", "scope"}, "request")
        instances = catalogue_instances(data)
    elif mode == "custom":
        _only_fields(data, common | {"instance"}, "request")
        if data.get("unbalanced", "auto") not in ("auto", "none"):
            raise ValueError("unbalanced must be auto or none")
        raw = _object(data.get("instance"), "instance")
        problem = _object(raw.get("problem"), "instance.problem")
        kind = problem.get("kind")
        if kind not in ("sd", "rank_sd", "qcsd", "cfp", "qccf"):
            raise ValueError("Custom problem kind must be sd, rank_sd, qcsd, cfp or qccf")
        parameters = _object(problem.get("parameters"), "instance.problem.parameters")
        # Proxy kinds use the same Hamming parameter contract as ordinary SD.
        checked = Problem(kind if kind == "rank_sd" else "sd", parameters,
                          problem.get("log2_solutions"))
        for key, value in checked.parameters.items():
            limit = (1 << 32) if key == "q" else MAX_CUSTOM_DIMENSION
            if value > limit:
                raise ValueError(f"Custom {key} exceeds the web limit of {limit}")
        if type(raw.get("targets", 1)) is not int or not 1 <= raw.get("targets", 1) <= 10**12:
            raise ValueError("Custom targets must be an integer from 1 to 1000000000000")
        instance = AttackInstance.from_dict(raw)
        if data.get("unbalanced", "auto") == "none":
            instance = replace(instance, block_profile=None)
        instances = [instance]
    else:
        raise ValueError("mode must be catalogue or custom")

    supplied_options = _object(data.get("options", {}), "options")
    _only_fields(supplied_options, set(DEFAULT_OPTIONS), "options")
    defaults = dict(DEFAULT_OPTIONS)
    if instances and all(instance.problem.kind == "rank_scheme" for instance in instances):
        defaults["classical_algorithms"] = ["Rank-OJ"]
    options = Options(**{**defaults, **supplied_options})
    allowed = catalogue()["algorithms"]
    for family in ("classical", "quantum"):
        names = getattr(options, f"{family}_algorithms")
        if names is not None and set(names) - set(allowed[family]):
            unknown = ", ".join(sorted(set(names) - set(allowed[family])))
            raise ValueError(f"Unknown {family} algorithms: {unknown}")
    if require_selection and options.classical_algorithms == () and not options.quantum_algorithms:
        raise ValueError("Select at least one classical or quantum algorithm")
    return instances, options


class _AvailableAlgorithm(Exception):
    """Stop a model's guard path before it can optimize or compute any costs."""


@lru_cache(maxsize=1)
def _availability_models():
    """Reuse the actual model guards, with explicit stops before optimization.

    Classical dispatch reaches an upstream constructor only after its tag,
    structure and family checks. Constructors reject inapplicable parameter
    combinations but do not optimize. MAGE has its own solution-count guard.
    Quantum dispatch stops before either finite-cost entry point is evaluated.
    """
    from .backend import ClassicalModel
    from .quantum import QuantumModel

    class ClassicalProbe(ClassicalModel):
        @classmethod
        def _resolve(cls, problem):
            resolved = super()._resolve(problem)
            if resolved is None:
                return None
            family, parameters, estimator_class, all_classes, candidates = resolved

            def constructor_probe(**kwargs):
                estimator = estimator_class(**kwargs)
                if estimator.algorithms():
                    raise _AvailableAlgorithm
                # Stop here even in QCSD recursion: a returned rejection row
                # could otherwise continue into target-aware optimization.
                raise ValueError("The upstream estimator rejected this algorithm for these parameters.")

            return family, parameters, constructor_probe, all_classes, candidates

        def _estimate_mage(self, instance, options):
            problem, reason = self._mage_applicability(instance)
            if reason:
                return self._unsupported("MAGE-Stern", instance, reason)
            if instance.tags != ("doom:qccf",) and problem.log2_solutions is None:
                from cryptographic_estimators.SDEstimator.sd_problem import SDProblem

                p = problem.parameters
                if SDProblem(p["n"], p["k"], p["w"]).nsolutions != 0:
                    return self._unsupported(
                        "MAGE-Stern", instance,
                        "MAGE-Stern supports one solution per syndrome, but the CE default has multiple "
                        "solutions for this instance. Set log2_solutions=0 explicitly to use a single-solution assumption.",
                    )
            raise _AvailableAlgorithm

    class QuantumProbe(QuantumModel):
        def _estimate_time(self, *args, **kwargs):
            raise _AvailableAlgorithm

        def _estimate_prange(self, *args, **kwargs):
            raise _AvailableAlgorithm

    return {"classical": ClassicalProbe(), "quantum": QuantumProbe()}


def algorithm_availability(instances: list[AttackInstance], options: Options) -> dict:
    """Report implemented applicability, never unsearched cost/memory feasibility."""
    models = _availability_models()
    availability = {}
    for family, names in catalogue()["algorithms"].items():
        availability[family] = {}
        for name in names:
            supported = 0
            reasons = []
            for instance in instances:
                if name in RANK_CLASSICAL_ALGORITHMS + RANK_QUANTUM_ALGORITHMS:
                    reason = RankModel().applicability(name, instance)
                    if reason:
                        reasons.append(reason)
                    else:
                        supported += 1
                    continue
                try:
                    result = models[family].estimate_algorithm(name, instance, options)
                except _AvailableAlgorithm:
                    supported += 1
                except (ValueError, TypeError, OverflowError) as exc:
                    reasons.append(str(exc))
                else:
                    reasons.append(result.reason or "This algorithm is not implemented for this route.")
            unique_reasons = list(dict.fromkeys(reasons))
            if supported == len(instances):
                reason = "Available for all selected routes; finite cost and memory feasibility require estimation."
            elif supported:
                reason = f"Available for {supported} of {len(instances)} selected routes. " + " ".join(unique_reasons)
            else:
                reason = " ".join(unique_reasons) or "No supported routes selected."
            availability[family][name] = {"available": supported > 0, "reason": reason}
    return availability


def _finite_json(value: Any) -> Any:
    """Keep unavailable nonfinite metadata JSON-compatible without inventing costs."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(item) for item in value]
    return value


def _evaluate_job(connection, instances: list[AttackInstance], options: Options) -> None:
    try:
        reports = []
        for instance in instances:
            report = estimate(instance, options=options)
            reports.append(report)
            connection.send({"type": "report", "report": _finite_json(report.to_dict())})
        connection.send({"type": "complete", "comparisons": _finite_json(
            [comparison.to_dict() for comparison in compare_routes(reports)])})
    except Exception as exc:
        connection.send({"type": "error", "error": str(exc) or type(exc).__name__})
    finally:
        connection.close()


class JobManager:
    """Bounded in-memory job store; only validated domain objects reach workers."""

    def __init__(self, *, max_active: int = MAX_ACTIVE_JOBS,
                 max_stored: int = MAX_STORED_JOBS, worker=_evaluate_job):
        self.max_active = max_active
        self.max_stored = max_stored
        self.worker = worker
        self._context = multiprocessing.get_context("spawn")
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}
        self._closed = False

    def submit(self, instances: list[AttackInstance], options: Options) -> dict:
        with self._lock:
            if self._closed:
                raise APIError(503, "The estimator is shutting down")
            active = sum(job["data"]["status"] not in TERMINAL_STATUSES
                         for job in self._jobs.values())
            if active >= self.max_active:
                raise APIError(429, "All estimator workers are busy; cancel a job or wait for completion")
            while len(self._jobs) >= self.max_stored:
                oldest = next((key for key, job in self._jobs.items()
                               if job["data"]["status"] in TERMINAL_STATUSES), None)
                if oldest is None:
                    raise APIError(429, "The estimator job store is full")
                del self._jobs[oldest]
            job_id = uuid.uuid4().hex
            receiver, sender = self._context.Pipe(duplex=False)
            process = self._context.Process(target=self.worker, args=(sender, instances, options),
                                            daemon=True, name=f"estimator-{job_id[:8]}")
            data = {"id": job_id, "status": "queued", "progress": {
                "completed": 0, "total": len(instances)}, "reports": [], "comparisons": []}
            job = {"data": data, "process": process, "receiver": receiver}
            self._jobs[job_id] = job
            try:
                process.start()
            except Exception:
                del self._jobs[job_id]
                receiver.close()
                sender.close()
                raise
            sender.close()
            data["status"] = "running"
            monitor = threading.Thread(target=self._monitor, args=(job,), daemon=True,
                                       name=f"estimator-monitor-{job_id[:8]}")
            job["monitor"] = monitor
            monitor.start()
            return {"id": job_id, "status": data["status"]}

    def _monitor(self, job: dict) -> None:
        receiver, process = job["receiver"], job["process"]
        try:
            while True:
                with self._lock:
                    if job["data"]["status"] in TERMINAL_STATUSES:
                        break
                if receiver.poll(0.1):
                    try:
                        message = receiver.recv()
                    except EOFError:
                        break
                    with self._lock:
                        data = job["data"]
                        if data["status"] in TERMINAL_STATUSES:
                            break
                        if message["type"] == "report":
                            data["reports"].append(message["report"])
                            data["progress"]["completed"] = len(data["reports"])
                        elif message["type"] == "complete":
                            data.update(status="completed", comparisons=message["comparisons"])
                        elif message["type"] == "error":
                            data.update(status="failed", error=message["error"])
                elif not process.is_alive():
                    break
        finally:
            self._stop_process(process)
            receiver.close()
            with self._lock:
                if job["data"]["status"] not in TERMINAL_STATUSES:
                    job["data"].update(status="failed", error="The estimator worker exited unexpectedly")

    @staticmethod
    def _stop_process(process) -> None:
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)

    def get(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise APIError(404, "Job not found (completed jobs are retained only in recent history)")
            return deepcopy(job["data"])

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise APIError(404, "Job not found")
            if job["data"]["status"] not in TERMINAL_STATUSES:
                job["data"]["status"] = "cancelled"
                # The monitor owns termination and reaping; wait outside the lock.
            monitor = job["monitor"]
        monitor.join(timeout=3)
        return self.get(job_id)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            identifiers = list(self._jobs)
        for job_id in identifiers:
            self.cancel(job_id)


class EstimatorServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, *, manager: Optional[JobManager] = None,
                 assets: Path = ASSET_DIRECTORY):
        if address[0] not in ("127.0.0.1", "localhost"):
            raise ValueError("The web interface must bind to 127.0.0.1 or localhost")
        self.jobs = manager or JobManager()
        self.assets = Path(assets).resolve()
        super().__init__(address, EstimatorHandler)

    def server_close(self) -> None:
        self.jobs.close()
        super().server_close()


class EstimatorHandler(BaseHTTPRequestHandler):
    server: EstimatorServer
    server_version = "CodeBasedEstimator"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format: str, *args) -> None:
        # Avoid logging attack-instance JSON or untrusted request text.
        pass

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                         "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()

    def _json(self, status: int, data: dict) -> None:
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(payload))
        self.wfile.write(payload)

    def _check_origin(self) -> None:
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1:
            raise APIError(403, "A local Host header is required")
        host = hosts[0].lower()
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed.update(("127.0.0.1", "localhost"))
        if host not in allowed:
            raise APIError(403, "Only local requests are accepted")
        origin = self.headers.get("Origin")
        if origin is not None and origin.lower() != f"http://{host}":
            raise APIError(403, "Cross-origin requests are not accepted")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise APIError(403, "Cross-site requests are not accepted")

    def _body(self) -> Any:
        if self.headers.get("Transfer-Encoding"):
            raise APIError(400, "Transfer-Encoding is not supported")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1:
            raise APIError(411, "One Content-Length header is required")
        try:
            length = int(lengths[0])
        except ValueError:
            raise APIError(400, "Invalid Content-Length")
        if length < 0 or length > MAX_BODY_BYTES:
            raise APIError(413, f"Request body must be at most {MAX_BODY_BYTES} bytes")
        if self.headers.get_content_type() != "application/json":
            raise APIError(415, "Content-Type must be application/json")
        def reject_constant(value):
            raise ValueError(f"Nonfinite JSON number: {value}")
        return json.loads(self.rfile.read(length), parse_constant=reject_constant)

    def _dispatch(self) -> None:
        try:
            self._check_origin()
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            if self.command == "GET" and path == "/api/catalogue":
                self._json(200, catalogue())
            elif self.command == "GET" and path == "/api/routes":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if any(len(values) != 1 for values in query.values()):
                    raise ValueError("Route query parameters must appear exactly once")
                data = {key: values[0] for key, values in query.items()}
                _only_fields(data, {"scheme", "parameter_set", "goal", "doom", "unbalanced", "scope"}, "route query")
                instances, options = prepare_job(data, require_selection=False)
                self._json(200, {"instances": [asdict(item) for item in instances],
                                 "availability": algorithm_availability(instances, options)})
            elif self.command == "POST" and path == "/api/availability":
                instances, options = prepare_job(self._body(), require_selection=False)
                self._json(200, {"instances": [asdict(item) for item in instances],
                                 "availability": algorithm_availability(instances, options)})
            elif self.command == "POST" and path == "/api/jobs":
                instances, options = prepare_job(self._body())
                self._json(202, self.server.jobs.submit(instances, options))
            elif path.startswith("/api/jobs/") and self.command in ("GET", "DELETE"):
                job_id = path[len("/api/jobs/"):]
                if not job_id or "/" in job_id:
                    raise APIError(404, "Job not found")
                operation = self.server.jobs.get if self.command == "GET" else self.server.jobs.cancel
                self._json(200, operation(job_id))
            elif self.command in ("GET", "HEAD") and not path.startswith("/api/"):
                self._static(path)
            else:
                raise APIError(404, "Endpoint not found")
        except APIError as exc:
            self._json(exc.status, {"error": str(exc)})
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError) as exc:
            self._json(400, {"error": str(exc) or "Invalid request"})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            self._json(500, {"error": "An unexpected server error occurred"})

    def _static(self, path: str) -> None:
        relative = "index.html" if path == "/" else path.lstrip("/")
        candidate = (self.server.assets / relative).resolve()
        try:
            candidate.relative_to(self.server.assets)
        except ValueError:
            raise APIError(404, "File not found")
        if not candidate.is_file() or candidate.suffix not in (
            ".html", ".css", ".js", ".svg", ".png", ".jpg", ".ico", ".woff2",
        ):
            raise APIError(404, "File not found")
        payload = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if candidate.suffix in (".html", ".css", ".js", ".svg"):
            content_type += "; charset=utf-8"
        self._headers(200, content_type, len(payload))
        if self.command != "HEAD":
            self.wfile.write(payload)

    do_GET = _dispatch
    do_HEAD = _dispatch
    do_POST = _dispatch
    do_DELETE = _dispatch


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    try:
        server = EstimatorServer((args.host, args.port))
    except OSError as exc:
        parser.exit(1, f"Unable to start the web interface: {exc}\n")
    host, port = server.server_address
    print(f"Code-based Estimator: http://{host}:{port}\nPress Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
