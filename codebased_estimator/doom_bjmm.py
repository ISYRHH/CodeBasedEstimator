"""Finite depth-two BJMM terms for a target-aware classical DOOM estimate.

The construction follows Esser--May--Zweydinger, *McEliece needs a Break*,
Sections 2 and 5.1 (pp. 6--8 and 18--19 of BJMMDOOM.pdf): only the fourth
base list carries syndromes, and its weight may decrease to compensate for
the target multiplicity.  The half-wise weight and representation counts
below refine the paper's unsplit approximation in the same way as CE's BJMMd2.

These are expected list sizes and hash-merge vector-operation counts, not
measured runtimes.  The random-label/representation heuristic is retained:
floor(log2 R) matching bits give at least one representation in expectation,
not probability one.  Memory counts use a materialized-list proxy; the paper's
streaming implementation may use less memory.  Target correlation, Gaussian
elimination, syndrome processing, solution multiplicity, and batch selection
are left to the caller.  This module models depth two only.
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


def _logadd(*terms: float) -> float:
    """Add nonnegative quantities represented by their base-two logarithms."""
    largest = max(terms, default=-inf)
    if largest == -inf:
        return -inf
    return largest + log2(sum(2.0 ** (term - largest) for term in terms))


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

    For ``m`` active targets, before external costs, iteration work is
    ``shared + m * per_target`` and the success-probability proxy is
    ``min(1, m * probability)``.  All returned costs/counts are logarithms;
    the terms exclude both ``m`` and the number of solutions per syndrome.
    Invalid types or infeasible parameter tuples return ``None``.
    """
    inputs = (n, k, w, ell, p, p1, weight_deficit)
    if any(type(value) is not int for value in inputs):
        return None
    if not (
        n > 0
        and 0 <= k < n
        and 0 <= w <= n
        and 0 <= ell <= n - k
        and p >= 0
        and p % 2 == 0
        and p1 >= 0
        and 0 <= weight_deficit <= min(p // 2, p1)
    ):
        return None

    left_length = (k + ell) // 2
    right_length = k + ell - left_length
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

    log_a = _logcomb(left_length, p1)
    log_b = _logcomb(right_length, p1)
    log_d = _logcomb(right_length, fourth_weight)

    # Choose which final support positions occur in the first summand, then
    # choose positions shared by both summands (and hence canceled by XOR).
    left_representations = comb(p, p // 2) * comb(left_length - p, cancellations)
    right_representations = comb(right_weight, p // 2) * comb(
        right_length - right_weight, cancellations
    )
    representations = left_representations * right_representations
    log_representations = log2(representations)
    # bit_length is exact at powers of two, where floating log2 can round up.
    ell1 = min(ell, representations.bit_length() - 1)
    log_x = log_a + log_b - ell1
    log_y = log_a + log_d - ell1
    log_outputs = log_x + log_y - (ell - ell1)

    # merge(A,B) + the shared sides of merge(A,mD) and merge(X,mY).
    log_first_merge = _logadd(log_a, log_b, log_x)
    log_shared_work = _logadd(log_first_merge, log_a, log_x)
    # The target-dependent sides plus the final collision checks.
    log_target_work = _logadd(log_d, log_y + 1.0, log_outputs)
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
        "log2_memory_shared": _logadd(log_a, log_b, log_x),
        "log2_memory_per_target": _logadd(log_d, log_y),
        "log2_representations": log_representations,
        "details": {
            "half_lengths": [left_length, right_length],
            "half_weights": [p, right_weight],
            "base_weights": [p1, p1, p1, fourth_weight],
            "outside_weight": outside_weight,
            "tail_weight": tail_weight,
            "log2_base_lists": [log_a, log_b, log_a, log_d],
            "log2_intermediate_lists": [log_x, log_y],
            "log2_representations": log_representations,
            "log2_outputs_per_target": log_outputs,
            "matching_bits": [ell1, ell - ell1],
        },
    }
