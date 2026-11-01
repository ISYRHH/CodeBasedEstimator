"""Exact public linear observations; no decoding-cost or recovery-success model.

Bit i is coefficient X**i (and message bit i). Variables are (r1, r2, e),
with e retaining all ring coordinates. The small message image is reduced
exactly; full circulant matrices are never allocated. These helpers also
apply to other binary cyclic schemes with the same public observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from functools import cached_property
from math import comb


def _size(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _word(value: int, width: int, name: str) -> int:
    if type(value) is not int or value < 0 or value >> width:
        raise ValueError(f"{name} must fit in {width} bits")
    return value


def _rref(rows, width):
    rows = [_word(row, width, "matrix row") for row in rows]
    pivots = []
    for column in range(width):
        i = len(pivots)
        source = next((j for j in range(i, len(rows)) if rows[j] >> column & 1), None)
        if source is None:
            continue
        rows[i], rows[source] = rows[source], rows[i]
        for j in range(len(rows)):
            if j != i and rows[j] >> column & 1:
                rows[j] ^= rows[i]
        pivots.append(column)
    return tuple(rows[:len(pivots)]), tuple(pivots)


def _nullspace(rows, width):
    rows, pivots = _rref(rows, width)
    pivot_set = set(pivots)
    return tuple((1 << j) | sum(((row >> j) & 1) << pivot
                               for row, pivot in zip(rows, pivots))
                 for j in range(width) if j not in pivot_set)


def _apply(rows, word):
    return sum((bin(row & word).count("1") & 1) << i for i, row in enumerate(rows))


def cyclic_product(left: int, right: int, r: int) -> int:
    """Multiply in F2[X]/(X**r-1), iterating over nonzero right coefficients."""
    _size(r, "ring length")
    if not r:
        raise ValueError("ring length must be positive")
    _word(left, r, "left polynomial")
    _word(right, r, "right polynomial")
    mask, result = (1 << r) - 1, 0
    while right:
        low = right & -right
        shift = low.bit_length() - 1
        result ^= ((left << shift) | (left >> (r - shift))) & mask
        right ^= low
    return result


@dataclass(frozen=True)
class MessageFiber:
    """All compatible messages are particular XOR span(kernel_basis)."""

    particular: int
    kernel_basis: tuple[int, ...]


@dataclass(frozen=True)
class BinaryMessageImage:
    """Small public G matrix, stored as one output word per message bit.

    A zero/empty or rank-deficient generator is allowed. This represents the
    encoder restricted to observed positions, not a replacement HARE encoder.
    """

    output_bits: int
    columns: tuple[int, ...]

    def __post_init__(self):
        _size(self.output_bits, "output_bits")
        object.__setattr__(self, "columns", tuple(
            _word(column, self.output_bits, "generator column") for column in self.columns))

    @property
    def message_bits(self):
        return len(self.columns)

    @cached_property
    def rank(self):
        return len(_rref(self.columns, self.output_bits)[1])

    @cached_property
    def annihilator(self):
        """Full row basis L with LG=0 and ker(L)=im(G)."""
        return _nullspace(self.columns, self.output_bits)

    @cached_property
    def rows(self):
        return tuple(sum(((column >> i) & 1) << j
                         for j, column in enumerate(self.columns))
                     for i in range(self.output_bits))

    @cached_property
    def kernel_basis(self):
        return _nullspace(self.rows, self.message_bits)

    def encode(self, message):
        _word(message, self.message_bits, "message")
        result = 0
        while message:
            low = message & -message
            result ^= self.columns[low.bit_length() - 1]
            message ^= low
        return result

    def eliminate(self, observation):
        _word(observation, self.output_bits, "message-image observation")
        return _apply(self.annihilator, observation)

    def fiber(self, residual):
        """Solve Gm=residual; return None exactly when no message exists."""
        _word(residual, self.output_bits, "residual")
        t = self.message_bits
        rows, pivots = _rref((row | (((residual >> i) & 1) << t)
                             for i, row in enumerate(self.rows)), t + 1)
        if t in pivots:
            return None
        particular = sum(((row >> t) & 1) << pivot for row, pivot in zip(rows, pivots))
        return MessageFiber(particular, self.kernel_basis)


@dataclass(frozen=True)
class CyclicTailObservation:
    """Public u and exact uncompressed tail v2; the KR prefix is excluded.

    u=r1+h*r2 and v2=G_tail*m+R(s*r2+e). Only public polynomials and
    observations enter this object. Checking a supplied candidate is not an
    ISD search, and a compatible message fiber is not a recovered KEM key.
    """

    r: int
    h: int
    s: int
    positions: tuple[int, ...]
    message_image: BinaryMessageImage
    u: int
    v2: int

    def __post_init__(self):
        _size(self.r, "ring length")
        if not self.r:
            raise ValueError("ring length must be positive")
        for name in ("h", "s", "u"):
            _word(getattr(self, name), self.r, name)
        if not isinstance(self.message_image, BinaryMessageImage):
            raise ValueError("message_image must be a BinaryMessageImage")
        positions = tuple(self.positions)
        if (any(type(j) is not int or not 0 <= j < self.r for j in positions)
                or len(set(positions)) != len(positions)):
            raise ValueError("positions must be distinct ring indices")
        if len(positions) != self.message_image.output_bits:
            raise ValueError("positions must match message-image output bits")
        object.__setattr__(self, "positions", positions)
        _word(self.v2, len(positions), "v2")

    def project(self, word):
        _word(word, self.r, "ring word")
        return sum(((word >> j) & 1) << i for i, j in enumerate(self.positions))

    def _candidate_image(self, r1, r2, e):
        for name, value in (("r1", r1), ("r2", r2), ("e", e)):
            _word(value, self.r, name)
        return (r1 ^ cyclic_product(self.h, r2, self.r),
                self.project(cyclic_product(self.s, r2, self.r) ^ e))

    def apply(self, r1, r2, e):
        """Matrix-free action on full-length (r1,r2,e), after eliminating m."""
        u, tail = self._candidate_image(r1, r2, e)
        return u, self.message_image.eliminate(tail)

    @property
    def rhs(self):
        return self.u, self.message_image.eliminate(self.v2)

    def accepts(self, r1, r2, e):
        """Test the linear observations only; no weight or KR validation."""
        return self.apply(r1, r2, e) == self.rhs

    def messages_for(self, r1, r2, e):
        u, tail = self._candidate_image(r1, r2, e)
        return self.message_image.fiber(tail ^ self.v2) if u == self.u else None

    @property
    def rank(self):
        # I on r1 and the independent L rows on e certify this exact rank.
        return self.r + len(self.positions) - self.message_image.rank

    @property
    def block_parity_added_rank(self):
        """Rank added by the three FULL-length block parity rows.

        The r1 row follows from parity(u) and the r2 row. The e row is
        independent when positions omit any ring coordinate; for a complete
        observation it is redundant exactly when L contains the all-one row.
        This is ambient rank, with no extra entropy or cost discount.
        """
        q = len(self.positions)
        if q < self.r:
            return 2
        rows = self.message_image.annihilator
        includes_parity = len(_rref(rows + ((1 << q) - 1,), q)[1]) == len(rows)
        return 1 if includes_parity else 2

    def to_dict(self):
        q, d = len(self.positions), self.message_image.rank
        return {
            "contract": "cyclic-public-tail-linear-v1",
            "variable_order": ["r1", "r2", "e"],
            "error_coordinates": "full ring; fixed full weight is not a tail weight",
            "ring_length": self.r, "tail_bits": q,
            "message_bits": self.message_image.message_bits, "message_rank": d,
            "message_kernel_dimension": self.message_image.message_bits - d,
            "remaining_tail_constraints": q - d,
            "linear_rank": self.rank, "full_variable_bits": 3 * self.r,
            "block_parity_added_rank": self.block_parity_added_rank,
            "projected_formal_dimensions": {"n": 2 * self.r + q, "k": self.r + d},
            "total_attack_time_log2": None,
            "scope": "Linear compatibility only; KR constraints, usable-solution probability "
                     "and recovery costs are not modeled. No default estimator route is added.",
        }


def projected_weight_distribution(r: int, retained: int, weight: int):
    """Exact prior Pr[wt(R e)=j] for uniformly sampled full-weight e.

    This is neither the weight of L R e nor a ciphertext-conditioned posterior.
    All omitted coordinates remain unknown; compatible completions require
    0 <= weight-j <= r-retained.
    """
    for name, value in (("r", r), ("retained", retained), ("weight", weight)):
        _size(value, name)
    if retained > r or weight > r:
        raise ValueError("require retained <= r and weight <= r")
    return {j: Fraction(comb(retained, j) * comb(r - retained, weight - j), comb(r, weight))
            for j in range(max(0, weight - (r - retained)), min(weight, retained) + 1)}
