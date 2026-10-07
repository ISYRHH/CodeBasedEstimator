"""Independent, heuristic quantum time estimates with explicit applicability."""

from __future__ import annotations

from math import log2

from .models import AttackInstance, Estimate, Options, QUANTUM_ALGORITHMS
from .list_costs import LIST_COST_PROFILE
from .matrix_costs import (DEFAULT_MATRIX_PROFILE, M4RI_MATRIX_PROFILE,
                          cost_model_for_profile, matrix_budget)
from .quantum_costs import COST_MODEL, optimize


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
        problem = instance.problem
        status = "not_implemented"
        if "doom:qccf" in instance.tags:
            status = "not_applicable"
            reason = f"{name} has no declared QCCF codeword-solution/orbit-candidate model."
        elif problem.kind != "sd" or problem.parameters.get("q") != 2:
            status = "not_applicable"
            reason = f"{name} currently declares only binary syndrome-decoding routes."
        elif "doom:qcsd" in instance.tags:
            reason = (
                f"{name} needs a QCSD cost model and independent optimization using "
                "the available syndrome targets; this algorithm-specific DOOM path is pending."
            )
        elif instance.tags:
            reason = f"{name} has no model for tags: {', '.join(instance.tags)}."
        elif instance.structure:
            reason = f"{name} has no model for structure: {', '.join(instance.structure)}."
        elif instance.targets != 1:
            reason = f"{name} needs an explicit multi-target model and target-aware optimization."
        elif problem.log2_solutions is not None and problem.log2_solutions > 0:
            reason = f"{name} has no multiple-solution model; only log2_solutions=0 or null is supported."
        elif name in ("QSS", "QMMT+"):
            return self._estimate_time(name, instance, options)
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

    def _estimate_time(self, name: str, instance: AttackInstance, options: Options) -> Estimate:
        problem = instance.problem
        p = problem.parameters
        profile = options.quantum_matrix_profile
        # Preserve the default four-argument call, including custom wrappers.
        cost = (optimize(p["n"], p["k"], p["w"], name)
                if profile == DEFAULT_MATRIX_PROFILE else
                optimize(p["n"], p["k"], p["w"], name, matrix_profile=profile))
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
            "effective_log2_solutions": 0,
            "solution_count_policy": (
                "single-solution model assumed for null input"
                if problem.log2_solutions is None else "explicit single solution"
            ),
            "memory_bound_log2_bits": options.memory_bound_log2_bits,
            "memory_bound_applied": False,
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
            "Generic unstructured binary single-target, single-solution decoding.",
            "Ka17 abstract quantum access with ordered lists and average-load cost budgets; "
            "not a gate-level estimate or a security lower bound.",
            "Random-code ensemble survival proxy; not a per-matrix or mean-runtime upper bound.",
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
