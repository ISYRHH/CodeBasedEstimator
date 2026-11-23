"""Zero-direction maximal minors. All inputs are dimensions or block counts."""

from __future__ import annotations

from itertools import permutations
from math import comb, fsum, log, log1p, log2, prod

from .rank_sd_schemes import lcombv, log2_sum
from .zd_mm_profiles import Profile


def _direct_rows(blocks, dimension):
    """Least degree-R coefficient over systematic block orders, in the extension field."""
    rank = sum(r for _, r in blocks)
    if dimension < 0 or sum(n for n, _ in blocks) - dimension - 1 < rank:
        return 0
    if len(blocks) == 1:
        return comb(blocks[0][0] - dimension - 1, rank)

    counts = []
    for order in set(permutations(blocks)):
        pivots = dimension + 1
        coeff = [1] + [0] * rank
        for length, block_rank in order:
            assigned = min(pivots, length)
            pivots -= assigned
            free = length - assigned
            lower = max(0, block_rank - assigned)
            # Multiply by the block's truncated binomial polynomial.
            updated = [0] * (rank + 1)
            for degree in range(lower, min(free, rank) + 1):
                factor = comb(free, degree)
                for previous in range(rank - degree + 1):
                    updated[degree + previous] += factor * coeff[previous]
            coeff = updated
        counts.append(coeff[rank])
    return min(counts)


def _equations(profile, kept, guesses):
    dimension = profile.k - sum(guesses)
    image = list(kept)
    if profile.noise_block is not None:
        i = profile.noise_block
        kernel = max(0, profile.message_dimension - guesses[i])
        dimension -= kernel
        if image[i]:
            image[i] -= kernel
            if image[i] < profile.ranks[i]:
                return 0

    if profile.overlap:
        r, s = profile.ranks
        rank = r + s - profile.overlap
        h = sum(image) - dimension - 1
        if dimension < 0 or h < rank:
            return 0
        left, right = max(0, h - image[1]), max(0, h - image[0])
        shared = h - left - right
        rows = sum(comb(left, i) * comb(right, j) * lcombv(shared, rank - i - j)
                   for i in range(min(left, r) + 1) for j in range(min(right, s) + 1))
    else:
        blocks = tuple((n, r) for n, r in zip(image, profile.ranks) if n)
        rows = _direct_rows(blocks, dimension)
    return profile.m * rows


def _minors(lengths, degrees):
    return sum(prod(lcombv(n, r) for n, r in zip(lengths, exponents)) for exponents in degrees)


def _log_full_rank(length, rank, d=1):
    """Log2 probability that length columns span rank dimensions over GF(2^d)."""
    if length < rank:
        raise ValueError("The sampled block is too short for its specified rank.")
    return fsum(log1p(-2.0 ** (d * (i - length))) for i in range(rank)) / log(2)


def _success_neglog2(profile, kept):
    originals = profile.probability_lengths or profile.lengths
    d = profile.d
    loss = []
    for n, r, a, u in zip(originals, profile.ranks, profile.guesses, kept):
        # The source samples binary full-rank blocks before field packing.
        # A punctured-away block may use every surviving original coordinate.
        original = _log_full_rank(d * n, r)
        retained = _log_full_rank(u, r, d) if u else _log_full_rank(d * (n - a), r)
        loss.append(d * a * r + original - retained)
    for sample, whole, rank in profile.sample_geometry:
        loss.append(_log_full_rank(whole, rank) - _log_full_rank(sample, rank))
    return fsum(loss)


def evaluate(profile: Profile, omega: float) -> tuple[float, dict]:
    """Price one selected ZD-MM configuration; stage costs include expected repetitions.

    Indices in the input profile are zero-based. The output reports the contraction
    block using the paper's one-based numbering.
    """
    if not 2 <= omega <= 3:
        raise ValueError("The matrix multiplication exponent must lie between 2 and 3.")
    n, r, a, p = profile.lengths, profile.ranks, profile.guesses, profile.punctures
    if not (len(n) == len(r) == len(a) == len(p)) or not 0 <= profile.block < len(n):
        raise ValueError("ZD-MM requires matching block vectors and a contraction block.")
    if profile.overlap and (len(n) != 2 or not 0 < profile.overlap <= min(r)):
        raise ValueError("A support intersection must be shared by two blocks.")
    kept = tuple(ni - ai - pi for ni, ai, pi in zip(n, a, p))
    j = profile.block
    if (any(x < 0 for x in (*a, *p, *kept)) or any(0 < u < ri for u, ri in zip(kept, r))
            or kept[j] <= r[j] or sum(a) >= profile.k):
        raise ValueError("The block guesses and punctures do not admit a local zero direction.")

    active_ranks = tuple(ri if u else 0 for u, ri in zip(kept, r))
    rank = sum(active_ranks) - profile.overlap
    if profile.overlap:
        degrees = [(i, rank - i) for i in range(r[0] - profile.overlap, r[0] + 1)]
    else:
        degrees = [active_ranks]
    variables = _minors(kept, degrees)
    equations = _equations(profile, kept, a)
    delta = variables - equations
    after = list(kept)
    after[j] -= 1
    after_guesses = list(a)
    after_guesses[j] += 1
    variables_after = _minors(after, degrees)
    equations_after = _equations(profile, after, after_guesses)
    if equations <= 0 or delta <= 1 or min(equations, equations_after) < variables_after - 1:
        raise ValueError("ZD-MM requires an underdetermined parent and enough equations after contraction.")

    output_degrees = [tuple(degree - (i == j) for i, degree in enumerate(row))
                      for row in degrees if row[j] > 0]
    contraction_rows = _minors(kept, output_degrees)
    contraction_rank = variables - variables_after
    d, m = profile.d, profile.m
    local_length = r[j] + 1
    directions = (2 ** (d * local_length) - 1) // (2 ** d - 1)

    length = sum(n)
    verify = m * m * (length * rank ** 2 + rank ** 3 + length * rank + length ** 2) + m * length ** 2
    recover = rank * sum(kept) * delta + verify + m * m * profile.terminal_length ** 3
    samples = profile.extra_samples
    recover += samples * m * m * length ** 2 * rank
    log_recover = log2(recover)
    if samples:
        complete = log2(samples * m * length) + (omega - 1) * log2(rank * length)
        log_recover = log2_sum([log_recover, complete])

    neglog = _success_neglog2(profile, kept)
    # Reprice each stage in expected binary operations; d^2 is the field conversion.
    overhead = neglog + 2 * log2(d)
    stages = {
        "setup": log2(m * m * length ** 3),
        "kernel": log2(variables) + (omega - 1) * log2(equations),
        "prepare": log2(d * local_length * contraction_rank * delta),
        "update": log2(directions * contraction_rows * delta),
        "solve": log2(directions * contraction_rows) + (omega - 1) * log2(delta),
        "recover": log2(directions) + log_recover,
    }
    stage_log2 = {step: value + overhead for step, value in stages.items()}
    details = {
        "route": profile.route, "d": d, "m": m, "k": profile.k,
        "lengths": list(n), "ranks": list(r), "guesses": list(a), "punctures": list(p),
        "kept": list(kept), "block": j + 1, "overlap": profile.overlap,
        "equations": equations, "variables": variables, "kernel_dimension": delta,
        "equations_after": equations_after, "variables_after": variables_after,
        "contraction_rank": contraction_rank, "contraction_rows": contraction_rows,
        "directions": directions, "success_neglog2": neglog, "stage_log2": stage_log2,
    }
    if profile.noise_block is not None:
        details.update(noise_block=profile.noise_block + 1, message_dimension=profile.message_dimension)
    if profile.probability_lengths:
        details["probability_lengths"] = list(profile.probability_lengths)
    if profile.sample_geometry:
        details.update(sample_geometry=[list(row) for row in profile.sample_geometry],
                       extra_samples=samples, terminal_length=profile.terminal_length)
    return log2_sum(stage_log2.values()), details
