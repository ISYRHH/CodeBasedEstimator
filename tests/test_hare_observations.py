"""Exact enumeration independent of the compact public-tail implementation."""

from collections import Counter
from fractions import Fraction
from itertools import combinations, product
import json
from math import comb
from pathlib import Path
from random import Random

import pytest

from codebased_estimator.hare_observations import (
    BinaryMessageImage, CyclicTailObservation, cyclic_product,
    projected_weight_distribution,
)
from codebased_estimator.hamming import hamming_catalogue, hamming_instances


def _parity(word):
    return bin(word).count("1") % 2


def _multiply(a, b, r):
    result = 0
    for i in range(r):
        for j in range(r):
            if (a >> i & 1) and (b >> j & 1):
                result ^= 1 << ((i + j) % r)
    return result


def _image(columns, message):
    result = 0
    for j, column in enumerate(columns):
        if message >> j & 1:
            result ^= column
    return result


def _span(basis):
    return {_image(basis, x) for x in range(1 << len(basis))}


def _rank(rows):
    """Independent highest-pivot rank, without production elimination."""
    pivots = {}
    for row in rows:
        while row:
            high = row.bit_length() - 1
            if high not in pivots:
                pivots[high] = row
                break
            row ^= pivots[high]
    return len(pivots)


def _project(word, positions):
    return sum(((word >> j) & 1) << i for i, j in enumerate(positions))


def _observation(r, h, s, positions, image, u=0, v2=0):
    return CyclicTailObservation(r, h, s, positions, image, u, v2)


def test_message_images_and_affine_fibers_exhaustively():
    for q, t in product(range(4), repeat=2):
        for columns in product(range(1 << q), repeat=t):
            image = BinaryMessageImage(q, columns)
            inverse = {}
            for message in range(1 << t):
                encoded = _image(columns, message)
                assert image.encode(message) == encoded
                inverse.setdefault(encoded, set()).add(message)
            assert len(inverse) == 1 << image.rank
            assert _rank(image.annihilator) == q - image.rank
            assert len(image.kernel_basis) == t - image.rank
            assert _span(image.kernel_basis) == inverse[0]
            for residual in range(1 << q):
                fiber = image.fiber(residual)
                assert (image.eliminate(residual) == 0) == (residual in inverse)
                if residual not in inverse:
                    assert fiber is None
                else:
                    actual = {fiber.particular ^ z for z in _span(fiber.kernel_basis)}
                    assert actual == inverse[residual]


@pytest.mark.parametrize("r", range(1, 6))
def test_cyclic_direction_against_coefficient_convolution(r):
    for a, b in product(range(1 << r), repeat=2):
        assert cyclic_product(a, b, r) == _multiply(a, b, r)


def test_exists_message_equivalence_all_tiny_public_observations():
    # All binary r=2 public h/s, subsets and one-bit message generators.
    # e keeps its full coordinates, including those omitted from the tail.
    r = 2
    for h, s, mask in product(range(4), range(4), range(4)):
        positions = tuple(j for j in range(r) if mask >> j & 1)
        q = len(positions)
        for column in range(1 << q):
            image = BinaryMessageImage(q, (column,))
            for r1, r2, e in product(range(4), repeat=3):
                u = r1 ^ _multiply(h, r2, r)
                base = _project(_multiply(s, r2, r) ^ e, positions)
                messages = {base ^ _image((column,), m) for m in range(2)}
                for v in range(1 << q):
                    obs = _observation(r, h, s, positions, image, u, v)
                    assert obs.accepts(r1, r2, e) == (v in messages)
                    assert (obs.messages_for(r1, r2, e) is not None) == (v in messages)
                    wrong_u = _observation(r, h, s, positions, image, u ^ 1, v)
                    assert not wrong_u.accepts(r1, r2, e)
                    assert wrong_u.messages_for(r1, r2, e) is None


@pytest.mark.parametrize("positions", [(), (2,), (3, 0), (0, 1, 2, 3)])
@pytest.mark.parametrize("columns", [(), (0, 0), (1, 1), (1, 2)])
def test_exact_full_operator_rank_and_parity_rows(positions, columns):
    r, q = 4, len(positions)
    columns = tuple(c & ((1 << q) - 1) for c in columns)
    image = BinaryMessageImage(q, columns)
    for h, s in product((0, 1, 3, 15), repeat=2):
        obs = _observation(r, h, s, positions, image)
        # Independently build rows only for tiny tests; no production matrix.
        operator_columns = []
        for j in range(3 * r):
            parts = [0, 0, 0]
            parts[j // r] = 1 << (j % r)
            first, tail = obs.apply(*parts)
            operator_columns.append(first | tail << r)
        rows = [sum(((column >> i) & 1) << j
                    for j, column in enumerate(operator_columns))
                for i in range(r + q - image.rank)]
        assert _rank(rows) == obs.rank == r + q - image.rank
        parities = [((1 << r) - 1) << (block * r) for block in range(3)]
        assert _rank(rows + parities) - _rank(rows) == obs.block_parity_added_rank
        if q < r:
            assert obs.block_parity_added_rank == 2
        if q == r and image.rank == 0:
            assert obs.block_parity_added_rank == 1


def test_complete_double_core_adds_one_independent_parity_row():
    r = 4
    for h in range(1 << r):
        rows = [(1 << i) | sum(((h >> ((i - j) % r)) & 1) << (r + j)
                               for j in range(r)) for i in range(r)]
        assert _rank(rows) == r
        j = (1 << r) - 1
        assert _rank(rows + [j, j << r]) == r + 1


def test_projection_is_not_zero_padding_and_annihilator_does_not_preserve_weight():
    image = BinaryMessageImage(1, ())
    obs = _observation(3, 0, 0b100, (0,), image, u=0, v2=0)
    # s*r2 has an omitted nonzero coordinate. The observed tail is still zero.
    assert obs.accepts(0, 1, 0)
    assert _multiply(obs.s, 1, 3) != 0
    # L repeats information as a linear map, so wt(L e_T) need not be wt(e_T).
    image = BinaryMessageImage(3, (0b111,))
    assert bin(image.eliminate(0b001)).count("1") == 2
    assert bin(0b001).count("1") == 1


def test_nonprefix_projection_and_old_column_order_are_explicitly_distinct():
    r, positions = 3, (2, 0)
    obs = _observation(r, 0b011, 0b101, positions, BinaryMessageImage(2, (0,)))
    for r1, r2, e in product(range(1 << r), repeat=3):
        old_order = (r1, e, r2)
        new_order = (old_order[0], old_order[2], old_order[1])
        u, tail = obs.apply(*new_order)
        assert u == r1 ^ _multiply(obs.h, r2, r)
        assert tail == _project(_multiply(obs.s, r2, r) ^ e, positions)


@pytest.mark.parametrize("r", range(7))
def test_projected_weight_prior_matches_all_full_fixed_weight_words(r):
    for retained, weight in product(range(r + 1), repeat=2):
        counts = Counter()
        for support in combinations(range(r), weight):
            counts[sum(j < retained for j in support)] += 1
        expected = {j: Fraction(count, comb(r, weight)) for j, count in counts.items()}
        actual = projected_weight_distribution(r, retained, weight)
        assert actual == expected
        assert sum(actual.values()) == 1


def test_frozen_generators_match_current_catalogue_and_matrix_free_large_ring():
    fixture = json.loads((Path(__file__).parent / "data/hare_tail_generators.json").read_text())
    assert fixture["schema"] == "hare-tail-generators-v1"
    entries = fixture["entries"]
    assert [entry["parameter_set"] for entry in entries] == ["HARE-2", "HARE-5", "HARE-7", "HARE-9"]
    catalogue = {row["parameter_set"]: row["parameters"] for row in hamming_catalogue()}
    rng = Random(20261101)
    for entry, expected_d, expected_constraints in zip(entries, (6, 6, 6, 7), (23, 18, 21, 35)):
        r, t, q = entry["ring_length"], entry["message_bits"], entry["tail_bits"]
        parameters = catalogue[entry["parameter_set"]]
        assert (r, entry["wr"], entry["we"]) == (parameters["r"], parameters["wr"], parameters["we"])
        image = BinaryMessageImage(q, tuple(entry["message_columns"]))
        assert image.message_bits == t
        assert image.rank == expected_d
        assert len(image.annihilator) == expected_constraints
        assert len(image.kernel_basis) == t - expected_d
        positions = tuple(range(entry["tail_start"], entry["encoded_bits"]))
        h, s = rng.getrandbits(r), rng.getrandbits(r)
        # Sparse deterministic test witness, not recovered by this module.
        r1 = sum(1 << j for j in rng.sample(range(r), entry["wr"]))
        r2 = sum(1 << j for j in rng.sample(range(r), entry["wr"]))
        e = sum(1 << j for j in rng.sample(range(r), entry["we"]))
        m = rng.getrandbits(t)
        u = r1 ^ cyclic_product(h, r2, r)
        v = image.encode(m) ^ _project(cyclic_product(s, r2, r) ^ e, positions)
        obs = _observation(r, h, s, positions, image, u, v)
        assert obs.accepts(r1, r2, e)
        fiber = obs.messages_for(r1, r2, e)
        assert image.encode(fiber.particular) == image.encode(m)
        assert image.encode(fiber.particular ^ fiber.kernel_basis[0]) == image.encode(m)
        descriptor = obs.to_dict()
        assert descriptor["linear_rank"] == r + expected_constraints
        assert descriptor["message_kernel_dimension"] == t - expected_d
        assert descriptor["block_parity_added_rank"] == 2
        assert descriptor["total_attack_time_log2"] is None
        distribution = projected_weight_distribution(r, q, entry["we"])
        assert sum(distribution.values()) == 1
        assert json.loads(json.dumps(descriptor)) == descriptor


def test_no_new_priced_routes_or_renaming_of_current_hare_catalogue():
    hare = [row for row in hamming_catalogue() if row["scheme"] == "HARE"]
    assert [row["parameter_set"] for row in hare] == ["HARE-1", "HARE-2", "HARE-3", "HARE-5", "HARE-7", "HARE-9"]
    assert len(hamming_instances()) == 123
    for entry in hare:
        instances = hamming_instances(parameter_sets=[entry["parameter_set"]])
        assert len(instances) == 3
        assert all(instance.route_id != "public_tail" for instance in instances)


@pytest.mark.parametrize("args", [(-1, ()), (True, ()), (2, (4,)), (0, (1,)), (2, (True,))])
def test_invalid_message_images(args):
    with pytest.raises((TypeError, ValueError)):
        BinaryMessageImage(*args)


@pytest.mark.parametrize("update", [{"r": 0}, {"r": True}, {"h": -1}, {"s": 8},
    {"u": True}, {"v2": 2}, {"positions": (3,)}, {"positions": (0, 0)},
    {"positions": (True,)}, {"message_image": None}])
def test_invalid_public_observation(update):
    values = dict(r=3, h=0, s=1, positions=(0,), message_image=BinaryMessageImage(1, (0,)), u=0, v2=0)
    values.update(update)
    with pytest.raises((TypeError, ValueError)):
        CyclicTailObservation(**values)


@pytest.mark.parametrize("args", [(-1, 0, 0), (3, 4, 0), (3, 1, 4), (True, 0, 0)])
def test_invalid_weight_prior(args):
    with pytest.raises(ValueError):
        projected_weight_distribution(*args)
