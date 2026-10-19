"""Small, explicit adapter for CryptographicEstimators' classical models."""

from __future__ import annotations

import importlib
from importlib import metadata
from dataclasses import replace
from functools import lru_cache
import math
from numbers import Integral, Real
import os
from pathlib import Path
import subprocess

from .models import AttackInstance, Estimate, Options, Problem
from .doom_fallback import single_target_fallback


def _m4ri_cost(n: int, k: int, r: int) -> int:
    helper = importlib.import_module("cryptographic_estimators.SDEstimator.sd_helper")
    return helper._gaussian_elimination_complexity(n, k, r)


@lru_cache(maxsize=256)
def _bounded_m4ri_r(n: int, k: int, mem=math.inf) -> int:
    """Exactly reproduce the 2.1.1 search while pruning provably worse r.

    For 0 < r < n-k the upstream integer Gaussian cost is at least 2**r.
    Once this lower bound reaches the best cost, no remaining candidate can
    improve it. Keep upstream's strict log2 comparison (including ties) and
    its check of the *selected* r against mem, rather than changing its model.
    """
    selected, best_log, best_cost = 0, math.inf, None
    if not selected < mem:
        return selected
    for candidate in range(n - k):
        if best_cost is not None and (1 << candidate) >= best_cost:
            break
        cost = _m4ri_cost(n, k, candidate)
        log_cost = math.log2(cost)
        if best_log > log_cost and selected < mem:
            selected, best_log, best_cost = candidate, log_cost, cost
    return selected


def _seed_bounded_m4ri(algorithm) -> bool:
    """Use the reviewed shortcut only for binary Prange/Stern in 2.1.1."""
    if type(algorithm).__name__ not in ("Prange", "Stern"):
        return False
    try:
        if metadata.version("cryptographic_estimators") != "2.1.1":
            return False
    except metadata.PackageNotFoundError:
        return False
    binary = importlib.import_module("cryptographic_estimators.SDEstimator")
    if not isinstance(algorithm, binary.SDAlgorithm):
        return False
    n, k, _ = algorithm.problem.get_parameters()
    mem = algorithm.problem.memory_bound - math.log2(n - k)
    r = _bounded_m4ri_r(n, k, mem)
    base = importlib.import_module("cryptographic_estimators.base_algorithm")
    # SDAlgorithm.set_parameters also disables adaptive ranges for p and l.
    # Its base implementation preserves that upstream search behavior.
    base.BaseAlgorithm.set_parameters(algorithm, {"r": r})
    return True


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
    """Evaluate decoding, including binary QCSD and QCCF cost proxies.

    MAGE-Stern uses a local finite branching model in the same CE bit units.
    For QCSD, Prange, Stern, Dumer and BJMM optimize explicit DOOM costs;
    MAGE-Stern integrates targets into its branching cost and probability.
    Remaining binary algorithms use a marked square-root-of-targets approximation.
    QCCF instead supplies log2(targets) as CE's number of codeword solutions.
    """

    name = "classical"
    local_algorithms = ("MAGE-Stern",)

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
        names = set(cls.local_algorithms)
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

    @staticmethod
    def _backend_problem(instance: AttackInstance) -> Problem:
        """Validate the built-in QCCF proxy without changing caller context.

        Codeword problem kinds remain open to custom backends. Only this
        explicitly tagged classical path interprets their parameters as SD
        parameters and their target count as the total usable solution count.
        """
        if instance.tags == ("doom:qccf",):
            return Problem("sd", dict(instance.problem.parameters),
                           log2_solutions=math.log2(instance.targets))
        return instance.problem

    @staticmethod
    def _mage_applicability(instance: AttackInstance) -> tuple[Problem | None, str]:
        """Keep unsupported structures and solution counts out of the new model."""
        problem = instance.problem
        if problem.kind not in ("sd", "qcsd"):
            return None, "MAGE-Stern currently supports only binary SD and QCSD."
        try:
            problem = Problem("sd", dict(problem.parameters), problem.log2_solutions)
        except ValueError as exc:
            return None, f"MAGE-Stern requires valid SD parameters: {exc}."
        if problem.parameters["q"] != 2:
            return None, "MAGE-Stern currently requires binary parameters (q=2)."
        if problem.log2_solutions not in (None, 0):
            return None, "MAGE-Stern currently supports one acceptable solution per syndrome (log2_solutions=0)."
        if instance.structure:
            return None, "MAGE-Stern has no reduction for additional structure: " + ", ".join(instance.structure)
        if instance.tags not in ((), ("doom:qcsd",)):
            return None, "MAGE-Stern supports only untagged SD or the doom:qcsd target model."
        if not instance.tags and instance.targets != 1:
            return None, "MAGE-Stern requires doom:qcsd for multiple syndrome targets."
        return problem, ""

    def _estimate_mage(self, instance: AttackInstance, options: Options) -> Estimate:
        name = "MAGE-Stern"
        problem, reason = self._mage_applicability(instance)
        if reason:
            return self._unsupported(name, instance, reason)
        parameters = problem.parameters
        effective_solutions = problem.log2_solutions
        if effective_solutions is None:
            # Read CE's problem convention without running another algorithm.
            sd_problem = importlib.import_module("cryptographic_estimators.SDEstimator.sd_problem")
            effective_solutions = sd_problem.SDProblem(
                parameters["n"], parameters["k"], parameters["w"],
            ).nsolutions
        if effective_solutions != 0:
            return self._unsupported(
                name, instance,
                "MAGE-Stern currently supports one solution per syndrome; the CE default "
                "has multiple solutions for this instance. Set log2_solutions=0 explicitly "
                "to compare under a single-solution assumption.",
            )
        from .mage_search import optimize
        from .mage_costs import COST_MODEL, TARGET_SUCCESS_MODEL

        cost = optimize(parameters["n"], parameters["k"], parameters["w"],
                        algorithm=name, targets=instance.targets,
                        memory_bound_log2_bits=options.memory_bound_log2_bits)
        details = {
            "estimator": "local MAGE-Stern",
            "cost_model": COST_MODEL,
            "target_success_model": TARGET_SUCCESS_MODEL,
            "bit_complexities": 1,
            "complexity_type": 0,
            "memory_access": 0,
            "memory_bound_log2_bits": options.memory_bound_log2_bits,
            "tags": list(instance.tags),
            "targets": instance.targets,
            "effective_log2_solutions": 0,
            "solution_count_policy": (
                "CE default equals one solution per syndrome"
                if problem.log2_solutions is None else "explicit log2 count"
            ),
            "heuristic": True,
            "mage_cost_convention": {
                "memory_access": "constant cost",
                "vector_operation_bit_cost": parameters["n"],
                "list_record_bits": parameters["n"],
                "partial_elimination": "n*k*b bit operations per generator-matrix block of b pivots",
                "target_transform": "n*k bit operations per target per leaf",
                "target_storage": "full n-bit vectors and a target-expanded right list",
                "input_conversion": "parity-check to generator conversion charged once",
            },
        }
        bound = options.memory_bound_log2_bits
        time = cost.time_log2 if cost else math.inf
        memory = cost.memory_log2 if cost else math.inf
        feasible = (math.isfinite(time) and math.isfinite(memory)
                    and (bound is None or memory <= bound))
        if cost is not None:
            details["search"] = cost.search
        references = ("https://eprint.iacr.org/2026/1498 (MAGE-Stern, Sections 5-6)",)
        strategy = "multilevel" if cost and len(cost.parameters.get("blocks", ())) > 1 else "single_level"
        details["selected_strategy"] = strategy if feasible else None
        if cost is not None:
            details["cost_breakdown"] = cost.details
        if instance.tags == ("doom:qcsd",):
            details["doom"] = {
                "model": "mage_stern_branching",
                "cost_model": COST_MODEL,
                "available_targets": instance.targets,
                "active_targets": cost.parameters.get("targets_used", instance.targets) if cost else None,
                "postprocessing_speedup_applied": False,
            }
        assumptions = (
            "Binary random-code SD with one acceptable solution per syndrome.",
            "Whole-tree failures for distinct targets are assumed mutually independent; "
            "success is 1-(1-S)^u for single-target tree success S. Independent errors alone "
            "do not establish this assumption for a shared randomized tree.",
            "Complete tree executions are charged without early stopping, with independent "
            "randomized retries until success.",
            "CE-compatible constant-cost memory access, n-bit vector operations and list storage; "
            "finite MAGE-Stern branching probabilities and partial elimination are modeled locally.",
            "Generator partial elimination costs n*k*b bit operations for b pivots; each leaf "
            "transforms each target for n*k bit operations. Both full-vector lists, the target-expanded right list, "
            "and parity-check-to-generator conversion storage are charged.",
            "The bounded parameter search returns the best evaluated point, not a proof of global optimality.",
        )
        if instance.tags:
            assumptions += (
                "QCSD syndrome targets are usable under the model's random-error branching assumptions; "
                "correlations between cyclic shifts are not modeled and no separate sqrt(targets) discount is applied.",
            )
        return Estimate(
            algorithm=name, model=self.name,
            status="computed" if feasible else "infeasible",
            time_log2=float(time) if math.isfinite(time) else None,
            memory_log2=float(memory) if math.isfinite(memory) else None,
            parameters=_json_value({**cost.parameters, "strategy": strategy}) if cost else {},
            reason="" if feasible else "No finite MAGE-Stern estimate satisfies the parameters and memory bound.",
            assumptions=assumptions,
            references=references,
            metadata=_json_value(details),
        )

    def estimate(self, instance: AttackInstance, options: Options) -> list[Estimate]:
        requested = options.classical_algorithms
        if requested == ():
            return []
        resolved = self._resolve(self._backend_problem(instance))
        candidates = set(resolved[-1]) | set(self.local_algorithms) if resolved is not None else self._known_names()
        if requested is not None:
            unknown = set(requested).difference(candidates)
            if unknown:
                raise ValueError(
                    f"Unknown or unavailable classical algorithms: {', '.join(sorted(unknown))}. "
                    f"Available: {', '.join(sorted(candidates))}"
                )
            names = list(dict.fromkeys(requested))
        else:
            names = list(resolved[-1]) if resolved is not None else []
            if ((resolved is not None and resolved[0] == "SDEstimator")
                    or (instance.problem.kind == "qcsd"
                        and instance.problem.parameters.get("q", 2) == 2)):
                names.extend(self.local_algorithms)
            if not names:
                names = ["classical"]
        return [self.estimate_algorithm(name, instance, options) for name in names]

    def estimate_algorithm(
        self, name: str, instance: AttackInstance, options: Options,
    ) -> Estimate:
        """Receive the full tagged instance before applicability checks and optimization."""
        if name == "MAGE-Stern":
            return self._estimate_mage(instance, options)
        problem = self._backend_problem(instance)
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
        if instance.tags == ("doom:qccf",):
            if family != "SDEstimator":
                return self._unsupported(
                    name, instance, "The classical QCCF solution-count proxy requires binary parameters (q=2).",
                )
            if instance.structure:
                return self._unsupported(
                    name, instance,
                    "The QCCF solution-count proxy has no reduction for additional structure: "
                    + ", ".join(instance.structure),
                )
            # A fresh CE instance receives the solution count before its
            # parameter search. Calling the base method preserves the outer
            # algorithm hook's original tagged context, as for QCSD below.
            try:
                result = ClassicalModel.estimate_algorithm(
                    self, name, replace(instance, problem=problem, tags=(), targets=1), options,
                )
            except OverflowError:
                # For example, CE 2.1.1 Stern materializes 2**nsolutions
                # as a float. Preserve the declared count instead of capping
                # it or silently replacing an unavailable upstream estimate.
                result = self._unsupported(
                    name, instance,
                    "CE exceeded its numeric range while evaluating QCCF with "
                    f"nsolutions={problem.log2_solutions}; no finite estimate is available.",
                )
            return replace(
                result,
                assumptions=(
                    "QCCF is estimated by CE's generic binary SD multiple-solution cost proxy; "
                    "zero-syndrome-specific enumeration and self-collisions are not modeled.",
                    "targets counts distinct acceptable nonzero weight-w codewords, including "
                    "usable orbit members; orbit size and independence are not inferred.",
                    "CE receives nsolutions=log2(targets) before optimization, replacing its "
                    "default solution count; no additional DOOM time discount is applied.",
                ),
                metadata={
                    **result.metadata,
                    "tags": list(instance.tags),
                    "targets": instance.targets,
                    "effective_log2_solutions": problem.log2_solutions,
                    "solution_count_policy": "QCCF total usable codewords: log2(targets), replacing upstream default",
                    "heuristic": True,
                    "doom": {
                        "model": "ce_nsolutions",
                        "cost_model": "ce-qccf-nsolutions-v1",
                        "available_targets": instance.targets,
                        "effective_log2_solutions": problem.log2_solutions,
                        "source_problem_kind": instance.problem.kind,
                        "backend_problem_kind": "sd",
                        "postprocessing_speedup_applied": False,
                    },
                },
            )
        if instance.tags == ("doom:qcsd",):
            if instance.structure:
                return self._unsupported(
                    name, instance,
                    "This adapter has no reduction for structured decoding instances: "
                    + ", ".join(instance.structure),
                )
            # Keep each syndrome's solution count unchanged. This internal
            # single-target baseline is not another requested algorithm hook.
            baseline = ClassicalModel.estimate_algorithm(
                self, name, replace(instance, tags=(), targets=1), options,
            )
            if family != "SDEstimator":
                return single_target_fallback(
                    baseline, instance,
                    "Classical nonbinary QCSD DOOM is not implemented; "
                    "using the single-target SD baseline without DOOM.",
                )
            if name in ("Prange", "Stern", "Dumer", "BJMM"):
                from .classical_doom import estimate_doom

                return estimate_doom(name, instance, options, baseline)
            speedup = 0.5 * math.log2(instance.targets)
            time = baseline.time_log2
            computed = (baseline.status == "computed" and time is not None
                        and math.isfinite(time))
            adjusted_time = max(0.0, time - speedup) if computed else time
            return replace(
                baseline,
                time_log2=adjusted_time,
                assumptions=(
                    "Generic unstructured binary decoding; upstream classical cost model.",
                    "QCSD uses a sqrt(M) time-speedup approximation for usable syndrome "
                    "targets under one matrix; algorithm parameters and memory are unchanged.",
                    "This approximation does not model target correlations or "
                    "algorithm-specific multi-target list costs.",
                ),
                metadata={
                    **baseline.metadata,
                    "tags": list(instance.tags),
                    "targets": instance.targets,
                    "doom": {
                        "model": "sqrt_targets_approximation",
                        "available_targets": instance.targets,
                        "log2_speedup": speedup,
                        "realized_log2_speedup": time - adjusted_time if computed else None,
                    },
                },
            )
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
        if family == "SDEstimator" and _seed_bounded_m4ri(algorithm):
            details["gaussian_elimination_search"] = (
                "exact bounded equivalent of upstream 2.1.1 _optimize_m4ri; "
                "other parameter ranges remain adaptive"
            )
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
