"""CE 2.1.1 static ordered-list primitives, in normalized vector operations.

Source: SDEstimator/sd_helper.py::_list_merge_complexity(hmap=False), and
SDAlgorithms/bjmm.py::BJMMd2 for the integer intermediate-list proxy.
These are estimation conventions, not measurements of a concrete data structure.
The classical backend keeps its upstream defaults, including hash-based merging.
"""

from __future__ import annotations


LIST_COST_PROFILE = {
    "name": "ce-2.1.1-ordered-v1",
    "reference": "CryptographicEstimators 2.1.1 ordered list-merge formula",
    "static_merge": "integer floor(log2 L), floor(L^2/2^j); singleton cost 1",
    "static_list_sizes": "J1=max(1,floor(D1)); J2=floor(J1^2/2^(ell-f))",
    "candidate_processing": "aggregate matched-output processing; no separate weight-check surcharge",
    "new_leaf": "explicit random support generation and cached full linear image",
    "old_leaf": "reuse cached support/image; one record-removal operation",
    "dynamic_index": "ordered lookup/insertion/deletion with mean loads and ceil(log2(2+z))",
    "scope": "shared static primitives; not equality of complete classical and quantum budgets",
}


def ce_ordered_merge_cost(length: int, matching_bits: int) -> int:
    """Evaluate CE's equal-size ordered-merge formula with exact integers.

The singleton shortcut charges one operation even if the predicted matching
output count is zero. Integer bit lengths implement the intended floor(log2 L)
without inheriting floating-point rounding near very large powers of two.
"""
    if type(length) is not int or length < 1:
        raise ValueError("length must be a positive integer")
    if type(matching_bits) is not int or matching_bits < 0:
        raise ValueError("matching_bits must be a nonnegative integer")
    if length == 1:
        return 1
    return 2 * (length.bit_length() - 1) * length + ((length * length) >> matching_bits)


def setup_list_sizes(u: int, f: int, ell: int) -> tuple[int, int]:
    """Return CE-style integer setup proxies, not expected random list sizes.

The first proxy is kept at least one as in BJMMd2. The terminal output count
can be zero; a singleton merge's unit cost does not assert a matching output.
Dynamic walk loads continue to use the unrounded D1, D2, eta1 and eta2.
"""
    if type(u) is not int or u < 1:
        raise ValueError("u must be a positive integer")
    if any(type(x) is not int for x in (f, ell)) or not 0 <= f <= ell:
        raise ValueError("require integer 0 <= f <= ell")
    first = max(1, (u * u) >> f)
    return first, (first * first) >> (ell - f)
