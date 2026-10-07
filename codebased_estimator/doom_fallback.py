"""Report a single-syndrome baseline when a QCSD DOOM model is unavailable."""

from dataclasses import replace

from .models import AttackInstance, Estimate


def single_target_fallback(baseline: Estimate, instance: AttackInstance, reason: str) -> Estimate:
    """Annotate the already-evaluated baseline without changing costs or status."""
    return replace(
        baseline,
        reason=f"{reason} {baseline.reason}".strip(),
        assumptions=(*baseline.assumptions,
                     "Only one of the available QCSD syndromes is used; the per-syndrome "
                     "solution count is unchanged and no DOOM speedup is applied."),
        metadata={
            **baseline.metadata,
            "tags": list(instance.tags),
            "targets": instance.targets,
            "effective_tags": [],
            "effective_targets": 1,
            "doom": {
                "model": "single_target_fallback",
                "available_targets": instance.targets,
                "active_targets": 1,
                "applied": False,
                "fallback_reason": reason,
            },
        },
    )
