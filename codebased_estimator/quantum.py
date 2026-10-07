"""Independent, heuristic quantum time estimates with explicit applicability."""

from __future__ import annotations

from dataclasses import replace
from math import log2

from .models import AttackInstance, Estimate, Options, Problem, QUANTUM_ALGORITHMS
from .doom_fallback import single_target_fallback
from .list_costs import LIST_COST_PROFILE
from .matrix_costs import (DEFAULT_MATRIX_PROFILE, M4RI_MATRIX_PROFILE,
                          cost_model_for_profile, matrix_budget)
from .quantum_costs import COST_MODEL, OUTER_PROBABILITY_MODEL, optimize


class QuantumModel:
    """Dispatch each requested candidate with the complete recovery instance."""

    name = "quantum"
    algorithms = QUANTUM_ALGORITHMS

    def estimate(self, instance: AttackInstance, options: Options) -> list[Estimate]:
        names = options.quantum_algorithms
        unknown = set(names).difference(self.algorithms)
        if unknown:
            raise ValueError(
                f"Unknown quantum algorithms: {', '.join(sorted(unknown))}. "
                f"Available: {', '.join(self.algorithms)}"
            )
        return [self.estimate_algorithm(name, instance, options) for name in names]

    def estimate_algorithm(
        self, name: str, instance: AttackInstance, options: Options,
    ) -> Estimate:
        """Validate the full recovery context before optimizing a finite model."""
        if name not in self.algorithms:
            raise ValueError(f"Unknown quantum algorithm: {name}")
        codeword_finding = instance.tags == ("doom:qccf",)
        # Validate the explicitly tagged proxy using the ordinary SD contract,
        # while retaining the original problem kind, tags, and target semantics.
        problem = (Problem("sd", dict(instance.problem.parameters), log2(instance.targets))
                   if codeword_finding else instance.problem)
        status = "not_implemented"
        if "doom:qccf" in instance.tags and not codeword_finding:
            reason = f"{name} has no model for additional QCCF tags: {', '.join(instance.tags)}."
        elif problem.kind != "sd" or problem.parameters.get("q") != 2:
            status = "not_applicable"
            reason = f"{name} currently declares only binary syndrome-decoding routes."
        elif "doom:qcsd" in instance.tags:
            if instance.tags == ("doom:qcsd",) and not instance.structure:
                return self._estimate_without_doom(name, instance, options)
            reason = (
                f"{name} has no model for the additional QCSD tags or structure: "
                f"tags={list(instance.tags)}, structure={list(instance.structure)}."
            )
        elif instance.tags and not codeword_finding:
            reason = f"{name} has no model for tags: {', '.join(instance.tags)}."
        elif instance.structure:
            reason = f"{name} has no model for structure: {', '.join(instance.structure)}."
        elif instance.targets != 1 and not codeword_finding:
            reason = f"{name} needs an explicit multi-target model and target-aware optimization."
        elif name in ("QSS", "QMMT+"):
            return self._estimate_time(name, instance, options, problem=problem,
                                       codeword_finding=codeword_finding)
        else:
            reason = f"{name} finite quantum costs and independent parameter optimization are pending."
        return Estimate(
            algorithm=name,
            model=self.name,
            status=status,
            time_unit="unspecified",
            memory_unit="unspecified",
            reason=reason,
            metadata={
                "tags": list(instance.tags),
                "targets": instance.targets,
                "structure": list(instance.structure),
                "memory_bound_log2_bits": options.memory_bound_log2_bits,
                "matrix_profile": options.quantum_matrix_profile,
            },
        )

    def _estimate_without_doom(
        self, name: str, instance: AttackInstance, options: Options,
    ) -> Estimate:
        """Use one QCSD syndrome when its multi-target quantum model is pending.

        Keep the original per-syndrome solution count and matrix profile. This
        reduction does not apply to unknown constraints or nonzero-codeword
        failures, and cannot implement a missing single-target algorithm.
        """
        baseline = QuantumModel.estimate_algorithm(
            self, name, replace(instance, tags=(), targets=1), options,
        )
        return single_target_fallback(
            baseline, instance,
            "Quantum QCSD DOOM is not implemented; using the single-target SD baseline without DOOM.",
        )

    def _estimate_time(self, name: str, instance: AttackInstance, options: Options, *,
                       problem: Problem, codeword_finding: bool = False) -> Estimate:
        p = problem.parameters
        profile = options.quantum_matrix_profile
        solutions = problem.log2_solutions if problem.log2_solutions is not None else 0.0
        # Preserve the default four-argument call, including custom wrappers.
        optimizer_options = {}
        if profile != DEFAULT_MATRIX_PROFILE:
            optimizer_options["matrix_profile"] = profile
        if solutions:
            optimizer_options["log2_solutions"] = solutions
        if codeword_finding:
            optimizer_options["codeword_finding"] = True
        cost = optimize(p["n"], p["k"], p["w"], name, **optimizer_options)
        metadata = {
            "tags": list(instance.tags),
            "targets": instance.targets,
            "structure": list(instance.structure),
            "cost_model": cost_model_for_profile(profile),
            "matrix_profile": profile,
            "list_cost_profile": dict(LIST_COST_PROFILE),
            "heuristic": True,
            "resource_scope": "time_only",
            "representation_survival": "random-ensemble second-moment proxy R/(R+2^b-1)",
            "first_layer_pairs": [["00", "01"], ["10", "11"]],
            "cost_breakdown_units": {
                "probabilities_and_lengths": "log2",
                "G_S_U_C_Q_g_leaf_direct_check": "log2 vector_operations",
                "setup_merge_first_last_output_index": "log2 vector_operations; null output_index means zero cost",
                "setup_list_size_output_count": "log2 counts; null output_count means zero outputs",
                "T0": "log2 bit_operations",
            },
            "effective_log2_solutions": solutions,
            "solution_count_policy": (
                "QCCF total usable nonzero codewords: log2(targets)"
                if codeword_finding else
                "single-solution model assumed for null input" if problem.log2_solutions is None else
                "explicit single solution" if solutions == 0 else "explicit log2 count for one syndrome"
            ),
            "outer_probability_model": OUTER_PROBABILITY_MODEL,
            "codeword_finding": codeword_finding,
            "memory_bound_log2_bits": options.memory_bound_log2_bits,
            "memory_bound_applied": False,
        }
        if codeword_finding:
            metadata["doom"] = {
                "model": "quantum_outer_solution_probability",
                "cost_model": OUTER_PROBABILITY_MODEL,
                "available_targets": instance.targets,
                "effective_log2_solutions": solutions,
                "source_problem_kind": instance.problem.kind,
                "backend_problem_kind": "sd",
                "codeword_finding": True,
                "postprocessing_speedup_applied": False,
            }
        if cost is not None:
            metadata.update(cost_breakdown=cost.details, search=cost.search)
            if profile != DEFAULT_MATRIX_PROFILE:
                matrix = dict(getattr(cost, "matrix", {}))
                if not matrix:
                    budget = matrix_budget(p["n"], p["k"], cost.parameters["ell"], profile)
                    matrix = budget.metadata()
                    matrix.update(log2_G_core=log2(budget.core) if budget.core else None,
                                  log2_G_prepare=log2(budget.preparation),
                                  log2_G_total=log2(budget.total))
                metadata["matrix"] = matrix
                metadata["cost_breakdown_units"]["matrix_G_core_prepare_total"] = (
                    "log2 vector_operations; null core means zero"
                )
        assumptions = (
            ("Generic binary nonzero-codeword finding through an outer-probability QCCF proxy."
             if codeword_finding else
             "Generic unstructured binary single-target, single-solution decoding." if solutions == 0 else
             "Generic unstructured binary single-target decoding with an explicit solution count."),
            "Ka17 abstract quantum access with ordered lists and average-load cost budgets; "
            "not a gate-level estimate or a security lower bound.",
            "Random-code ensemble survival proxy; not a per-matrix or mean-runtime upper bound.",
        )
        if solutions > 0 or codeword_finding:
            assumptions += (
                "Independent-solution outer union proxy rho*(1-(1-P*sigma)^M), applied during "
                "parameter optimization; the inner model retains one surviving solution and receives no extra multiplicity factor.",
            )
        if codeword_finding:
            assumptions += (
                "targets counts distinct acceptable nonzero weight-w codewords, including usable orbit members; "
                "orbit size and independence are not inferred and correlations are not modeled.",
                "The p=0 direct branch is excluded because it yields the zero codeword; "
                "zero-syndrome-specific enumeration and self-collision costs are not fully modeled.",
            )
        if profile == M4RI_MATRIX_PROFILE:
            assumptions += (
                "Partial M4RI uses abstract coherent row-table lookup and data-dependent pivot selection; "
                "pivot choices and row-operation history are retained until reverse cleanup.",
                "Panel, table, and cleanup work use the declared aggregate vector-operation "
                "normalization; table record counts are not a quantum memory estimate.",
            )
        return Estimate(
            algorithm=name,
            model=self.name,
            status="computed" if cost is not None else "infeasible",
            time_log2=cost.time_log2 if cost is not None else None,
            memory_log2=None,
            time_unit="quantum_bit_operations",
            memory_unit="not_estimated",
            parameters=cost.parameters if cost is not None else {},
            reason=(
                "Heuristic time-only estimate; memory is not estimated and the memory bound is not applied."
                if cost is not None else
                "No finite quantum time estimate was found in the searched parameter domain; "
                "memory is not estimated and the memory bound is not applied."
            ),
            assumptions=assumptions,
            references=("https://arxiv.org/abs/1703.00263v2",),
            metadata=metadata,
        )
