"""Independent quantum candidates; finite-cost models remain to be implemented."""

from __future__ import annotations

from .models import AttackInstance, Estimate, Options


class QuantumModel:
    """Dispatch each requested candidate with the complete recovery instance."""

    name = "quantum"
    algorithms = ("QPrange", "QSS", "QMMT+")

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
        """Keep tags and target semantics available to future per-algorithm optimizers."""
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
            },
        )
