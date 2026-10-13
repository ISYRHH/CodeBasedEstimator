"""Independent small binary matrices for the Mito and QUBE core reductions."""

from random import Random

import pytest

from codebased_estimator.hamming import HammingScheme, hamming_catalogue


def _rotate(value, shift, r):
    shift %= r
    return ((value << shift) | (value >> (r - shift))) & ((1 << r) - 1)


def _multiply(a, b, r):
    """Polynomial multiplication in F2[X]/(X**r-1)."""
    product = 0
    for i in range(r):
        for j in range(r):
            if (a >> i) & (b >> j) & 1:
                product ^= 1 << ((i + j) % r)
    return product


def _dyadic_multiply(a, b, r):
    result = [0] * len(a)
    for i, ai in enumerate(a):
        for j, bj in enumerate(b):
            result[i ^ j] ^= _multiply(ai, bj, r)
    return result


def _pack(blocks, r):
    return sum(block << (i * r) for i, block in enumerate(blocks))


def _rows(columns, nrows):
    return [sum(((column >> i) & 1) << j for j, column in enumerate(columns))
            for i in range(nrows)]


def _apply(matrix, vector):
    return sum((bin(row & vector).count("1") & 1) << i for i, row in enumerate(matrix))


def _rank(matrix):
    pivots = {}
    for row in matrix:
        while row:
            pivot = row.bit_length() - 1
            if pivot not in pivots:
                pivots[pivot] = row
                break
            row ^= pivots[pivot]
    return len(pivots)


def _mito_matrix(h, s, r):
    d = len(h)
    columns = [1 << j for j in range(d * r)]
    columns += [_pack([_rotate(h[i ^ j], bit, r) for i in range(d)]
                      + [_rotate(s[j], bit, r)], r)
                for j in range(d) for bit in range(r)]
    columns += [1 << (d * r + bit) for bit in range(r)]
    return _rows(columns, (d + 1) * r)


def _qube_matrix(h, s, r):
    columns = [1 << bit for bit in range(r)]
    columns += [1 << (r + bit) for bit in range(r)]
    columns += [_pack([_rotate(h[j], bit, r), _rotate(s[j], bit, r)], r)
                for j in range(2) for bit in range(r)]
    return _rows(columns, 2 * r)


@pytest.mark.parametrize("parameter_set,d", [("Mito-1-128", 2), ("Mito-2-E-128", 4)])
def test_mito_joint_rank_encryption_and_cyclic_orbit(parameter_set, d):
    r = 7
    rng = Random(d)
    h, s, a, t = [[rng.randrange(1 << r) for _ in range(d)] for _ in range(4)]
    e = rng.randrange(1 << r)
    matrix = _mito_matrix(h, s, r)
    rank = _rank(matrix)
    assert rank == (d + 1) * r

    ht = _dyadic_multiply(h, t, r)
    st = _dyadic_multiply(s, t, r)
    syndrome = [ai ^ hi for ai, hi in zip(a, ht)] + [st[0] ^ e]
    blocks = a + t + [e]
    assert _apply(matrix, _pack(blocks, r)) == _pack(syndrome, r)
    for shift in range(r):
        shifted = [_rotate(block, shift, r) for block in blocks]
        shifted_syndrome = [_rotate(block, shift, r) for block in syndrome]
        assert _apply(matrix, _pack(shifted, r)) == _pack(shifted_syndrome, r)
        assert sum(bin(block).count("1") for block in shifted) == sum(bin(block).count("1") for block in blocks)

    entry = next(row for row in hamming_catalogue() if row["parameter_set"] == parameter_set)
    instance = next(row for row in HammingScheme("Mito").instances(parameter_set, "msg_recovery")
                    if row.route_id == "composite")
    scale = entry["parameters"]["r"]
    assert instance.problem.parameters["n"] * r == (2 * d + 1) * r * scale
    assert instance.problem.parameters["k"] * r == ((2 * d + 1) * r - rank) * scale
    assert instance.targets == scale


@pytest.mark.parametrize("d", [2, 4])
def test_mito_dyadic_shift_does_not_descend_to_published_syndrome(d):
    """A kernel witness excludes a syndrome transform for the dyadic swap."""
    r = 7
    h, s = list(range(1, d + 1)), [1] + [0] * (d - 1)
    t = [0, 1] + [0] * (d - 2)
    a = _dyadic_multiply(h, t, r)
    matrix = _mito_matrix(h, s, r)
    assert _apply(matrix, _pack(a + t + [0], r)) == 0

    shifted_a = [a[i ^ 1] for i in range(d)]
    shifted_t = [t[i ^ 1] for i in range(d)]
    # u still vanishes, but the other dyadic component now appears in v.
    assert _apply(matrix, _pack(shifted_a + shifted_t + [0], r)) == 1 << (d * r)


def test_qube_joint_rank_encryption_and_cyclic_orbit():
    r = 7
    rng = Random(23)
    h, s, f = [[rng.randrange(1 << r) for _ in range(2)] for _ in range(3)]
    g, e = [rng.randrange(1 << r) for _ in range(2)]
    matrix = _qube_matrix(h, s, r)
    rank = _rank(matrix)
    assert rank == 2 * r
    syndrome = [g ^ _multiply(h[0], f[0], r) ^ _multiply(h[1], f[1], r),
                e ^ _multiply(s[0], f[0], r) ^ _multiply(s[1], f[1], r)]
    blocks = [g, e, *f]
    assert _apply(matrix, _pack(blocks, r)) == _pack(syndrome, r)
    for shift in range(r):
        shifted = [_rotate(block, shift, r) for block in blocks]
        shifted_syndrome = [_rotate(block, shift, r) for block in syndrome]
        assert _apply(matrix, _pack(shifted, r)) == _pack(shifted_syndrome, r)
        assert sum(bin(block).count("1") for block in shifted) == sum(bin(block).count("1") for block in blocks)

    entry = next(row for row in hamming_catalogue() if row["parameter_set"] == "QUBE-128")
    instance = next(row for row in HammingScheme("QUBE").instances("QUBE-128", "msg_recovery")
                    if row.route_id == "composite")
    scale = entry["parameters"]["r"]
    assert instance.problem.parameters["n"] * r == 4 * r * scale
    assert instance.problem.parameters["k"] * r == (4 * r - rank) * scale
    assert instance.targets == scale
