"""Finite depth-two BJMM terms for a target-aware classical DOOM estimate.

The construction follows Esser--May--Zweydinger, *McEliece needs a Break*,
Sections 2 and 5.1: only the fourth
base list carries syndromes, and its weight may decrease to compensate for
the target multiplicity.  The half-wise weight and representation counts
below refine the paper's unsplit approximation in the same way as CE's BJMMd2.

Finite list sizes, merge special cases, representation repetitions, and the
two equal floor-sized halves follow CE's BJMMd2 convention.  With one target
and zero weight deficit, these terms reproduce CE's fixed-parameter costs.
For multiple targets, integer collision sizes are rounded per target before
expanding the fourth leaf.  A target-dependent singleton can use either a
separate scan per target or one shared hash table; the cheaper affine cost
is selected.  This extension is a cost-model convention, not a claim that CE
supplies a finite DOOM construction.

The first intermediate list is retained and the second is streamed into its
final merge.  Peak list storage is max(A+B+X, A+uD+X); a materialized second
intermediate list is unnecessary.  Target correlation, Gaussian elimination,
syndrome processing, solution multiplicity, and batch selection are left to
the caller.  This module models depth two only.
"""

from __future__ import annotations

from functools import lru_cache
from math import comb, inf, log2
from typing import Any


@lru_cache(maxsize=32768)
def _logcomb(n: int, k: int) -> float:
    """Return log2(binomial(n, k)), or -infinity for an impossible count."""
    if n < 0 or k < 0 or k > n:
        return -inf
    return log2(comb(n, min(k, n - k)))


def _merge_affine(a: int, b: int, bits: int) -> tuple[int, int]:
    """Shared and per-target work for CE's hash-merge convention.

    The second list is target-dependent.  Collision rounding is performed for
    one target, so the returned work stays affine in the batch size.  CE's
    singleton fast path costs only the other list; apply that scan separately
    for each target rather than charging for a hash table it does not build.
    """
    if a == 1:
        return 0, b
    if b == 1:
        return 0, a
    return a, b + a*b // (1 << bits)


def _merge_options(a: int, b: int, bits: int) -> tuple[tuple[int, int], ...]:
    """Retain shared hashing as an alternative to repeated singleton scans.

    At one target CE's singleton scan is cheaper.  With multiple targets the
    shared side may instead be hashed once, amortizing its construction cost.
    Both branches retain per-target collision rounding and the same storage.
    """
    scan = _merge_affine(a, b, bits)
    if b == 1 and a > 1:
        return scan, (a, 1 + a // (1 << bits))
    return (scan,)


def bjmm_terms(
    n: int,
    k: int,
    w: int,
    *,
    ell: int,
    p: int,
    p1: int,
    weight_deficit: int,
) -> dict[str, Any] | None:
    """Return BJMMd2 DOOM terms for one admissible finite parameter tuple.

    CE's ``p`` is the final weight in the left half; the right-half weight is
    ``p - weight_deficit``.  ``p1`` is the first three base-list weights; the
    fourth is ``p1 - weight_deficit``.  Thus the final weight outside the
    information set is ``2*p - weight_deficit``.  ``p`` must be even.

    For ``u`` active targets, before external costs, iteration work is
    the minimum of ``shared + u * per_target`` across ``log2_work_branches``;
    the success-probability proxy is ``min(1, u * probability)``.  The legacy
    shared/per-target fields describe the scan branch.  Memory is the maximum
    of the two affine branches in ``log2_memory_branches``.  Representation repetitions multiply
    only the list work, already included in the returned work terms.  Costs
    are logarithms except for explicitly named integer diagnostic fields.
    The terms exclude ``u`` and the number of solutions per syndrome.
    Invalid types or infeasible parameter tuples return ``None``.
    """
    inputs = (n, k, w, ell, p, p1, weight_deficit)
    if any(type(value) is not int for value in inputs):
        return None
    if not (
        n > 0
        and 0 <= k < n
        and 0 <= w <= n
        and 0 <= ell < n - k
        and p >= 0
        and p % 2 == 0
        and p1 >= 0
        and 0 <= weight_deficit <= min(p // 2, p1)
    ):
        return None

    # CE leaves the extra coordinate fixed to zero if k+ell is odd.
    left_length = right_length = (k + ell) // 2
    right_weight = p - weight_deficit
    fourth_weight = p1 - weight_deficit
    outside_weight = p + right_weight
    tail_length = n - k - ell
    tail_weight = w - outside_weight
    cancellations = p1 - p // 2
    if not (
        p <= left_length
        and right_weight <= right_length
        and p1 <= left_length
        and p1 <= right_length
        and 0 <= tail_weight <= tail_length
        and 0 <= cancellations <= left_length - p
        and cancellations <= right_length - right_weight
    ):
        return None

    a = comb(left_length, p1)
    b = comb(right_length, p1)
    d = comb(right_length, fourth_weight)
    log_a, log_b, log_d = map(log2, (a, b, d))

    # Choose which final support positions occur in the first summand, then
    # choose positions shared by both summands (and hence canceled by XOR).
    left_representations = comb(p, p // 2) * comb(left_length - p, cancellations)
    right_representations = comb(right_weight, p // 2) * comb(
        right_length - right_weight, cancellations
    )
    representations = left_representations * right_representations
    log_representations = log2(representations)
    # Exact integer ceiling avoids floating log2 ambiguity near powers of two.
    ell1 = (representations - 1).bit_length()
    if ell1 > ell:
        return None
    representation_repetitions = ((1 << ell1) + representations - 1) // representations
    x = max(1, a*b // (1 << ell1))
    y = max(1, a*d // (1 << ell1))
    outputs = x*y // (1 << (ell-ell1))

    first_shared, first_target = _merge_affine(a, b, ell1)
    second_shared, second_target = _merge_affine(a, d, ell1)
    final_shared, final_target = _merge_affine(x, y, ell-ell1)
    shared_work = representation_repetitions * (
        first_shared + first_target + second_shared + final_shared
    )
    target_work = representation_repetitions * (second_target + final_target)
    work_branches = tuple(
        (representation_repetitions*(first_shared+first_target+second[0]+final[0]),
         representation_repetitions*(second[1]+final[1]))
        for second in _merge_options(a, d, ell1)
        for final in _merge_options(x, y, ell-ell1)
    )
    log_x, log_y = log2(x), log2(y)
    log_shared_work, log_target_work = log2(shared_work), log2(target_work)
    log_probability = (
        _logcomb(tail_length, tail_weight)
        + _logcomb(left_length, p)
        + _logcomb(right_length, right_weight)
        - _logcomb(n, w)
    )

    return {
        "parameters": {
            "depth": 2,
            "p": p,
            "p1": p1,
            "l": ell,
            "l1": ell1,
            "weight_deficit": weight_deficit,
        },
        "log2_probability": min(0.0, log_probability),
        "log2_work_shared": log_shared_work,
        "log2_work_per_target": log_target_work,
        "log2_work_branches": tuple((log2(shared), log2(target))
                                    for shared, target in work_branches),
        # The first branch is retained for callers inspecting the legacy
        # affine fields; batch memory evaluation must use both branches.
        "log2_memory_shared": log2(a+b+x),
        "log2_memory_per_target": -inf,
        "log2_memory_branches": (
            (log2(a+b+x), -inf),
            (log2(a+x), log_d),
        ),
        "log2_representations": log_representations,
        "details": {
            "half_lengths": [left_length, right_length],
            "unused_information_coordinates": k+ell-left_length-right_length,
            "half_weights": [p, right_weight],
            "base_weights": [p1, p1, p1, fourth_weight],
            "outside_weight": outside_weight,
            "tail_weight": tail_weight,
            "log2_base_lists": [log_a, log_b, log_a, log_d],
            "log2_intermediate_lists": [log_x, log_y],
            "log2_representations": log_representations,
            "log2_outputs_per_target": log2(outputs) if outputs else None,
            "matching_bits": [ell1, ell - ell1],
            "representation_repetitions": representation_repetitions,
            "collision_rounding": "per target, floor(A*D/2^l1) and floor(X*Y/2^(l-l1))",
            "memory_model": "stream second intermediate list; max(A+B+X, A+uD+X)",
            "base_list_sizes": [a, b, a, d],
            "intermediate_list_sizes_per_target": [x, y],
            "outputs_per_target": outputs,
            "list_work_shared": shared_work,
            "list_work_per_target": target_work,
            "list_work_branches": work_branches,
            "singleton_merge_model": "minimum of per-target scans and one shared hash table with per-target rounded collisions",
            "list_memory_branches": [(a+b+x, 0), (a+x, d)],
        },
    }
