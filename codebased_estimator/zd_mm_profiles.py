"""Input configurations for the 34 ZD-MM estimates in the DCLens report.

Lengths, ranks, guesses and punctures use the block order of Appendix A.
Block indices in Python start at zero. No estimated work factors are stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .schemes_final import BRA_DATA, BRQC_DATA, CM, LOONG


@dataclass(frozen=True)
class Profile:
    route: str
    m: int
    k: int
    lengths: tuple[int, ...]
    ranks: tuple[int, ...]
    guesses: tuple[int, ...]
    punctures: tuple[int, ...]
    block: int
    d: int = 1
    overlap: int = 0
    probability_lengths: tuple[int, ...] = ()
    # Each triple gives a selected row/column length, full sample length and rank.
    sample_geometry: tuple[tuple[int, int, int], ...] = ()
    extra_samples: int = 0
    terminal_length: int = 0
    message_dimension: int = 0
    noise_block: Optional[int] = None


def _loong(level, goal, guesses, punctures, block):
    data = LOONG[level]
    n, n1 = data["n"], data["n1"]
    if goal == "key_recovery":
        ranks, overlap = data["A"]
        lengths = (n, n + 1)
        samples = n1
        geometry = tuple((n, n * samples, rank) for rank in ranks)
        route, terminal = "known_support_element", 0
    else:
        ranks, overlap = data["B"]
        lengths = (n, n + n1)
        samples = {128: 10, 256: 13, 384: 15, 512: 15}[level]  # ciphertext rows
        geometry = tuple((size, size * samples, rank) for size, rank in zip(lengths, ranks))
        route, terminal = "message_free_complete_row", n1 * samples
    return Profile(route, data["m"], n, lengths, ranks, guesses, punctures, block,
                   overlap=overlap, sample_geometry=geometry, extra_samples=samples - 1,
                   terminal_length=terminal)


def _bra(level, goal, guesses, block):
    data = BRA_DATA[level]
    # Transposition exchanges the original block length and extension degree.
    length, m = data["m"], data["k"]
    if goal == "key_recovery":
        ranks = tuple(data["A"][1])
        route = "transposed_key"
    else:
        left, _, right = data["B"][1]
        ranks = (left, right)
        route = "transposed_first_component"
    return Profile(route, m, length, (length, length), ranks, guesses, (0, 0), block)


def _brqc(level, goal, guesses, punctures, block):
    data = BRQC_DATA[level]
    n = data["k"]
    if goal == "key_recovery":
        return Profile("two_block_key", data["m"], n, (n, n), tuple(data["A"][1]),
                       guesses, punctures, block)
    ranks = tuple(data["B"][1])
    # The report puts the noise block last at levels 128 and 256.
    noise_block = 1
    if level in (128, 256):
        ranks = (ranks[0], ranks[2], ranks[1])
        noise_block = 2
    return Profile("three_block_message_projection", data["m"], n + 3, (n,) * 3, ranks,
                   guesses, punctures, block, message_dimension=3, noise_block=noise_block)


def _cmulti(level, goal, zeros):
    data = CM[level]
    n, n1 = data["n"], data["N1"]
    if goal == "key_recovery":
        rank = data["w1"]
        length, k = 2 * n + 1, n
        geometry = ((2 * n, 2 * n * n1, rank),)
        route, samples, terminal = "known_support_element", n1 - 1, 0
    else:
        rank = data["w2"]
        length, k = 2 * n + n1, n + {128: 3, 256: 3, 512: 4}[level]
        geometry = ((length, length * data["N2"], rank),)
        route, samples, terminal = "one_column_message_projection", 0, n1
    return Profile(route, data["m"], k, (length,), (rank,), (zeros,), (0,), 0,
                   sample_geometry=geometry, extra_samples=samples, terminal_length=terminal)


def _report_profiles():
    key, msg = "key_recovery", "msg_recovery"
    profiles = {}
    for level, key_args, msg_args in (
        (128, ((7, 0), (0, 0), 1), ((5, 0), (0, 0), 0)),
        (256, ((21, 0), (0, 0), 0), ((18, 0), (0, 0), 0)),
        (384, ((29, 0), (0, 0), 1), ((29, 0), (1, 0), 0)),
        (512, ((43, 0), (1, 0), 0), ((34, 0), (0, 0), 1)),
    ):
        name = f"BAG-Loong-{level}"
        profiles[name, key] = _loong(level, key, *key_args)
        profiles[name, msg] = _loong(level, msg, *msg_args)

    # These are the reduced Piglet dimensions. At level 128, m=47, n=43.
    profiles["BAG-Piglet-128", key] = Profile(
        "three_block_key", 47, 43, (43,) * 3, (4,) * 3, (0, 0, 5), (0, 0, 38), 0)
    profiles["BAG-Piglet-128", msg] = Profile(
        "first_component", 47, 86, (43,) * 3, (2, 3, 3), (41, 0, 0), (2, 2, 0), 2)
    profiles["BAG-Piglet-256", key] = Profile(
        "packed_key", 79, 39, (39,) * 3, (6,) * 3, (6, 0, 0), (0,) * 3, 1, d=2)
    profiles["BAG-Piglet-256", msg] = Profile(
        "packed_ciphertext", 79, 52, (26,) * 4, (3, 3, 4, 4), (17, 0, 0, 0), (1, 0, 0, 0), 1, d=3)
    profiles["BAG-Piglet-384", key] = Profile(
        "packed_key", 103, 53, (53,) * 3, (7,) * 3, (12, 0, 0), (0,) * 3, 1, d=2)
    profiles["BAG-Piglet-384", msg] = Profile(
        "packed_ciphertext", 103, 106, (53,) * 4, (4,) * 4, (37, 0, 0, 0), (16, 0, 0, 0), 1, d=2)
    profiles["BAG-Piglet-512", key] = Profile(
        "three_block_key", 131, 125, (125,) * 3, (8,) * 3, (0, 0, 30), (0, 0, 1), 2)
    profiles["BAG-Piglet-512", msg] = Profile(
        "ciphertext_zero_tail", 131, 250, (125, 125, 120, 125), (4, 4, 5, 5),
        (0, 96, 0, 0), (0, 29, 0, 0), 0, probability_lengths=(125,) * 4)

    for level, key_args, msg_args in (
        (128, ((3, 3), 1), ((0, 14), 1)),
        (256, ((0, 13), 0), ((0, 26), 0)),
        (512, ((0, 32), 1), ((54, 0), 0)),
    ):
        name = f"BRA-{level}"
        profiles[name, key] = _bra(level, key, *key_args)
        profiles[name, msg] = _bra(level, msg, *msg_args)

    for level, key_guesses, msg_args in (
        (128, (0, 21), ((0, 0, 0), (0, 0, 16), 0)),
        (256, (36, 0), ((16, 0, 0), (0, 0, 0), 2)),
        (512, (71, 0), ((0, 39, 0), (0, 0, 0), 0)),
    ):
        name = f"BRQC-{level}"
        profiles[name, key] = _brqc(level, key, key_guesses, (0, 0), 0)
        profiles[name, msg] = _brqc(level, msg, *msg_args)

    for level, key_zeros, msg_zeros in ((128, 13, 15), (256, 20, 20), (512, 34, 38)):
        name = f"C-Multi-UR-AG-{level}"
        profiles[name, key] = _cmulti(level, key, key_zeros)
        profiles[name, msg] = _cmulti(level, msg, msg_zeros)
    return profiles


PROFILES = _report_profiles()
