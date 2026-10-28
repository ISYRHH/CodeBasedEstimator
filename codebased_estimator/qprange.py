"""QPrange at the existing quantum model's fixed direct point.

This thin adapter adds neither a cost kernel nor a circuit model.  Block
profiles are deliberately left to the next incremental change.
"""

from __future__ import annotations

from dataclasses import replace
from math import log2

from .matrix_costs import DEFAULT_MATRIX_PROFILE, matrix_budget
from .quantum_costs import QuantumCost, evaluate_parameters


COST_MODEL = "bernstein-prange-shared-budget-v1"


def evaluate_qprange(n: int, k: int, w: int, *,
                     matrix_profile: str = DEFAULT_MATRIX_PROFILE,
                     log2_solutions: float = 0.0) -> QuantumCost:
    """Reuse the validated QSS ell=p=0 budget exactly, without its search.

    Existing ensemble-rank and independent-solution probability proxies are
    retained, not upgraded to a guarantee for a structured matrix or runtime.
    """
    cost = evaluate_parameters(n, k, w, "QSS", ell=0, p=0,
                              matrix_profile=matrix_profile,
                              log2_solutions=log2_solutions)
    if cost is None:
        raise RuntimeError("validated QPrange direct point was unexpectedly infeasible")
    budget = matrix_budget(n, k, 0, matrix_profile)
    matrix = budget.metadata()
    matrix.update(log2_G_core=log2(budget.core),
                  log2_G_prepare=log2(budget.preparation),
                  log2_G_total=log2(budget.total),
                  cost_unit="log2 vector_operations")
    return replace(
        cost, parameters={**cost.parameters, "branch": "qprange"},
        details={**cost.details,
                 "log2_amplitude_budget": -cost.details["log2_P_eff_model"] / 2,
                 "log2_support_query_budget": -cost.details["log2_P"] / 2},
        search={"method": "fixed-prange-point", "ell": 0, "p": 0,
                "attack_parameter_search": False},
        matrix=matrix,
    )
