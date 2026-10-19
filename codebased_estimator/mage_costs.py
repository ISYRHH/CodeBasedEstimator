"""Finite MAGE-Stern branching probabilities and CE-priced fixed points.

The probability recursion follows Theorem 5.6 of the MAGE-Stern paper
(Carrier, Hatey, Luzzi, and Tillich, ePrint 2026/1498).  It stores
logarithms of survival probabilities, rather than subtracting near-one
extinction probabilities.  In particular, very rare successful branches do
not disappear through floating-point cancellation or underflow.

Costs use the existing estimator's CE convention: an n-bit vector operation
costs n bit operations, random accesses have constant vector cost, and both
lists use n-bit records with a target-expanded right list.  Partial Gaussian
elimination is ordinary elimination on the generator matrix, charged k*b
vector operations for a block of b pivots.  This is a finite CE-compatible
model, not a reproduction of the paper's gate model or sparse-list storage.
Partial M4RI and the paper's sparse-memory implementation are not modeled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from math import comb, expm1, inf, isfinite, log1p, log2


COST_MODEL = "ce-mage-generator-v2"
TARGET_SUCCESS_MODEL = "independent-target-tree-union-v1"
QCCF_COST_MODEL = "ce-mage-qccf-codewords-v1"
CODEWORD_SUCCESS_MODEL = "independent-codeword-tree-union-v1"


@dataclass(frozen=True)
class MageCost:
    time_log2: float
    memory_log2: float
    parameters: dict
    details: dict
    search: dict = field(default_factory=dict)


def _logadd(*terms):
    top = max(terms, default=-inf)
    return top if top == -inf else top + log2(sum(2.0 ** (x - top) for x in terms))


@lru_cache(maxsize=65536)
def _logcomb(n, weight):
    return -inf if not 0 <= weight <= n else log2(comb(n, min(weight, n-weight)))


def _log_any(log_probability, trials):
    """Return log2(1-(1-p)**trials) without forming tiny p or near-one 1-p."""
    if log_probability == -inf or trials == 1:
        return log_probability
    if log_probability >= 0:
        return 0.0
    # Below this threshold replacing -log(1-p) by p changes less than one ulp.
    if log_probability < -50:
        log_hazard = log_probability + log2(trials)
    else:
        probability = 2.0**log_probability
        if probability == 1:
            return 0.0
        log_hazard = log2(-log1p(-probability)) + log2(trials)
    if log_hazard < -50:
        return log_hazard
    if log_hazard > 10:
        return 0.0
    return min(0.0, log2(-expm1(-(2.0**log_hazard))))


def _valid_parameters(n, k, w, ell, p, delta, blocks, repetitions, targets, bound):
    scalars = (n, k, w, ell, p, delta, targets)
    if (any(type(value) is not int for value in scalars)
            or not (0 < k < n and 1 <= w <= n-k and targets >= 1)
            or not (0 <= ell <= n-k and p >= 1 and 0 <= delta <= p)):
        return False
    z = 2*p-delta
    if not (p <= k//2 and p-delta <= k-k//2 and 0 <= w-z <= n-k-ell):
        return False
    if (not blocks or any(type(value) is not int or value < 1 for value in blocks)
            or sum(blocks) != k or len(repetitions) != len(blocks)+1
            or any(type(value) is not int or value < 1 for value in repetitions)):
        return False
    return bound is None or (not isinstance(bound, bool)
                             and isinstance(bound, (int, float))
                             and isfinite(bound) and bound >= 0)


@lru_cache(maxsize=8192)
def _transition_log_rows(n, w, z, previous_size, block):
    """Triangular hypergeometric transitions for one partial information set."""
    remaining = n-previous_size
    outside = remaining-block
    rows = []
    for old_weight in range(z+1):
        denominator = _logcomb(remaining, w-old_weight)
        row = []
        for new_weight in range(old_weight, z+1):
            if denominator == -inf:
                row.append(-inf)
            else:
                row.append(min(0.0, _logcomb(block, new_weight-old_weight)
                               + _logcomb(outside, w-new_weight)-denominator))
        rows.append(tuple(row))
    return tuple(rows)


@lru_cache(maxsize=16384)
def single_target_success_log2(n, k, w, ell, p, delta, blocks, repetitions):
    """Log survival for one specified solution in the uniform-support model.

    ``blocks`` and ``repetitions`` must be tuples; public fixed-point validation
    is performed by :func:`evaluate_parameters`.  The final zero window uses
    the remaining error weight, as in Eq. (5.14), resolving the inconsistent
    printed terminal transition in Eq. (5.11).
    """
    z = 2*p-delta
    left, right = k//2, k-k//2
    # This algebraically equivalent form avoids large zero-window binomials.
    terminal = min(0.0, _logcomb(left, p) + _logcomb(right, p-delta)
                   - _logcomb(k, z) + _logcomb(n-k-ell, w-z)
                   - _logcomb(n-k, w-z))
    alive = [-inf]*z + [_log_any(terminal, repetitions[-1])]
    previous_size = k
    for block, repeat in zip(reversed(blocks), reversed(repetitions[:-1])):
        previous_size -= block
        rows = _transition_log_rows(n, w, z, previous_size, block)
        alive = [_log_any(min(0.0, _logadd(*(probability+alive[new_weight]
                             for new_weight, probability in enumerate(row, old_weight)))), repeat)
                 for old_weight, row in enumerate(rows)]
    return alive[0]


@lru_cache(maxsize=16384)
def _list_logs(n, k, w, ell, p, delta):
    from .classical_doom import _simple_terms

    terms = _simple_terms(n, k, w, "Stern", {"l": ell, "p_left": p, "p_right": p-delta})
    left, right = terms["details"]["log2_base_lists"]
    return left, right, terms["details"]["log2_outputs_per_target"], terms["log2_probability"]


@lru_cache(maxsize=8192)
def _tree_gaussian_logs(n, k, blocks, repetitions):
    log_nodes, levels = 0.0, []
    for block, repeat in zip(blocks, repetitions):
        log_nodes += log2(repeat)
        levels.append(log_nodes+log2(n)+log2(k)+log2(block))
    return _logadd(*levels), log_nodes+log2(repetitions[-1]), tuple(levels)


def evaluate_parameters(n, k, w, *, ell, p, delta=0, blocks=None, repetitions=None,
                        targets=None, memory_bound_log2_bits=None, targets_used=None,
                        codewords=None):
    """Evaluate a fixed CE-priced MAGE-Stern tree, or return None if invalid.

    ``blocks=(k,), repetitions=(1,1)`` is the ordinary Stern branching
    probability, with generator-matrix costs as documented above.  The existing
    CE Stern estimator remains a separate candidate because it uses a parity
    check matrix with optimized M4RI.  The input conversion is charged once;
    complete executions of the tree are then repeated until success.

    Parameter dictionaries in returned points can be replayed directly.
    Distinct targets' whole-tree failures are assumed mutually independent,
    giving success 1-(1-P_single)**targets.  Dependencies among branches within
    one target use the full survival recursion.  Each target is assumed to
    have one accepted solution; independent errors alone do not establish
    whole-tree independence when targets share a randomized tree.

    A positive integer ``codewords`` selects the QCCF multiple-codeword proxy
    for one zero syndrome, requiring ``targets=1``.  All codewords enter only
    the outer success probability; single-syndrome CE costs are retained,
    including representative overhead that zero-syndrome code could omit.
    The uniform-support recursion is a proxy, not an exact rank-conditioned
    codeword distribution.  p>=1 makes every enumerated information vector
    nonzero, excluding the zero word when the information set has full rank.
    """
    if targets is None:
        targets = 1 if targets_used is None else targets_used
    if targets_used is not None and (type(targets_used) is not int or targets_used != targets):
        return None
    if codewords is not None and (type(codewords) is not int or codewords < 1 or targets != 1):
        return None
    if blocks is None:
        blocks = (k,)
    if not isinstance(blocks, (tuple, list)):
        return None
    blocks = tuple(blocks)
    if repetitions is None:
        repetitions = (1,)*(len(blocks)+1)
    if not isinstance(repetitions, (tuple, list)):
        return None
    repetitions = tuple(repetitions)
    if not _valid_parameters(n, k, w, ell, p, delta, blocks, repetitions,
                             targets, memory_bound_log2_bits):
        return None
    log_n, log_k, log_targets = log2(n), log2(k), log2(targets)
    left, right, matches, stern_probability = _list_logs(n, k, w, ell, p, delta)
    # Both tables are materialized, matching the existing CE-DOOM convention.
    memory_shared = log_n+_logadd(log_k, left)
    memory_target = log_n+_logadd(0.0, right)
    online_memory = _logadd(memory_shared, log_targets+memory_target)
    conversion_memory = log_n+log2(n-k+targets)
    memory = max(online_memory, conversion_memory)
    if memory_bound_log2_bits is not None and memory > memory_bound_log2_bits:
        return None

    # One full coset-representative transform per leaf and per target.
    shared_work = log_n+left
    target_work = log_n+_logadd(right, matches, log_k)
    leaf_work = _logadd(shared_work, log_targets+target_work)
    gaussian, leaves, level_gaussian = _tree_gaussian_logs(n, k, blocks, repetitions)
    tree_work = _logadd(gaussian, leaves+leaf_work)
    single_probability = single_target_success_log2(n, k, w, ell, p, delta, blocks, repetitions)
    probability = _log_any(single_probability, targets if codewords is None else codewords)
    if probability == -inf:
        return None
    # Ordinary CE elimination of the input parity-check matrix, followed by
    # dense syndrome transforms.  Its workspace need not coexist with lists.
    conversion_work = log2(n+targets)+2*log2(n-k)
    expected_tree_work = tree_work-probability
    details = {
        "cost_model": COST_MODEL,
        "half_lengths": [k//2, k-k//2],
        "half_weights": [p, p-delta],
        "tail_weight": w-2*p+delta,
        "log2_base_lists": [left, right],
        "log2_expanded_base_lists": [left, right+log_targets],
        "log2_outputs_per_target": matches,
        "log2_total_outputs": matches+log_targets,
        "log2_stern_single_solution_probability": stern_probability,
        "log2_single_target_success_probability": single_probability,
        "log2_single_solution_probability": single_probability,
        "log2_success_probability": probability,
        "log2_permutations": -probability,
        "log2_iteration_bit_cost": tree_work,
        "log2_tree_bit_cost": tree_work,
        "log2_leaf_bit_cost": leaf_work,
        "log2_shared_leaf_bit_cost": shared_work,
        "log2_per_target_leaf_bit_cost": target_work,
        "log2_tree_gaussian_bit_cost": gaussian,
        "log2_level_gaussian_bit_costs": list(level_gaussian),
        "log2_leaves": leaves,
        "log2_conversion_bit_cost": conversion_work,
        "log2_expected_tree_bit_cost": expected_tree_work,
        "log2_online_memory_bits": online_memory,
        "log2_conversion_memory_bits": conversion_memory,
        "log2_shared_memory_bits": memory_shared,
        "log2_per_target_memory_bits": memory_target,
        "log2_active_targets": log_targets,
        "target_success_model": TARGET_SUCCESS_MODEL,
        "target_success_formula": "1-(1-single_target_tree_survival)**targets",
        "target_independence_assumption": "unconditional_independence_of_target_tree_failures",
        "tree_execution_model": "complete_tree_without_early_stopping",
        "gaussian_model": "ordinary_generator_elimination_n_k_b_bit_operations",
        "input_conversion_model": "once_ordinary_parity_check_elimination_and_syndrome_transforms",
    }
    parameters = {"ell": ell, "p": p, "delta": delta, "blocks": list(blocks),
                  "repetitions": list(repetitions), "targets_used": targets}
    if codewords is not None:
        parameters["codewords"] = codewords
        details.update({
            "cost_model": QCCF_COST_MODEL,
            "success_event_kind": "codewords",
            "codeword_count": codewords,
            "effective_syndrome_targets": 1,
            "log2_single_codeword_success_probability": single_probability,
            "log2_single_target_success_probability": probability,
            "codeword_success_model": CODEWORD_SUCCESS_MODEL,
            "target_success_model": CODEWORD_SUCCESS_MODEL,
            "target_success_formula": "1-(1-single_codeword_tree_survival)**codewords",
            "target_independence_assumption": "unconditional_independence_of_codeword_tree_failures",
            "codeword_sampling_model": "uniform_weight_support_proxy",
            "zero_codeword_exclusion": "positive_information_weight_and_full_rank_information_set",
            "zero_syndrome_cost_model": "single_syndrome_ce_proxy_including_representative_overhead",
        })
    return MageCost(_logadd(conversion_work, expected_tree_work), memory, parameters, details)
