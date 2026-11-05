"""HEP-QC source snapshot and the limits of its three decoding subproblems."""

from dataclasses import asdict
import json

import pytest

from codebased_estimator.__main__ import main
from codebased_estimator.hamming import hamming_catalogue, hamming_instances


# Specification Table 4.1, independently cross-checked with both implementation
# families: set, n, n1, n2, n1*n2, message bits, omega, omega_r=omega_e.
PARAMETERS = [
    (1, 17669, 46, 384, 17664, 128, 66, 75),
    (3, 35851, 56, 640, 35840, 192, 100, 114),
    (5, 57637, 90, 640, 57600, 256, 131, 149),
    (7, 197123, 220, 896, 197120, 512, 261, 297),
]


@pytest.mark.parametrize("level,r,n1,n2,length,message,w,wr", PARAMETERS)
def test_hep_source_parameters_keep_ring_code_and_message_lengths_distinct(
        level, r, n1, n2, length, message, w, wr):
    entry = next(row for row in hamming_catalogue()
                 if row["parameter_set"] == f"HEP-QC-{level}")
    assert entry["scheme"] == "HEP-QC"
    assert entry["parameters"] == {
        "r": r, "w": w, "wr": wr, "we": wr, "n1": n1, "n2": n2,
        "code_length": length, "message_bits": message,
    }
    assert length == n1 * n2 and message < length < r
    assert "Table 4.1" in " ".join(entry["references"])


@pytest.mark.parametrize("doom", ["auto", "none"])
@pytest.mark.parametrize("unbalanced", ["auto", "none"])
def test_hep_subproblem_scope_and_block_weights_survive_configuration(doom, unbalanced):
    key, u_only, composite = hamming_instances(
        parameter_sets=["HEP-QC-1"], doom=doom, unbalanced=unbalanced)
    assert [i.route_id for i in (key, u_only, composite)] == [None, "u_only", "composite"]
    assert "Sparse-key subproblem" in key.route
    assert "Conditional full-length known-mask" in composite.route
    key_notes, u_notes, c_notes = [" ".join(i.assumptions) for i in (key, u_only, composite)]
    assert "scrambler T and permutation P are not recovered" in key_notes
    assert "not a complete HEP-QC" in key_notes
    assert "public masked generator G'_L" in u_notes and "cost is not included" in u_notes
    assert "missing r-L tail" in c_notes and "message mask m*G'" in c_notes
    assert "not a DOOM orbit of the actual truncated unknown-message ciphertext" in c_notes
    for instance, weights in zip((key, u_only, composite), ((66, 66), (75, 75), (75, 75, 75))):
        assert instance.targets == (17669 if doom == "auto" else 1)
        assert instance.tags == (("doom:qcsd",) if doom == "auto" else ())
        assert instance.problem.log2_solutions == 0
        if unbalanced == "auto":
            assert instance.block_profile.lengths == (17669,) * len(weights)
            assert instance.block_profile.weights == weights
        else:
            assert instance.block_profile is None


def test_hep_cli_routes_include_every_parameter_set_and_scope(capsys):
    assert main(["hamming", "--schemes", "HEP-QC", "--list-routes", "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    expected = json.loads(json.dumps([asdict(i) for i in hamming_instances(schemes=["HEP-QC"])]))
    assert records == [{key: row[key] for key in records[0]} for row in expected]
    assert len(records) == 12
    assert {row["parameter_set"] for row in records} == {f"HEP-QC-{i}" for i in (1, 3, 5, 7)}


def _rotate(value, r):
    return ((value << 1) | (value >> (r - 1))) & ((1 << r) - 1)


def _multiply(a, b, r):
    result = 0
    for _ in range(r):
        if b & 1:
            result ^= a
        b >>= 1
        a = _rotate(a, r)
    return result


def test_recovered_randomness_leaves_a_public_code_decoding_problem():
    # A small masked public generator, with a truncated transmitted v. Knowing
    # r2 removes the s*r2 term but does not remove e or decode m by itself.
    r, length = 7, 6
    mask = (1 << length) - 1
    generator = (0b000111, 0b111000)
    message, r1, r2, error, h, s = 1, 0b0010010, 0b0000101, 0b1000010, 0b0010011, 0b1010001
    encoded = generator[message - 1]
    u = r1 ^ _multiply(h, r2, r)
    v = (encoded ^ _multiply(s, r2, r) ^ error) & mask
    assert u ^ _multiply(h, r2, r) == r1
    residual = v ^ (_multiply(s, r2, r) & mask)
    assert residual == encoded ^ (error & mask)
    assert residual != encoded
    assert bin(error & mask).count("1") < bin(error).count("1")


def test_truncation_and_masked_generator_do_not_supply_a_qc_syndrome_orbit():
    r, length = 7, 6
    mask = (1 << length) - 1
    # Two full syndromes have the same transmitted prefix, but rotating them
    # produces different prefixes. Thus a full cyclic target cannot be
    # computed solely from a truncated ciphertext.
    left, right = 0, 1 << length
    assert left & mask == right & mask
    assert _rotate(left, r) & mask != _rotate(right, r) & mask
    # A generic public generator row space need not be shift invariant either.
    generator = (0b000111, 0b111000)
    row_space = {0, *generator, generator[0] ^ generator[1]}
    assert _rotate(generator[0], length) not in row_space
