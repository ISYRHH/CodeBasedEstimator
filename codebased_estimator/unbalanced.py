"""Finite block-weight support probabilities for outer ISD selection.

Each block independently supplies a uniformly selected coordinate subset.
The remaining inner regions are uniformly shuffled: existing conditional
list-split factors therefore stay unchanged. Matrix-rank and target-orbit
correlations are still the owning algorithm's proxies. No entropy-gap time
discount is applied here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
from functools import lru_cache
from math import comb, fsum, inf, log2


MODEL = "block-hypergeometric-outer-v1"


@dataclass(frozen=True)
class BlockProfile:
    lengths: tuple[int, ...]
    weights: tuple[int, ...]
    target_permutations: tuple[tuple[int, ...], ...] = ()

    def __post_init__(self):
        for name in ("lengths", "weights"):
            value = getattr(self, name)
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"block profile {name} must be a list or tuple")
            object.__setattr__(self, name, tuple(value))
        if (not self.lengths or len(self.lengths) != len(self.weights)
                or any(type(n) is not int or n < 1 for n in self.lengths)
                or any(type(w) is not int or not 0 <= w <= n
                       for n, w in zip(self.lengths, self.weights))):
            raise ValueError("require equally sized block lengths and weights, 0 <= weight <= length")
        try:
            permutations = tuple(tuple(p) for p in self.target_permutations)
        except TypeError as exc:
            raise ValueError("target_permutations must contain coordinate-block permutations") from exc
        size = len(self.lengths)
        for permutation in permutations:
            if (len(permutation) != size or any(type(i) is not int for i in permutation)
                    or sorted(permutation) != list(range(size))
                    or any(self.lengths[i] != self.lengths[j]
                           for i, j in enumerate(permutation))):
                raise ValueError("target permutations must permute equal-length blocks")
        if permutations and (tuple(range(size)) not in permutations
                             or len(set(permutations)) != len(permutations)):
            raise ValueError("target permutations must be distinct and include the identity")
        object.__setattr__(self, "target_permutations", permutations)

    def validate(self, n, w):
        if sum(self.lengths) != n or sum(self.weights) != w:
            raise ValueError("block lengths/weights must sum to the decoding length/weight")

    def preserving_targets(self, total):
        """Count usable targets with this exact profile under a uniform orbit.

        A declared orbit consists of equally sized permutation classes. For
        arbitrary truncated target counts their distribution is unknown; only
        the original target is guaranteed and is used as the fallback.
        """
        if type(total) is not int or total < 1:
            raise ValueError("total targets must be a positive integer")
        if not self.target_permutations or total == 1:
            return total
        classes = len(self.target_permutations)
        if total % classes:
            return 1
        preserving = sum(tuple(self.weights[i] for i in p) == self.weights
                         for p in self.target_permutations)
        return total // classes * preserving

    def to_dict(self):
        return {"lengths": list(self.lengths), "weights": list(self.weights),
                "target_permutations": [list(p) for p in self.target_permutations]}

    @classmethod
    def from_dict(cls, value):
        return cls(**value)


@dataclass(frozen=True)
class OuterProbability:
    log2_probability: float
    log2_uniform_probability: float
    allocation: tuple[int, ...] | None
    method: str

    @property
    def gain(self):
        if self.log2_probability == self.log2_uniform_probability:
            return 0.0
        return self.log2_probability - self.log2_uniform_probability

    def to_dict(self):
        return {"model": MODEL, **asdict(self), "log2_gain": self.gain,
                "allocation_region": "tail", "rank_model": "unchanged",
                "inner_cost_model": "unchanged"}


@lru_cache(maxsize=65536)
def _logcomb(n, w):
    return log2(comb(n, min(w, n-w))) if 0 <= w <= n else -inf


def _logadd(values):
    top = max(values, default=-inf)
    return top if top == -inf else top + log2(fsum(2.0**(x-top) for x in values))


@lru_cache(maxsize=32768)
def _block_distribution(n, w, tail, maximum):
    """Finite hypergeometric coefficients; log recurrence avoids cancellation."""
    row = [-inf] * (maximum+1)
    low, high = max(0, w-tail), min(w, n-tail, maximum)
    if low > high:
        return tuple(row)
    row[low] = _logcomb(n-tail, low) + _logcomb(tail, w-low) - _logcomb(n, w)
    for j in range(low, high):
        row[j+1] = (row[j] + log2(n-tail-j) - log2(j+1)
                    + log2(w-j) - log2(tail-w+j+1))
    return tuple(min(0.0, value) for value in row)


@lru_cache(maxsize=32768)
def log_distribution(profile, allocation, max_weight):
    """Log probabilities for 0..max_weight errors outside the chosen tail."""
    if (type(max_weight) is not int or max_weight < 0
            or len(allocation) != len(profile.lengths)
            or any(type(r) is not int or not 0 <= r <= n
                   for r, n in zip(allocation, profile.lengths))):
        raise ValueError("invalid tail allocation or information weight")
    polynomial = (0.0,)
    for n, w, r in zip(profile.lengths, profile.weights, allocation):
        row = _block_distribution(n, w, r, min(w, max_weight))
        size = min(max_weight+1, len(polynomial)+len(row)-1)
        amax, bmax = max(polynomial), max(row)
        finite_a = [x for x in polynomial if x != -inf]
        finite_b = [x for x in row if x != -inf]
        # Scaled convolution avoids an exponential for every summand. Use
        # full log arithmetic whenever intermediate dynamic range could
        # produce underflow, including rare but valid coefficient tails.
        scaled = None
        if finite_a and finite_b and amax-min(finite_a)+bmax-min(finite_b) < 900:
            a = [2.0**(x-amax) for x in polynomial]
            b = [2.0**(x-bmax) for x in row]
            scaled = tuple(fsum(a[i]*b[j-i] for i in range(
                           max(0, j-len(b)+1), min(j+1, len(a)))) for j in range(size))
        if scaled is not None:
            polynomial = tuple(log2(x)+amax+bmax if x else -inf for x in scaled)
        else:
            polynomial = tuple(_logadd(tuple(polynomial[i] + row[j-i]
                               for i in range(max(0, j-len(row)+1), min(j+1, len(polynomial)))))
                               for j in range(size))
    return tuple(min(0.0, x) for x in polynomial) + (-inf,) * (max_weight+1-len(polynomial))


def log_probability(profile, allocation, information_weight):
    return log_distribution(profile, tuple(allocation), information_weight)[information_weight]


def _weighted_allocation(lengths, weights, total):
    """Capped proportional allocation, with exact integer marginal polishing."""
    low, high = 0.0, float(max(lengths) * max(1, total))
    for _ in range(64):
        scale = (low+high)/2
        if sum(min(n, w*scale) for n, w in zip(lengths, weights)) > total:
            high = scale
        else:
            low = scale
    allocation = [min(n, int(w*low)) for n, w in zip(lengths, weights)]
    # When positive-weight blocks saturate, fill zero-weight blocks in O(m).
    remaining = total-sum(allocation)
    if remaining > len(lengths):
        for i, n in enumerate(lengths):
            if weights[i] == 0:
                take = min(remaining, n-allocation[i])
                allocation[i] += take
                remaining -= take
    while sum(allocation) < total:
        i = max((i for i, n in enumerate(lengths) if allocation[i] < n),
                key=lambda i: weights[i]/(allocation[i]+1))
        allocation[i] += 1
    return tuple(allocation)


@lru_cache(maxsize=8192)
def allocation_candidates(profile, total):
    if type(total) is not int or not 0 <= total <= sum(profile.lengths):
        raise ValueError("tail size must be between zero and the total length")
    n = sum(profile.lengths)
    proportional = [total*size//n for size in profile.lengths]
    for i in sorted(range(len(proportional)),
                    key=lambda i: total*profile.lengths[i] % n, reverse=True)[:total-sum(proportional)]:
        proportional[i] += 1
    weighted = _weighted_allocation(profile.lengths, profile.weights, total)
    complement = tuple(n-r for n, r in zip(profile.lengths, _weighted_allocation(
                       profile.lengths, profile.weights, n-total)))
    return tuple(dict.fromkeys((weighted, tuple(proportional), complement)))


def _all_allocations(lengths, total):
    if len(lengths) == 1:
        if 0 <= total <= lengths[0]:
            yield (total,)
        return
    for first in range(max(0, total-sum(lengths[1:])), min(lengths[0], total)+1):
        for rest in _all_allocations(lengths[1:], total-first):
            yield (first, *rest)


@lru_cache(maxsize=16384)
def optimize_outer(profile, tail_size, information_weight):
    """Best evaluated outer event, including unchanged uniform selection.

    Prange has an exact discrete-concave optimum. Small instances enumerate
    every allocation. Other points use capped weighted/proportional seeds
    and bounded integer exchange, not a global-optimality assertion.
    """
    n, w = sum(profile.lengths), sum(profile.weights)
    if (type(information_weight) is not int or not 0 <= information_weight <= w
            or type(tail_size) is not int or not 0 <= tail_size <= n):
        raise ValueError("invalid outer event")
    uniform = (_logcomb(n-tail_size, information_weight)
               + _logcomb(tail_size, w-information_weight) - _logcomb(n, w))
    if uniform == -inf or len(profile.lengths) == 1:
        return OuterProbability(uniform, uniform, None, "uniform_fallback")
    seeds = allocation_candidates(profile, tail_size)
    best, selected = uniform, None
    method = "bounded_integer_exchange"
    if information_weight in (0, w):
        complement = information_weight == w
        allocation = list(_weighted_allocation(
            profile.lengths, profile.weights, n-tail_size if complement else tail_size))
        # Concave marginal gain log(r/(r-w)); exchanges are exact in integers.
        while True:
            add = [i for i, size in enumerate(profile.lengths) if allocation[i] < size]
            remove = [i for i, weight in enumerate(profile.weights) if allocation[i] > weight]
            if not add or not remove:
                break
            a = max(add, key=lambda i: Fraction(profile.weights[i], allocation[i]+1))
            b = min(remove, key=lambda i: Fraction(profile.weights[i], allocation[i]))
            if a == b or profile.weights[a]*allocation[b] <= profile.weights[b]*(allocation[a]+1):
                break
            allocation[a] += 1
            allocation[b] -= 1
        candidates = (tuple(n-r for n, r in zip(profile.lengths, allocation))
                      if complement else tuple(allocation),)
        method = "exact_discrete_concavity"
    elif n <= 20:
        candidates = _all_allocations(profile.lengths, tail_size)
        method = "exhaustive_integer_allocations"
    else:
        candidates = []
        for seed in sorted(seeds, key=lambda r: log_probability(profile, r, information_weight),
                           reverse=True)[:2]:
            current = seed
            value = log_probability(profile, current, information_weight)
            for step in (16, 4, 1):
                for _ in range(3):
                    improved, move = value, None
                    for a, size in enumerate(profile.lengths):
                        if current[a]+step > size:
                            continue
                        for b in range(len(current)):
                            if a == b or current[b] < step:
                                continue
                            trial = list(current)
                            trial[a] += step
                            trial[b] -= step
                            trial = tuple(trial)
                            score = log_probability(profile, trial, information_weight)
                            if score > improved+1e-12:
                                improved, move = score, trial
                    if move is None:
                        break
                    value, current = improved, move
            candidates.append(current)
    for allocation in candidates:
        score = log_probability(profile, allocation, information_weight)
        if score > best:
            best, selected = score, allocation
    return OuterProbability(min(0.0, best), uniform, selected,
                            method if selected is not None else "uniform_fallback")
