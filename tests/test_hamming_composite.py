"""Reference tuples and algebra for the full composite message core.

The reference tuples are independently recorded and checked against the
submitted reference parameters.
Mito-1-E-256 uses the corrected ring length 32261, rather than code length 32256.
"""

import pytest

from codebased_estimator.hamming import HammingScheme


# (scheme, parameter_set, N, K, total weight, cyclic target count).
COMPOSITE_EXPECTED = [
    ("HARE", "HARE-128", 62697, 20899, 303, 20899),
    ("HARE", "HARE-256", 157137, 52379, 486, 52379),
    ("HARE", "HARE-384", 314607, 104869, 747, 104869),
    ("HARE", "HARE-512", 521943, 173981, 967, 173981),
    ("NSS-HQC", "NSS-HQC-128", 88329, 29443, 249, 29443),
    ("NSS-HQC", "NSS-HQC-256", 163479, 54493, 399, 54493),
    ("NSS-HQC", "NSS-HQC-384", 367737, 122579, 597, 122579),
    ("NSS-HQC", "NSS-HQC-512", 653703, 217901, 798, 217901),
    ("TriQ-KEM", "TriQ-KEM-128", 48903, 16301, 240, 16301),
    ("TriQ-KEM", "TriQ-KEM-256", 151089, 50363, 498, 50363),
    ("TriQ-KEM", "TriQ-KEM-384", 292953, 97651, 742, 97651),
    ("TriQ-KEM", "TriQ-KEM-512", 472881, 157627, 995, 157627),
    ("Mito", "Mito-1-128", 76865, 30746, 261, 15373),
    ("Mito", "Mito-1-256", 169135, 67654, 407, 33827),
    ("Mito", "Mito-1-512", 531305, 212522, 794, 106261),
    ("Mito", "Mito-1-E-128", 73105, 29242, 262, 14621),
    ("Mito", "Mito-1-E-256", 161305, 64522, 406, 32261),
    ("Mito", "Mito-1-E-512", 512185, 204874, 793, 102437),
    ("Mito", "Mito-2-E-128", 92277, 41012, 229, 10253),
    ("Mito", "Mito-2-E-256", 193707, 86092, 356, 21523),
    ("Mito", "Mito-2-E-512", 587637, 261172, 683, 65293),
    ("QUBE", "QUBE-128", 52436, 26218, 168, 13109),
    ("QUBE", "QUBE-192", 101428, 50714, 246, 25357),
    ("QUBE", "QUBE-256", 166604, 83302, 328, 41651),
    ("QUBE", "QUBE-384", 331028, 165514, 492, 82757),
    ("QUBE", "QUBE-512", 543404, 271702, 653, 135851),
]


@pytest.mark.parametrize("doom", ["auto", "none"])
@pytest.mark.parametrize("scheme,parameter_set,n,k,w,targets", COMPOSITE_EXPECTED)
def test_composite_reference_tuples(scheme, parameter_set, n, k, w, targets, doom):
    routes = HammingScheme(scheme).instances(parameter_set, "msg_recovery", doom=doom)
    assert [attack.route_id for attack in routes] == ["u_only", "composite"]
    assert len({attack.name for attack in routes}) == 2
    attack = routes[1]
    assert attack.name == f"{parameter_set}/msg_recovery/composite"
    assert attack.problem.kind == "sd"
    assert attack.problem.parameters == {"n": n, "k": k, "w": w, "q": 2}
    assert attack.problem.log2_solutions == 0
    assert attack.targets == (targets if doom == "auto" else 1)
    assert attack.tags == (("doom:qcsd",) if doom == "auto" else ())
    assert any("unknown-message costs" in note for note in attack.assumptions)
    assert any("uncompressed core" in note for note in attack.assumptions)
    assert any(ref.startswith(scheme) for ref in attack.references)
    assert all("/" not in ref and "\\" not in ref for ref in attack.references)


def _cyclic_product(a, b):
    r = len(a)
    return [sum(a[j] * b[(i - j) % r] for j in range(r)) % 2 for i in range(r)]


def _xor(a, b):
    return [x ^ y for x, y in zip(a, b)]


def _shift(a):
    return a[-1:] + a[:-1]


def _binary_rank(rows):
    pivots = {}
    for row in rows:
        value = sum(bit << i for i, bit in enumerate(row))
        while value:
            pivot = value.bit_length() - 1
            if pivot not in pivots:
                pivots[pivot] = value
                break
            value ^= pivots[pivot]
    return len(pivots)


@pytest.mark.parametrize("r", [3, 5, 7])
def test_hqc_core_equations_rank_and_cyclic_targets(r):
    # Column order is (r1, e, r2). Identity blocks make the joint parity-check
    # rank 2r; only r2 remains free once the two syndromes are fixed.
    h = [int(i in (0, 1)) for i in range(r)]
    s = [int(i in (0, 2)) for i in range(r)]
    columns = []
    for coordinate in range(3 * r):
        value = [int(i == coordinate) for i in range(3 * r)]
        r1, e, r2 = value[:r], value[r:2 * r], value[2 * r:]
        u = _xor(r1, _cyclic_product(h, r2))
        z = _xor(e, _cyclic_product(s, r2))
        columns.append(u + z)

        # Simultaneous shifts preserve both equations under the same public h,s.
        shifted_u = _xor(_shift(r1), _cyclic_product(h, _shift(r2)))
        shifted_z = _xor(_shift(e), _cyclic_product(s, _shift(r2)))
        assert shifted_u + shifted_z == _shift(u) + _shift(z)
    rows = [list(row) for row in zip(*columns)]
    rank = _binary_rank(rows)
    assert rank == 2 * r
    assert len(columns) - rank == r

