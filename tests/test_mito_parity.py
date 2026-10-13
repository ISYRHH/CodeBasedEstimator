"""Independent finite algebra checks for the symbolic parity rank proxy."""

import json
from dataclasses import FrozenInstanceError

import pytest

from codebased_estimator.hamming_parameters import HAMMING_PARAMETERS
from codebased_estimator.mito_parity import MitoKeyParity, dyadic_multiply, transform_syndrome


def _rank(rows):
    pivots = {}
    for row in rows:
        value = sum(bit << j for j, bit in enumerate(row))
        while value:
            pivot = value.bit_length() - 1
            if pivot not in pivots:
                pivots[pivot] = value
                break
            value ^= pivots[pivot]
    return len(pivots)


def _product(h, y):
    """Independent cyclic-by-dyadic multiplication used only on tiny inputs."""
    d, r = len(h), len(h[0])
    return tuple(tuple(sum(h[a][b] * y[i ^ a][(j - b) % r]
                           for a in range(d) for b in range(r)) % 2
                       for j in range(r)) for i in range(d))


def _add(x, y):
    return tuple(tuple(a ^ b for a, b in zip(left, right)) for left, right in zip(x, y))


def _parities(blocks):
    return tuple(sum(block) % 2 for block in blocks)


def _matrices(h):
    d, r = len(h), len(h[0])
    dr, n = d * r, 2 * d * r
    columns = []
    for column in range(n):
        x = tuple(tuple(int(column == i * r + j) for j in range(r)) for i in range(d))
        y = tuple(tuple(int(column == dr + i * r + j) for j in range(r)) for i in range(d))
        s = _add(x, _product(h, y))
        columns.append(tuple(value for block in s for value in block))
    base = [list(row) for row in zip(*columns)]
    ey = [[int(dr + i * r <= column < dr + (i + 1) * r)
           for column in range(n)] for i in range(d)]
    ex = [[int(i * r <= column < (i + 1) * r)
           for column in range(n)] for i in range(d)]
    return base, ey, ex


@pytest.mark.parametrize("d", [1, 2, 4])
@pytest.mark.parametrize("r", [3, 5])
@pytest.mark.parametrize("zero_h", [False, True])
def test_augmented_rank_and_x_parity_redundancy_without_h_invertibility(d, r, zero_h):
    h = tuple(tuple(0 if zero_h else int((i + 2 * j) % 3 == 0)
                    for j in range(r)) for i in range(d))
    model = MitoKeyParity(r, d, [1] + [0] * (d - 1), [0] * (d - 1) + [1])
    base, ey, ex = _matrices(h)
    assert _rank(base) == d * r
    assert _rank(base + ey) == d * r + d
    assert _rank(base + ey + ex) == _rank(base + ey)
    assert model.n - _rank(base + ey) == model.k

    # Check the stronger explicit row identity Ex = E H + B_h Ey.
    parity_h = _parities(h)
    for i in range(d):
        expected = [sum(base[i * r + j][column] for j in range(r)) % 2
                    for column in range(model.n)]
        for block in range(d):
            if parity_h[i ^ block]:
                expected = [a ^ b for a, b in zip(expected, ey[block])]
        assert expected == ex[i]


def test_x_parity_alone_can_add_less_rank_than_y_parity():
    # h = (1,1) has singular B_h with two equal rows.
    base, ey, ex = _matrices(((1, 0, 0), (1, 0, 0)))
    assert _rank(base + ex) - _rank(base) == 1
    assert _rank(base + ey) - _rank(base) == 2


@pytest.mark.parametrize("d", [1, 2, 4])
def test_parity_convolution_and_full_doom_covariance(d):
    r = 5
    h = tuple(tuple(int((i + j) % 3 == 0) for j in range(r)) for i in range(d))
    x = tuple(tuple(int(j == i % r) for j in range(r)) for i in range(d))
    y = tuple(tuple(int(j < i + 1) for j in range(r)) for i in range(d))
    s = _add(x, _product(h, y))
    bx, by = _parities(x), _parities(y)
    assert _parities(_product(h, y)) == dyadic_multiply(_parities(h), by)
    assert _parities(s) == tuple(a ^ b for a, b in zip(bx, dyadic_multiply(_parities(h), by)))
    for cyclic in range(r):
        for dyadic in range(d):
            shifted_x, shifted_bx = transform_syndrome(x, bx, cyclic_shift=cyclic, dyadic_shift=dyadic)
            shifted_y, shifted_by = transform_syndrome(y, by, cyclic_shift=cyclic, dyadic_shift=dyadic)
            target, target_by = transform_syndrome(s, by, cyclic_shift=cyclic, dyadic_shift=dyadic)
            assert _add(shifted_x, _product(h, shifted_y)) == target
            assert _parities(shifted_y) == target_by == shifted_by
            assert _parities(shifted_x) == shifted_bx
            restored, restored_by = transform_syndrome(
                target, target_by, cyclic_shift=-cyclic, dyadic_shift=dyadic,
            )
            assert (restored, restored_by) == (s, by)


def test_dyadic_shift_must_permute_nonuniform_parity_labels():
    blocks = ((1, 0, 0), (1, 1, 0))
    shifted, parity = transform_syndrome(blocks, (1, 0), dyadic_shift=1)
    assert shifted == (blocks[1], blocks[0])
    assert parity == (0, 1)
    assert parity != (1, 0)


ACTUAL_PARITIES = {
    "Mito-1-128": ((0, 1), (1, 0)),
    "Mito-1-256": ((1, 1), (0, 1)),
    "Mito-1-512": ((1, 0), (1, 1)),
    "Mito-1-E-128": ((0, 1), (1, 0)),
    "Mito-1-E-256": ((1, 0), (0, 0)),
    "Mito-1-E-512": ((0, 1), (0, 0)),
    "Mito-2-E-128": ((1, 1, 0, 1), (1, 1, 0, 1)),
    "Mito-2-E-256": ((0, 0, 1, 1), (0, 0, 1, 1)),
    "Mito-2-E-512": ((0, 0, 0, 0), (0, 0, 0, 0)),
}


@pytest.mark.parametrize("entry", [entry for entry in HAMMING_PARAMETERS if entry["scheme"] == "Mito"])
def test_actual_parameters_and_serializable_symbolic_descriptor(entry):
    p = entry["parameters"]
    model = MitoKeyParity(p["r"], p["d"], p["wx"], p["wy"])
    assert (model.parity_x, model.parity_y) == ACTUAL_PARITIES[entry["parameter_set"]]
    assert (model.n, model.k, model.w) == (
        2 * p["d"] * p["r"], p["d"] * (p["r"] - 1), sum(p["wx"]) + sum(p["wy"]),
    )
    descriptor = json.loads(json.dumps(model.to_dict(), allow_nan=False))
    assert descriptor["added_rank"] == p["d"]
    assert descriptor["augmented_rank"] == model.n - model.k
    assert "rank cost proxy" in descriptor["interpretation"]
    assert "not an exact structured attack" in descriptor["interpretation"]
    assert descriptor["doom"]["requires_permuted_parity_rhs"] is True
    assert descriptor["doom"]["orbit_size_upper_bound"] == p["d"] * p["r"]
    assert "no weight change or parity time discount" in descriptor["weight_treatment"]
    # Symbolic descriptor stays small even at the largest submitted dimension.
    assert len(json.dumps(descriptor)) < 4000


def test_frozen_inputs_are_copied_and_cross_tuple_overlap_is_allowed():
    wx = [3, 0]
    model = MitoKeyParity(3, 2, wx, [3, 0])
    wx[0] = 0
    assert model.wx == (3, 0)
    assert model.w == 6
    with pytest.raises(FrozenInstanceError):
        model.r = 5


@pytest.mark.parametrize("kwargs", [
    {"r": 4}, {"r": 1}, {"r": True}, {"d": 3}, {"d": 0}, {"d": True},
    {"wx": [1]}, {"wx": [1, -1]}, {"wx": [1, 4]}, {"wx": [True, 1]},
    {"wy": [2, 2]}, {"wy": None},
])
def test_invalid_parity_models_are_rejected(kwargs):
    parameters = {"r": 3, "d": 2, "wx": [1, 1], "wy": [1, 0]}
    parameters.update(kwargs)
    with pytest.raises(ValueError):
        MitoKeyParity(**parameters)


@pytest.mark.parametrize("left,right", [([], []), ([1], [1, 0]), ([0, 1, 0], [1, 0, 1]),
                                       ([2, 0], [0, 1]), ([True], [1])])
def test_invalid_dyadic_vectors_are_rejected(left, right):
    with pytest.raises(ValueError):
        dyadic_multiply(left, right)


@pytest.mark.parametrize("blocks,parity,kwargs", [
    ([], [], {}), ([[1], [0]], [1], {}), ([[1], [0, 1]], [1, 1], {}),
    ([[2]], [0], {}), ([[1]], [1], {"dyadic_shift": 1}),
    ([[1]], [1], {"cyclic_shift": 0.5}),
])
def test_invalid_syndrome_transforms_are_rejected(blocks, parity, kwargs):
    with pytest.raises(ValueError):
        transform_syndrome(blocks, parity, **kwargs)
