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

from .assumptions import BLOCK_OUTER, BLOCK_SOLUTIONS, CLASSICAL_COST
from .models import AttackInstance, Estimate, Options, Problem
from .doom_fallback import single_target_fallback


_SQRT_SYNDROMES = (
    "Empirical sqrt(M) time discount for M syndromes; syndrome correlations and shared list costs are not modeled.",
    CLASSICAL_COST,
)


def _ce_outer_event(algorithm, parameters):
    """Return the aggregate outer event and CE's unsaturated log probability.

    Selected coordinates are shuffled within the tail and its complement.
    Consequently the half-list and intermediate-region constraints retain
    their CE conditional probabilities after conditioning on total weight.
    """
    from .classical_doom import _logcomb

    name = type(algorithm).__name__
    n, k, w = algorithm.problem.get_parameters()
    p, ell = parameters.get("p", 0), parameters.get("l", 0)
    if name == "Prange":
        tail, weight, split = n-k, 0, 0.0
    elif name == "Stern":
        tail, weight, split = n-k, 2*p, 2*_logcomb(k//2, p)
    elif name == "BallCollision":
        pl = parameters["pl"]
        tail, weight = n-k-ell, 2*(p+pl)
        split = 2*_logcomb(k//2, p)+2*_logcomb(ell//2, pl)
    elif name == "BothMay":
        tail, weight = n-k-ell, 2*p+parameters["w2"]
        split = 2*_logcomb(k//2, p)+_logcomb(ell, parameters["w2"])
    elif name in ("Dumer", "BJMMd2", "BJMMd3", "MayOzerovD2", "MayOzerovD3", "BJMMplus"):
        # This adapter does not enable CE's separate QC variant of BJMMplus.
        qc = getattr(algorithm, "qc", 0) if name == "BJMMplus" else 0
        if qc:
            raise ValueError("Unbalanced CE hook does not model BJMMplus qc mode")
        tail, weight = n-k-ell, 2*p
        split = 2*_logcomb((k+ell)//2, p)
    else:
        return None
    return tail, weight, _logcomb(tail, w-weight)+split-_logcomb(n, w)


def _install_ce_outer_probability(algorithm, profile):
    """Install an instance-local probability objective before CE optimization.

    No package source or process-global class is modified. List, matrix,
    representation, and (for Stern) IM projection costs stay unchanged.
    """
    from .unbalanced import optimize_outer

    name = type(algorithm).__name__
    if name in ("BJMMdw", "BJMMpdw"):
        from .ce_disjoint_outer import install_disjoint_outer
        return install_disjoint_outer(algorithm, profile)
    if name in ("BJMM", "MayOzerov"):
        children = {depth: getattr(algorithm, f"{name}_depth_{depth}") for depth in (2, 3)}
        detail_functions = {depth: _install_ce_outer_probability(child, profile)
                            for depth, child in children.items()}
        algorithm._time_complexity_is_convex = False
        original = algorithm._time_and_memory_complexity

        def evaluate_depth(parameters, verbose_information=None):
            # CE checks the child's feasibility before asking it to optimize.
            # A fresh parent evaluated with explicit {r, depth} therefore
            # reports infinity unless its selected child is initialized first.
            # Keep depth selection and all child costs in CE, but make replay
            # independent of a preceding no-argument optimization call.
            child = children.get(parameters.get("depth"))
            if child is not None:
                child.optimal_parameters()
            return original(parameters, verbose_information)

        algorithm._time_and_memory_complexity = evaluate_depth

        def details(parameters):
            depth = parameters["depth"]
            child_parameters = children[depth].optimal_parameters().copy()
            return {**detail_functions[depth](child_parameters),
                    "depth": depth, "child_parameters": child_parameters}

        return details
    if name not in ("Prange", "Stern", "Dumer", "BallCollision", "BothMay", "BJMMplus",
                    "BJMMd2", "BJMMd3", "MayOzerovD2", "MayOzerovD3"):
        return None
    original = algorithm._time_and_memory_complexity
    # Base-list generation is still a lower bound on one iteration, and the
    # replacement repetition exponent is nonnegative. Retain those safe CE
    # prunes. BJMMplus also treats memory as a work lower bound, so disable
    # its hook rather than assuming the proxy remains a strict lower bound.
    if name == "BJMMplus":
        algorithm._is_early_abort_possible = lambda *args, **kwargs: False
    algorithm._time_complexity_is_convex = False

    def correction(parameters, event=None):
        tail, weight, uniform_event = event or _ce_outer_event(algorithm, parameters)
        outer = optimize_outer(profile, tail, weight)
        solutions = algorithm.problem.nsolutions
        old = max(0.0, -uniform_event-solutions)
        new = max(0.0, -uniform_event-outer.gain-solutions)
        return outer, old, new

    def evaluate(parameters, verbose_information=None):
        result = original(parameters, verbose_information)
        if isinstance(result, tuple) and math.isfinite(result[0]):
            from .classical_doom import _logcomb
            event = _ce_outer_event(algorithm, parameters)
            tail, weight, uniform_event = event
            n, _, w = algorithm.problem.get_parameters()
            uniform_total = (_logcomb(tail, w-weight)+_logcomb(n-tail, weight)-_logcomb(n, w))
            solutions = algorithm.problem.nsolutions
            old = max(0.0, -uniform_event-solutions)
            # The block-total probability cannot exceed one. Conditional
            # half-list constraints still cost at least this many repeats.
            lower = result[0]-old+max(0.0, uniform_total-uniform_event-solutions)
            if algorithm._is_early_abort_possible(lower):
                return math.inf, result[1]
            _, old, new = correction(parameters, event)
            result = (result[0]-old+new, result[1])
            if verbose_information is not None:
                verbose_information["permutations"] = new
        elif isinstance(result, dict):
            # CE 2.1.1 depth-three verbose methods return the dictionary.
            _, _, new = correction(parameters)
            result["permutations"] = new
        return result

    algorithm._time_and_memory_complexity = evaluate

    def details(parameters):
        outer, old, new = correction(parameters)
        tail, weight, _ = _ce_outer_event(algorithm, parameters)
        return {**outer.to_dict(), "applied": True,
                "model": "block_outer_probability", "strategy": "block_allocation",
                "tail_size": tail, "information_weight": weight,
                "log2_permutations_before": old, "log2_permutations_after": new,
                "log2_repetition_gain": old-new,
                "inner_costs": "unchanged CE costs; uniform shuffle within selected regions",
                "search": "CE parameter search with profile objective; convex shortcuts disabled; base-list and conditional-probability lower-bound pruning"}

    return details


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


def _profile_cost_assumptions(metadata):
    """Describe block conditioning only when the returned cost actually uses it."""
    if not metadata.get("unbalanced", {}).get("applied", False):
        return ()
    return BLOCK_OUTER, BLOCK_SOLUTIONS


def _ce_bjmm_depth3(instance: AttackInstance, options: Options) -> Estimate:
    """Optimize a fresh CE depth-three child with the ordinary SD conventions.

    This deliberately does not reuse the parent's selected depth or parameters.
    A profile, when present, uses the existing per-parameter outer-probability
    hook; its generic competitor is constructed separately by the caller.
    """
    sd = importlib.import_module("cryptographic_estimators.SDEstimator.sd_problem")
    bjmm = importlib.import_module("cryptographic_estimators.SDEstimator.SDAlgorithms.bjmm")
    parameters = instance.problem.parameters
    bound = options.memory_bound_log2_bits
    kwargs = {"memory_bound": math.inf if bound is None else bound}
    if instance.problem.log2_solutions is not None:
        kwargs["nsolutions"] = instance.problem.log2_solutions
    problem = sd.SDProblem(*(parameters[key] for key in ("n", "k", "w")), **kwargs)
    algorithm = bjmm.BJMMd3(problem, bit_complexities=1, complexity_type=0,
                            memory_access=0)
    profile = instance.block_profile
    outer_details = (_install_ce_outer_probability(algorithm, profile)
                     if profile is not None else None)
    time = algorithm.time_complexity()
    memory = algorithm.memory_complexity()
    time = float(time) if time is not None else math.inf
    memory = float(memory) if memory is not None else math.inf
    feasible = (math.isfinite(time) and math.isfinite(memory)
                and (bound is None or memory <= bound))
    optimized = algorithm.get_optimal_parameters_dict()
    details = {
        "estimator": "SDEstimator", "upstream_algorithm": "BJMMd3",
        "bit_complexities": 1, "complexity_type": 0, "memory_access": 0,
        "memory_bound_log2_bits": bound,
        "effective_log2_solutions": problem.nsolutions,
        "solution_count_policy": ("upstream default" if instance.problem.log2_solutions is None
                                  else "explicit log2 count"),
    }
    if outer_details is not None and feasible:
        details["unbalanced"] = outer_details(optimized)
    return Estimate(
        algorithm="BJMM", model="classical",
        status="computed" if feasible else "infeasible",
        time_log2=time if math.isfinite(time) else None,
        memory_log2=memory if math.isfinite(memory) else None,
        parameters=_json_value({"depth": 3, **optimized}),
        reason="" if feasible else "No finite CE depth-three estimate satisfies the memory bound.",
        metadata=_json_value(details),
    )


def _with_bjmm_depth3_candidate(instance: AttackInstance, options: Options,
                                explicit: Estimate) -> Estimate:
    """Add only CE depth three / sqrt(M) to the explicit depth-two candidate.

    The unchanged CE parent is already retained by ``estimate_doom``. The
    empirical discount is independent of the depth-three search parameters;
    neither the explicit DOOM cost nor CE depth two is discounted here.
    """
    if instance.targets == 1:
        return explicit
    profile = instance.block_profile
    candidates = []
    strategies = [("ce_depth3_sqrt_targets", None, instance.targets)]
    if profile is not None:
        strategies.append(("profile_ce_depth3_sqrt_targets", profile,
                           profile.preserving_targets(instance.targets)))
    for strategy, candidate_profile, active in strategies:
        raw = _ce_bjmm_depth3(replace(instance, tags=(), targets=1,
                                     block_profile=candidate_profile), options)
        discount = 0.5 * math.log2(active)
        time = max(0.0, raw.time_log2-discount) if raw.status == "computed" else raw.time_log2
        candidates.append((strategy, active, raw, time, discount))
    selected = None
    for candidate in candidates:
        _, _, raw, time, _ = candidate
        if (raw.status == "computed" and
                (explicit.status != "computed" or time < explicit.time_log2) and
                (selected is None or time < selected[3])):
            selected = candidate
    comparison = {
        "policy": "minimum of explicit depth-two DOOM, unchanged CE baseline, and independently optimized CE depth three / sqrt(M)",
        "explicit_or_baseline_time_log2": explicit.time_log2,
        "explicit_or_baseline_strategy": explicit.metadata["doom"]["strategy"],
        "depth_two_sqrt_discount_applied": False,
        "candidates": [{
            "strategy": strategy, "depth": 3, "status": raw.status,
            "active_targets": active, "single_target_time_log2": raw.time_log2,
            "time_log2": time, "memory_log2": raw.memory_log2,
            "log2_speedup": discount, "parameters": raw.parameters,
            "effective_log2_solutions": raw.metadata.get("effective_log2_solutions"),
            **({"unbalanced": raw.metadata["unbalanced"]}
               if "unbalanced" in raw.metadata else {}),
        } for strategy, active, raw, time, discount in candidates],
    }
    if selected is None:
        return replace(explicit, metadata={
            **explicit.metadata,
            "doom": {**explicit.metadata["doom"], "bjmm_depth3_comparison": comparison},
        })
    strategy, active, raw, time, discount = selected
    baseline_time = explicit.metadata["doom"].get("baseline_time_log2")
    search = {
        "method": "independent CE fixed-depth-three optimization",
        "depth": 3, "parameters_optimized": ["r", "p", "p1", "p2", "l"],
        "profile_outer_probability": strategy == "profile_ce_depth3_sqrt_targets",
        "discount_parameter_independent": True, "baseline_retained": True,
    }
    details = {
        **raw.metadata, "tags": list(instance.tags), "targets": instance.targets,
        "heuristic": True,
        "doom": {
            "model": "sqrt_targets_approximation",
            "cost_model": "ce-bjmm-depth3-sqrt-targets-v1",
            "strategy": strategy, "depth": 3,
            "available_targets": instance.targets, "active_targets": active,
            "baseline_time_log2": baseline_time,
            "single_target_time_log2": raw.time_log2,
            "log2_speedup": baseline_time-time if baseline_time is not None else None,
            "log2_proxy_speedup": discount,
            "realized_log2_proxy_speedup": raw.time_log2-time,
            "postprocessing_speedup_applied": True,
            "search": search,
            "explicit_doom_search": explicit.metadata["doom"]["search"],
            "bjmm_depth3_comparison": comparison,
        },
    }
    if profile is not None:
        preserving = profile.preserving_targets(instance.targets)
        details["unbalanced"] = {
            **raw.metadata.get("unbalanced", {}),
            "applied": strategy == "profile_ce_depth3_sqrt_targets",
            "strategy": (strategy if strategy == "profile_ce_depth3_sqrt_targets"
                         else "generic_full_orbit"),
            "profile_preserving_targets": preserving,
            "available_targets": instance.targets,
            "target_policy": "depth-three sqrt-target proxy uses the profile-preserving subgroup; full generic orbit retained separately",
            "search": search,
        }
        details["doom"]["profile_preserving_targets"] = preserving
    assumptions = _SQRT_SYNDROMES + _profile_cost_assumptions(details)
    return replace(raw, time_log2=time, assumptions=assumptions,
                   references=explicit.references, metadata=_json_value(details))


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
    BJMM additionally compares independently optimized CE depth three / sqrt(M).
    MAGE-Stern integrates targets into its branching cost and probability.
    Remaining binary algorithms use a marked square-root-of-targets approximation.
    QCCF supplies log2(targets) as CE's solution count; MAGE instead uses a
    one-syndrome independent-codeword proxy with the same single-target costs.
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
        codeword_finding = problem.kind in ("cfp", "qccf")
        if problem.kind not in ("sd", "qcsd", "cfp", "qccf"):
            return None, "MAGE-Stern supports binary SD, QCSD and explicitly tagged QCCF proxies."
        if codeword_finding and instance.tags != ("doom:qccf",):
            return None, "MAGE-Stern codeword finding requires exactly the doom:qccf tag."
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
        if not codeword_finding and instance.tags not in ((), ("doom:qcsd",)):
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
        codeword_finding = instance.tags == ("doom:qccf",)
        effective_solutions = (math.log2(instance.targets) if codeword_finding
                               else problem.log2_solutions)
        if not codeword_finding and effective_solutions is None:
            # Read CE's problem convention without running another algorithm.
            sd_problem = importlib.import_module("cryptographic_estimators.SDEstimator.sd_problem")
            effective_solutions = sd_problem.SDProblem(
                parameters["n"], parameters["k"], parameters["w"],
            ).nsolutions
        if not codeword_finding and effective_solutions != 0:
            return self._unsupported(
                name, instance,
                "MAGE-Stern currently supports one solution per syndrome; the CE default "
                "has multiple solutions for this instance. Set log2_solutions=0 explicitly "
                "to compare under a single-solution assumption.",
            )
        from .mage_search import optimize
        from .mage_costs import (COST_MODEL, TARGET_SUCCESS_MODEL,
                                 QCCF_COST_MODEL, CODEWORD_SUCCESS_MODEL)

        search_options = {"algorithm": name,
                          "targets": 1 if codeword_finding else instance.targets,
                          "memory_bound_log2_bits": options.memory_bound_log2_bits}
        if codeword_finding:
            search_options["codewords"] = instance.targets
        cost = optimize(parameters["n"], parameters["k"], parameters["w"],
                        **search_options)
        profile = instance.block_profile
        profile_comparison = None
        if profile is not None:
            available = profile.preserving_targets(instance.targets)
            profile_options = {**search_options, "block_profile": profile}
            profile_options["codewords" if codeword_finding else "targets"] = available
            corrected = optimize(parameters["n"], parameters["k"], parameters["w"],
                                 **profile_options)
            selected = corrected is not None and (cost is None or corrected.time_log2 < cost.time_log2)
            profile_comparison = {
                "model": "block-profile-first-transition-tree-v1",
                "selected_strategy": "block_profile" if selected else "uniform_full_orbit",
                "available_targets": instance.targets,
                "profile_preserving_targets": available,
                "uniform_time_log2": cost.time_log2 if cost else None,
                "profile_time_log2": corrected.time_log2 if corrected else None,
                "full_orbit_baseline_retained": True,
                "mixed_profile_target_batching": False,
            }
            if selected:
                cost = corrected
                if codeword_finding:
                    effective_solutions = math.log2(available)
        details = {
            "estimator": "local MAGE-Stern",
            "cost_model": QCCF_COST_MODEL if codeword_finding else COST_MODEL,
            "target_success_model": CODEWORD_SUCCESS_MODEL if codeword_finding else TARGET_SUCCESS_MODEL,
            "bit_complexities": 1,
            "complexity_type": 0,
            "memory_access": 0,
            "memory_bound_log2_bits": options.memory_bound_log2_bits,
            "tags": list(instance.tags),
            "targets": instance.targets,
            "effective_log2_solutions": effective_solutions,
            "solution_count_policy": (
                "QCCF targets count all usable nonzero codewords of one zero syndrome"
                if codeword_finding else "CE default equals one solution per syndrome"
                if problem.log2_solutions is None else "explicit log2 count"
            ),
            "heuristic": True,
            "mage_cost_convention": {
                "memory_access": "constant cost",
                "vector_operation_bit_cost": parameters["n"],
                "list_record_bits": parameters["n"],
                "partial_elimination": "n*k*b bit operations per generator-matrix block of b pivots",
                "target_transform": (
                    "one n*k zero-representative transform per leaf retained as CE proxy overhead"
                    if codeword_finding else "n*k bit operations per target per leaf"
                ),
                "target_storage": (
                    "one n-bit representative and two unexpanded full-vector lists"
                    if codeword_finding else "full n-bit vectors and a target-expanded right list"
                ),
                "input_conversion": "parity-check to generator conversion charged once",
            },
        }
        if profile_comparison is not None:
            details["unbalanced"] = profile_comparison
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
        # The profile search can itself choose a uniform first block. Describe
        # the returned probability model, not merely the winning search branch.
        profile_selected = bool(cost and cost.details.get("unbalanced", {}).get("selected_strategy") == "block_profile")
        if codeword_finding:
            details.update({
                "codeword_finding": True,
                "target_semantics": "nonzero_codewords",
                "effective_syndrome_targets": 1,
                "available_codewords": instance.targets,
                "codeword_sampling_model": (
                    "block_profile_first_transition_proxy"
                    if profile_selected
                    else "uniform_weight_support_proxy"
                ),
                "zero_syndrome_cost_model": "single_syndrome_ce_proxy_including_representative_overhead",
                "doom": {
                    "model": "mage_stern_codeword_proxy",
                    "cost_model": QCCF_COST_MODEL,
                    "available_targets": instance.targets,
                    "available_codewords": instance.targets,
                    "active_codewords": cost.parameters.get("codewords", instance.targets) if feasible else None,
                    "effective_syndrome_targets": 1,
                    "effective_log2_solutions": effective_solutions,
                    "postprocessing_speedup_applied": False,
                },
            })
        if codeword_finding:
            sampling = "conditioned on block weights" if profile_selected else "with uniform weight supports"
            assumptions = (
                f"QCCF uses a proxy for nonzero codewords {sampling}; rank conditioning is not modeled.",
            )
            active = cost.parameters.get("codewords", instance.targets) if cost else instance.targets
            candidates = "codewords"
        else:
            assumptions = ()
            active = cost.parameters.get("targets_used", instance.targets) if cost else instance.targets
            candidates = "syndromes"
        if active > 1:
            assumptions += (
                f"Whole-tree failures for distinct {candidates} are independent; shared-tree and QC-orbit correlations are not modeled.",
            )
        assumptions += (CLASSICAL_COST, "Full-tree attempts and independent retries are assumed.")
        if profile_selected:
            assumptions += (
                f"Only {candidates} preserving block weights share a first-pivot allocation; remaining coordinates are shuffled uniformly.",
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
        if (instance.block_profile is not None and instance.problem.log2_solutions is None
                and "doom:qccf" not in instance.tags):
            from .classical_doom import _logcomb
            profile = instance.block_profile
            count = max(0.0, sum(_logcomb(length, weight) for length, weight in
                                zip(profile.lengths, profile.weights))
                        -(instance.problem.parameters["n"]-instance.problem.parameters["k"]))
            # Ignoring sampling constraints does not broaden the acceptable
            # solution set: generic and profile candidates share this count.
            instance = replace(instance, problem=replace(instance.problem, log2_solutions=count))
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
            if instance.block_profile is not None:
                preserving = instance.block_profile.preserving_targets(instance.targets)
                if preserving < instance.targets:
                    generic = ClassicalModel.estimate_algorithm(
                        self, name, replace(instance, block_profile=None), options,
                    )
                    restricted = ClassicalModel.estimate_algorithm(
                        self, name, replace(instance, targets=preserving,
                                            block_profile=replace(instance.block_profile, target_permutations=())),
                        options,
                    )
                    take_restricted = (restricted.status == "computed" and
                                       (generic.status != "computed" or
                                        restricted.time_log2 < generic.time_log2))
                    selected_result = restricted if take_restricted else generic
                    return replace(selected_result, metadata={
                        **selected_result.metadata, "targets": instance.targets,
                        "solution_count_policy": ("profile-preserving active codewords: log2(active_codewords)"
                                                  if take_restricted else selected_result.metadata.get("solution_count_policy")),
                        "unbalanced": {
                            **selected_result.metadata.get("unbalanced", {}),
                            "applied": take_restricted and restricted.metadata.get("unbalanced", {}).get("applied", False),
                            "strategy": "profile_preserving_codewords" if take_restricted else "generic_full_orbit",
                            "profile_preserving_targets": preserving,
                            "generic_time_log2": generic.time_log2,
                            "profile_candidate_time_log2": restricted.time_log2,
                            "target_policy": "shared allocation only for codewords with the original block-weight profile",
                        },
                        "doom": {**selected_result.metadata["doom"],
                                 "available_targets": instance.targets,
                                 "active_codewords": preserving if take_restricted else instance.targets},
                    })
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
                    CLASSICAL_COST,
                    "QCCF uses the SD solution-count proxy for nonzero codewords; zero-syndrome effects and codeword correlations are not modeled.",
                ) + _profile_cost_assumptions(result.metadata),
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
                self, name, replace(instance, tags=(), targets=1,
                                    block_profile=None if family == "SDEstimator" and
                                    name in ("Prange", "Stern", "Dumer", "BJMM")
                                    else instance.block_profile), options,
            )
            if family != "SDEstimator":
                return single_target_fallback(
                    baseline, instance,
                    "Classical nonbinary QCSD DOOM is not implemented; "
                    "using the single-target SD baseline without DOOM.",
                )
            if name in ("Prange", "Stern", "Dumer", "BJMM"):
                from .classical_doom import estimate_doom

                result = estimate_doom(name, instance, options, baseline)
                return (_with_bjmm_depth3_candidate(instance, options, result)
                        if name == "BJMM" else result)
            active_targets = (instance.block_profile.preserving_targets(instance.targets)
                              if instance.block_profile is not None else instance.targets)
            speedup = 0.5 * math.log2(active_targets)
            time = baseline.time_log2
            computed = (baseline.status == "computed" and time is not None
                        and math.isfinite(time))
            adjusted_time = max(0.0, time - speedup) if computed else time
            approximate = replace(
                baseline,
                time_log2=adjusted_time,
                assumptions=_SQRT_SYNDROMES + _profile_cost_assumptions(baseline.metadata),
                metadata={
                    **baseline.metadata,
                    "tags": list(instance.tags),
                    "targets": instance.targets,
                    "doom": {
                        "model": "sqrt_targets_approximation",
                        "available_targets": instance.targets,
                        "active_targets": active_targets,
                        "log2_speedup": speedup,
                        "realized_log2_speedup": time - adjusted_time if computed else None,
                    },
                },
            )
            if instance.block_profile is not None:
                approximate = replace(approximate, metadata={
                    **approximate.metadata, "unbalanced": {
                        **approximate.metadata.get("unbalanced", {}),
                        "profile_preserving_targets": active_targets,
                        "target_policy": "sqrt-target proxy uses only profile-preserving targets; full generic orbit retained",
                    },
                })
            if instance.block_profile is not None and active_targets < instance.targets:
                generic = ClassicalModel.estimate_algorithm(
                    self, name, replace(instance, block_profile=None), options,
                )
                if (generic.status == "computed" and
                        (approximate.status != "computed" or generic.time_log2 <= approximate.time_log2)):
                    return replace(generic, metadata={
                        **generic.metadata, "unbalanced": {
                            "applied": False, "strategy": "generic_full_orbit",
                            "profile_preserving_targets": active_targets,
                            "profile_candidate_time_log2": approximate.time_log2,
                        },
                    })
            return approximate
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
        profile = instance.block_profile
        outer_details = (_install_ce_outer_probability(algorithm, profile)
                         if profile is not None and family == "SDEstimator" else None)
        generic_baseline = None
        if profile is not None:
            if outer_details is None:
                details["unbalanced"] = {
                    "applied": False, "strategy": "generic_fallback",
                    "reason": "No reviewed per-parameter outer-probability hook for this CE algorithm; generic costs retained.",
                }
            else:
                generic_baseline = ClassicalModel.estimate_algorithm(
                    self, name, replace(instance, block_profile=None), options,
                )
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
        if outer_details is not None and feasible:
            details["unbalanced"] = outer_details(algorithm.get_optimal_parameters_dict())
            details["unbalanced"]["generic_baseline_time_log2"] = generic_baseline.time_log2
        if family == "SDEstimator" and name == "BJMM":
            # The parent already searched both children. Preserve the actual
            # depth-two optimum as a local-DOOM seed even when depth three won.
            # Fixed-parameter calls below do not launch another CE search.
            child = algorithm.BJMM_depth_2
            child_parameters = child.get_optimal_parameters_dict().copy()
            if all(key in child_parameters for key in ("r", "p", "p1", "l")):
                child_time = child.time_complexity(**child_parameters)
                child_memory = child.memory_complexity(**child_parameters)
                if (math.isfinite(child_time) and math.isfinite(child_memory)
                        and (bound is None or child_memory <= bound)):
                    details.update(ce_depth_two_parameters=child_parameters,
                                   ce_depth_two_time_log2=child_time,
                                   ce_depth_two_memory_log2=child_memory)
        result = Estimate(
            algorithm=name,
            model=self.name,
            status="computed" if feasible else "infeasible",
            time_log2=time if math.isfinite(time) else None,
            memory_log2=memory if math.isfinite(memory) else None,
            parameters=optimized,
            reason=reason,
            assumptions=(CLASSICAL_COST,)
                        + _profile_cost_assumptions(details),
            metadata=_json_value(details),
        )
        if (generic_baseline is not None and generic_baseline.status == "computed"
                and (not feasible or generic_baseline.time_log2 <= time)):
            return replace(generic_baseline, metadata={
                **generic_baseline.metadata,
                "unbalanced": {"applied": False, "strategy": "generic_baseline",
                               "profile_candidate_time_log2": result.time_log2,
                               "reason": "The generic strategy is no more expensive than the profile-aware candidate."},
            })
        return result
