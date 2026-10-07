"""Partial elimination budgets in normalized vector operations.

The default profile preserves the existing ordinary-elimination budget.  The
optional M4RI profile is a CE-style aggregate adaptation to ``m`` rows and
``r = m - ell`` tail pivots, not CE's full-matrix formula or a gate count.
Every candidate retains the same preparation budget and the ``h=0`` fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional


DEFAULT_MATRIX_PROFILE = "partial-ge-aggregate-v1"
M4RI_MATRIX_PROFILE = "partial-m4ri-aggregate-v1"
MATRIX_PROFILES = (DEFAULT_MATRIX_PROFILE, M4RI_MATRIX_PROFILE)


def validate_profile(profile: str) -> str:
    """Return a supported profile without silently coercing invalid values."""
    if not isinstance(profile, str) or profile not in MATRIX_PROFILES:
        raise ValueError(f"matrix profile must be one of {MATRIX_PROFILES}")
    return profile


def cost_model_for_profile(profile: str) -> str:
    """Identify the complete quantum cost version selected by this profile."""
    validate_profile(profile)
    if profile == DEFAULT_MATRIX_PROFILE:
        return "ka17-ce-ordered-average-v2"
    return "ka17-ce-ordered-partial-m4ri-v3"


@dataclass(frozen=True)
class MatrixBudget:
    """Immutable exact cost and the certificate for its block-width search."""

    n: int
    k: int
    ell: int
    profile: str
    core: int
    preparation: int
    block_size: int
    _last_evaluated_block_size: int
    _stop_reason: str
    _pruning_bound: Optional[int] = None

    @property
    def total(self) -> int:
        return self.core + self.preparation

    def metadata(self) -> dict[str, Any]:
        """Return fresh JSON-compatible metadata, safe to mutate after caching.

        ``search.complete`` concerns only the selected profile's block-width
        domain.  It makes no claim about optimizing the other attack parameters.
        ``table_peak_records`` is one panel's table, not total quantum memory:
        coherent selection and update histories also require temporary state.
        """
        rows = self.n - self.k
        pivots = rows - self.ell
        domain_max = pivots if self.profile == M4RI_MATRIX_PROFILE else 0
        pruned = self._stop_reason == "exponential_lower_bound"
        return {
            "profile": self.profile,
            "cost_model": cost_model_for_profile(self.profile),
            "n": self.n,
            "k": self.k,
            "ell": self.ell,
            "rows": rows,
            "pivots": pivots,
            "block_size": self.block_size,
            "core_model": (
                "min over h=0..r: E_0=m*r; E_h=sum_j(b_j^2 + 2^b_j + m - b_j); "
                "b_j is the actual panel width"
                if self.profile == M4RI_MATRIX_PROFILE else "m*r"
            ),
            "table_peak_records": (1 << self.block_size) if self.block_size else 0,
            "normalization_assumptions": {
                "unit": "normalized vector operations; not a gate count",
                "preparation": "m*ceil(log2(n+2))^2+n, repeated per outer candidate",
                "pivot_history": "coherent tail-only pivot selection with retained operation history",
                "table_indices": "when h>0, retain pre-update lookup indices for reversing row updates",
                "table_cleanup": "when h>0, local table cleanup with unchanged pivot rows; aggregate coefficient, not exact cleanup cost",
                "oracle_uncompute": "existing common whole-oracle forward/reverse normalization; no extra global factor",
                "memory_scope": "peak panel table only; histories and total quantum memory are not estimated",
            },
            "search": {
                "domain_scope": "block width within this matrix profile only",
                "domain": {"min": 0, "max": domain_max},
                "evaluated_block_sizes": list(range(self._last_evaluated_block_size + 1)),
                "evaluated_count": self._last_evaluated_block_size + 1,
                "last_evaluated_block_size": self._last_evaluated_block_size,
                "complete": True,
                "stop_reason": self._stop_reason,
                "next_block_size": self._last_evaluated_block_size + 1 if pruned else None,
                "pruning_bound": self._pruning_bound,
                "pruning_proof": (
                    "E_h >= 2^h for 1<=h<=r<=m; this lower bound increases "
                    "with h and is at least the incumbent core cost"
                    if pruned else None
                ),
                "tie_break": "retain h=0, then the smallest improving block width",
            },
        }


def _panel_core(rows: int, pivots: int, block_size: int) -> int:
    """Sum true-width panels without iterating over a possibly huge matrix."""
    full, remainder = divmod(pivots, block_size)
    core = full * (block_size * block_size + (1 << block_size) + rows - block_size)
    if remainder:
        core += remainder * remainder + (1 << remainder) + rows - remainder
    return core


@lru_cache(maxsize=4096)
def _matrix_budget(n: int, k: int, ell: int, profile: str) -> MatrixBudget:
    rows = n - k
    pivots = rows - ell
    # ceil(log2(n+2)) = bit_length(n+1), including exact power boundaries.
    preparation = rows * (n + 1).bit_length() ** 2 + n
    best_core, best_block = rows * pivots, 0
    last_evaluated = 0
    stop_reason = "profile_fixed"
    pruning_bound = None
    if profile == M4RI_MATRIX_PROFILE:
        stop_reason = "full_domain"
        # The first full panel gives E_h >= 2**h.  Once this reaches the
        # incumbent, all subsequent h are also unable to improve it.  This is
        # proof-based elimination of the remaining domain, not a heuristic cap.
        block_size = 1
        while block_size <= pivots:
            lower_bound = 1 << block_size
            if lower_bound >= best_core:
                stop_reason = "exponential_lower_bound"
                pruning_bound = lower_bound
                break
            core = _panel_core(rows, pivots, block_size)
            last_evaluated = block_size
            if core < best_core:
                best_core, best_block = core, block_size
            block_size += 1
    return MatrixBudget(
        n=n, k=k, ell=ell, profile=profile, core=best_core,
        preparation=preparation, block_size=best_block,
        _last_evaluated_block_size=last_evaluated,
        _stop_reason=stop_reason, _pruning_bound=pruning_bound,
    )


def matrix_budget(
    n: int, k: int, ell: int, profile: str = DEFAULT_MATRIX_PROFILE,
) -> MatrixBudget:
    """Return the exact aggregate partial-elimination budget.

    Dimensions follow the supported quantum input domain ``0 < k < n`` and
    ``0 <= ell <= n-k``.  Profile and dimension checks precede the bounded cache
    so that Boolean/float values cannot alias an already cached integer input.
    """
    validate_profile(profile)
    if (any(type(value) is not int for value in (n, k, ell))
            or not (0 < k < n and 0 <= ell <= n - k)):
        raise ValueError("require integer parameters 0 < k < n and 0 <= ell <= n-k")
    return _matrix_budget(n, k, ell, profile)
