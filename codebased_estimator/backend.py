"""Small, explicit adapter for CryptographicEstimators' classical models."""

from __future__ import annotations

import importlib
from importlib import metadata
import math
from numbers import Integral, Real
import os
from pathlib import Path
import subprocess

from .models import AttackInstance, Estimate, Options


def _json_value(value):
    """Keep upstream numeric parameters valid in strict JSON output."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError(f"Unsupported upstream result type: {type(value).__name__}")


def _git_output(directory: Path, *arguments: str):
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def backend_info() -> dict:
    """Report the installed package and, for source checkouts, its revision."""
    package = importlib.import_module("cryptographic_estimators")
    source_path = Path(package.__file__).resolve()
    try:
        version = metadata.version("cryptographic_estimators")
    except metadata.PackageNotFoundError:
        version = None
    result = {"package": "cryptographic_estimators", "version": version,
              "source_path": str(source_path), "commit": None,
              "tracked_dirty": None}
    # Do not attribute the containing application's Git revision to a wheel.
    checkout = source_path.parent.parent
    if (checkout / ".git").exists():
        result["commit"] = _git_output(checkout, "rev-parse", "HEAD")
        dirty = _git_output(checkout, "status", "--porcelain", "--untracked-files=no")
        result["tracked_dirty"] = bool(dirty) if dirty is not None else None
    return result


class ClassicalModel:
    """Evaluate a single, unstructured decoding instance in bit operations."""

    name = "classical"

    @staticmethod
    def _unsupported(name: str, instance: AttackInstance, reason: str) -> Estimate:
        return Estimate(
            algorithm=name, model="classical", status="not_implemented", reason=reason,
            metadata={"tags": list(instance.tags), "targets": instance.targets,
                      "structure": list(instance.structure)},
        )

    @staticmethod
    def _family_algorithms(family, base_name):
        module = importlib.import_module(f"cryptographic_estimators.{family}")
        estimator_class = getattr(module, family)
        algorithm_base = getattr(module, base_name)
        excluded_defaults = set(estimator_class.excluded_algorithms_by_default)
        all_classes = list(algorithm_base.__subclasses__())
        candidates = {cls.__name__: cls for cls in all_classes if cls not in excluded_defaults}
        return estimator_class, all_classes, candidates

    @classmethod
    def _known_names(cls):
        names = set()
        for family, base in (("SDEstimator", "SDAlgorithm"),
                             ("SDFqEstimator", "SDFqAlgorithm"),
                             ("RankSDEstimator", "RankSDAlgorithm")):
            names.update(cls._family_algorithms(family, base)[2])
        return names

    @classmethod
    def _resolve(cls, problem):
        if problem.kind not in ("sd", "rank_sd"):
            return None
        parameters = dict(problem.parameters)
        helper = importlib.import_module("cryptographic_estimators.helper")
        if not helper.is_prime_power(parameters["q"]):
            raise ValueError("q must be a prime power to define a finite field")
        if problem.kind == "rank_sd":
            family, base_name = "RankSDEstimator", "RankSDAlgorithm"
        elif parameters["q"] == 2:
            family, base_name = "SDEstimator", "SDAlgorithm"
            parameters.pop("q")
        else:
            family, base_name = "SDFqEstimator", "SDFqAlgorithm"
        return (family, parameters, *cls._family_algorithms(family, base_name))

    def estimate(self, instance: AttackInstance, options: Options) -> list[Estimate]:
        requested = options.classical_algorithms
        if requested == ():
            return []
        resolved = self._resolve(instance.problem)
        candidates = resolved[-1] if resolved is not None else self._known_names()
        if requested is not None:
            unknown = set(requested).difference(candidates)
            if unknown:
                raise ValueError(
                    f"Unknown or unavailable classical algorithms: {', '.join(sorted(unknown))}. "
                    f"Available: {', '.join(sorted(candidates))}"
                )
            names = list(dict.fromkeys(requested))
        else:
            names = list(candidates) if resolved is not None else ["classical"]
        return [self.estimate_algorithm(name, instance, options) for name in names]

    def estimate_algorithm(
        self, name: str, instance: AttackInstance, options: Options,
    ) -> Estimate:
        """Receive the full tagged instance before applicability checks and optimization."""
        problem = instance.problem
        resolved = self._resolve(problem)
        if resolved is None:
            if name != "classical" and name not in self._known_names():
                raise ValueError(f"Unknown classical algorithm: {name}")
            return self._unsupported(
                name, instance, f"No classical backend for problem kind {problem.kind!r}.",
            )
        family, parameters, estimator_class, all_classes, candidates = resolved
        if name not in candidates:
            raise ValueError(f"Unknown or unavailable {family} algorithm: {name}")
        if instance.tags:
            reasons = {
                "doom:qccf": "QCCF requires an algorithm-specific model of available codeword solutions/orbit candidates.",
                "doom:qcsd": "QCSD requires an algorithm-specific model of available syndrome targets.",
            }
            reason = " ".join(reasons.get(tag, f"No classical model for tag {tag!r}.")
                              for tag in instance.tags)
            return self._unsupported(name, instance, reason)
        if instance.targets != 1:
            return self._unsupported(
                name, instance,
                "Multiple targets require an algorithm-specific target model; "
                "they are not interpreted as additional solutions.",
            )
        if instance.structure:
            return self._unsupported(
                name, instance,
                "This adapter has no reduction for structured decoding instances: "
                + ", ".join(instance.structure),
            )
        if problem.kind == "rank_sd" and problem.log2_solutions is not None:
            return self._unsupported(
                name, instance,
                "RankSDEstimator does not implement the number-of-solutions parameter.",
            )

        bound = options.memory_bound_log2_bits
        kwargs = dict(bit_complexities=1, complexity_type=0, memory_access=0,
                      memory_bound=math.inf if bound is None else bound)
        if problem.log2_solutions is not None:
            kwargs["nsolutions"] = problem.log2_solutions
        if family == "SDFqEstimator":
            kwargs["is_syndrome_zero"] = False

        configuration = {
            "estimator": family,
            "bit_complexities": 1,
            "complexity_type": 0,
            "memory_access": 0,
            "memory_bound_log2_bits": bound,
            "tags": list(instance.tags),
            "targets": instance.targets,
            "solution_count_policy": "upstream default" if problem.log2_solutions is None else "explicit log2 count",
        }
        if family == "SDFqEstimator":
            configuration["is_syndrome_zero"] = False
        if family == "RankSDEstimator":
            configuration.update(linear_algebra_exponent=3, theta=2,
                                 solution_count_policy="not implemented upstream")

        # Rank algorithms mutate the problem's field-operation convention.
        # A fresh estimator also isolates cached optimization and exclusions.
        selected = candidates[name]
        estimator = estimator_class(
            **parameters,
            **kwargs,
            excluded_algorithms=[cls for cls in all_classes if cls is not selected],
        )
        details = {**configuration,
                   "effective_log2_solutions": estimator.problem.nsolutions}
        algorithms = estimator.algorithms()
        if not algorithms:
            return Estimate(
                algorithm=name, model=self.name, status="not_applicable",
                reason="The upstream estimator rejected this algorithm for these parameters.",
                metadata=_json_value(details),
            )
        if len(algorithms) != 1 or type(algorithms[0]).__name__ != name:
            raise RuntimeError("Upstream algorithm selection did not match the requested algorithm.")
        algorithm = algorithms[0]
        time = algorithm.time_complexity()
        memory = algorithm.memory_complexity()
        optimized = _json_value(algorithm.get_optimal_parameters_dict())
        time = float(time) if time is not None else math.inf
        memory = float(memory) if memory is not None else math.inf
        feasible = math.isfinite(time) and math.isfinite(memory)
        reason = ""
        if not feasible:
            reason = "No finite upstream estimate is available under these parameters and memory bound."
        elif bound is not None and memory > bound:
            feasible = False
            reason = "The upstream result exceeds the requested log2 memory bound in bits."
        return Estimate(
            algorithm=name,
            model=self.name,
            status="computed" if feasible else "infeasible",
            time_log2=time if math.isfinite(time) else None,
            memory_log2=memory if math.isfinite(memory) else None,
            parameters=optimized,
            reason=reason,
            assumptions=("Generic unstructured single-target decoding; upstream classical cost model.",),
            metadata=_json_value(details),
        )
