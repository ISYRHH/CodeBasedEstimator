"""Symbolic Mito key-parity dimensions and small-vector algebra helpers.

The dimensions describe the exact augmented linear system. Estimating its
cost as random SD is a rank cost proxy, not an exact structured attack.
No full cyclic or dyadic matrix is constructed by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


def _power_of_two(value: int) -> bool:
    return type(value) is int and value > 0 and value & (value - 1) == 0


def _bits(values: Iterable[int], name: str) -> tuple[int, ...]:
    try:
        result = tuple(values)
    except TypeError as exc:
        raise ValueError(f"{name} must be an iterable of binary integers") from exc
    if any(type(value) is not int or value not in (0, 1) for value in result):
        raise ValueError(f"{name} must contain only binary integers")
    return result


def dyadic_multiply(left: Iterable[int], right: Iterable[int]) -> tuple[int, ...]:
    """Multiply small GF(2) dyadic vectors using xor-index convolution.

    For ``a = E(h)``, this computes ``B_h * b`` without constructing B_h:
    ``result[i] = sum_j a[i xor j] * b[j] mod 2``.
    """
    left, right = _bits(left, "left"), _bits(right, "right")
    if len(left) != len(right) or not _power_of_two(len(left)):
        raise ValueError("dyadic vectors must have the same power-of-two length")
    return tuple(sum(left[i ^ j] * right[j] for j in range(len(left))) % 2
                 for i in range(len(left)))


def transform_syndrome(
    syndrome_blocks: Iterable[Iterable[int]],
    parity_y: Iterable[int],
    *,
    cyclic_shift: int = 0,
    dyadic_shift: int = 0,
) -> tuple[tuple[tuple[int, ...], ...], tuple[int, ...]]:
    """Apply a small-vector DOOM group action to ``(s, E(y))``.

    Cyclic shifts rotate each r-bit block right. Dyadic shifts replace block
    index i by ``i xor dyadic_shift`` and MUST also permute parity labels.
    Thus the transformed target is ``(P s, D_g parity_y)`` under the same
    augmented matrix. This operation does not assert orbit independence.
    """
    try:
        blocks = tuple(_bits(block, "syndrome block") for block in syndrome_blocks)
    except TypeError as exc:
        raise ValueError("syndrome_blocks must be an iterable of binary blocks") from exc
    parity = _bits(parity_y, "parity_y")
    d = len(blocks)
    if not _power_of_two(d) or len(parity) != d:
        raise ValueError("the number of blocks must be a power of two and match parity_y")
    r = len(blocks[0])
    if not r or any(len(block) != r for block in blocks):
        raise ValueError("syndrome blocks must have the same positive length")
    if type(cyclic_shift) is not int:
        raise ValueError("cyclic_shift must be an integer")
    if type(dyadic_shift) is not int or not 0 <= dyadic_shift < d:
        raise ValueError("dyadic_shift must be an integer in [0, d)")
    shifted = tuple(tuple(blocks[i ^ dyadic_shift][(j - cyclic_shift) % r]
                          for j in range(r)) for i in range(d))
    return shifted, tuple(parity[i ^ dyadic_shift] for i in range(d))


@dataclass(frozen=True)
class MitoKeyParity:
    """Exact parity-augmented dimensions, exposed only as a rank cost proxy.

    ``wx`` and ``wy`` give the fixed weights of the d cyclic components.
    Component supports within each tuple are disjoint. The x and y tuples
    are sampled independently; their supports may overlap one another.
    Public h is not needed to compute dimensions or fixed parity syndromes.
    Its parity convolution matrix is retained symbolically in the descriptor.
    """

    r: int
    d: int
    wx: tuple[int, ...]
    wy: tuple[int, ...]

    def __post_init__(self):
        if type(self.r) is not int or self.r < 3 or self.r % 2 != 1:
            raise ValueError("r must be an odd integer of at least 3")
        if not _power_of_two(self.d):
            raise ValueError("d must be a positive power of two")
        for name in ("wx", "wy"):
            try:
                weights = tuple(getattr(self, name))
            except TypeError as exc:
                raise ValueError(f"{name} must contain d integer block weights") from exc
            if len(weights) != self.d or any(
                type(weight) is not int or not 0 <= weight <= self.r for weight in weights
            ):
                raise ValueError(f"{name} must contain d integer block weights in [0, r]")
            if sum(weights) > self.r:
                raise ValueError(f"sum({name}) must not exceed r for disjoint component supports")
            object.__setattr__(self, name, weights)

    @property
    def n(self) -> int:
        return 2 * self.d * self.r

    @property
    def k(self) -> int:
        return self.d * self.r - self.added_rank

    @property
    def w(self) -> int:
        return sum(self.wx) + sum(self.wy)

    @property
    def parity_x(self) -> tuple[int, ...]:
        return tuple(weight % 2 for weight in self.wx)

    @property
    def parity_y(self) -> tuple[int, ...]:
        return tuple(weight % 2 for weight in self.wy)

    @property
    def added_rank(self) -> int:
        return self.d

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe descriptor with no sampled h or large matrices."""
        return {
            "model": "mito-key-parity-rank-v1",
            "interpretation": "Exact augmented linear dimensions; generic random-SD costs "
            "are a rank cost proxy, not an exact structured attack.",
            "r": self.r,
            "d": self.d,
            "weights_x": list(self.wx),
            "weights_y": list(self.wy),
            "parity_x": list(self.parity_x),
            "parity_y": list(self.parity_y),
            "n": self.n,
            "k": self.k,
            "w": self.w,
            "q": 2,
            "base_rank": self.d * self.r,
            "added_rank": self.added_rank,
            "augmented_rank": self.d * self.r + self.added_rank,
            "parity_map": "E = I_d tensor 1_r^T; E(v)_i = sum_j v_i[j] mod 2",
            "public_parity_action": "B_h[i,j] = E(h)[i xor j]; E A_h = B_h E; "
            "B_h is determined by public h and need not be invertible",
            "augmented_matrix": "H_P = [[I_(d*r), A_h], [0, E]]",
            "augmented_syndrome": "(s, parity_y)",
            "x_parity_redundancy": "[E,0] = E [I_(d*r),A_h] + B_h [0,E]; "
            "E(s) = parity_x + B_h parity_y",
            "sampling": "Component supports are disjoint within x and within y; "
            "x and y are independent, with no cross-tuple disjointness requirement.",
            "weight_treatment": "Keep W = sum(wx) + sum(wy); no weight change or parity time discount.",
            "rank_information_limit": "Added ambient rank d does not imply d new bits beyond fixed W "
            "or a d-bit time gain. Global weight parity may already imply a parity combination.",
            "doom": {
                "group": "C_r x (C_2)^log2(d)",
                "orbit_size_upper_bound": self.d * self.r,
                "covariance": "H_P diag(P,P) = diag(P,D_g) H_P",
                "syndrome_action": "(s, parity_y) -> (P s, D_g parity_y)",
                "requires_permuted_parity_rhs": True,
                "full_orbit_note": "Using d*r targets requires a full usable orbit assumption; "
                "distinctness and independence do not follow from the covariance identity.",
            },
        }
