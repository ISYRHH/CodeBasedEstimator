"""Independent finite-support enumeration, input contracts and route mapping."""

from dataclasses import asdict
from fractions import Fraction
from itertools import product
import json
from math import comb, log2

import pytest

from codebased_estimator import AttackInstance, BlockProfile, Problem
from codebased_estimator.hamming import hamming_instances
from codebased_estimator.unbalanced import log_distribution, optimize_outer


def exact_distribution(lengths, weights, allocation):
    """Independent integer count of coordinate subsets for each outside weight."""
    counts, denominator = [1], 1
    for n, w, r in zip(lengths, weights, allocation):
        denominator *= comb(n, r)
        block = [comb(w, w-j)*comb(n-w, r-w+j)
                 if 0 <= r-w+j <= n-w else 0 for j in range(w+1)]
        merged = [0]*(len(counts)+w)
        for i, left in enumerate(counts):
            for j, right in enumerate(block):
                merged[i+j] += left*right
        counts = merged
    return tuple(Fraction(count, denominator) for count in counts)


def log_fraction(value):
    return log2(value.numerator)-log2(value.denominator) if value else float("-inf")


@pytest.mark.parametrize("lengths,weights", [
    ((3, 4), (1, 2)), ((2, 3, 2), (0, 3, 1)),
    ((2, 2, 2, 2), (2, 0, 1, 2)), ((3, 2), (0, 0)),
])
def test_distribution_and_small_optimizer_match_exact_subset_counts(lengths, weights):
    profile = BlockProfile(lengths, weights)
    n, w = sum(lengths), sum(weights)
    maxima = [[Fraction(0)]*(w+1) for _ in range(n+1)]
    for allocation in product(*(range(size+1) for size in lengths)):
        expected = exact_distribution(lengths, weights, allocation)
        actual = log_distribution(profile, allocation, w+2)
        assert sum(expected) == 1
        for p, value in enumerate(expected):
            assert actual[p] == pytest.approx(log_fraction(value), abs=2e-12)
            maxima[sum(allocation)][p] = max(maxima[sum(allocation)][p], value)
        assert actual[w+1:] == (float("-inf"), float("-inf"))
    for tail in range(n+1):
        for p in range(w+1):
            result = optimize_outer(profile, tail, p)
            assert result.log2_probability == pytest.approx(log_fraction(maxima[tail][p]), abs=2e-12)
            assert result.gain >= 0
            if result.allocation is not None:
                assert sum(result.allocation) == tail
                replay = exact_distribution(lengths, weights, result.allocation)[p]
                assert result.log2_probability == pytest.approx(log_fraction(replay), abs=2e-12)


@pytest.mark.parametrize("lengths,weights,tail", [
    ((17, 9), (6, 1), 13), ((3, 12, 16), (3, 0, 5), 10),
    ((7, 8, 9), (7, 0, 9), 18),
])
def test_prange_and_complement_are_exact_above_small_search_threshold(lengths, weights, tail):
    profile = BlockProfile(lengths, weights)
    for size, p in ((tail, 0), (sum(lengths)-tail, sum(weights))):
        expected = max(exact_distribution(lengths, weights, allocation)[p]
                       for allocation in product(*(range(n+1) for n in lengths))
                       if sum(allocation) == size)
        actual = optimize_outer(profile, size, p)
        assert actual.log2_probability == pytest.approx(log_fraction(expected), abs=2e-12)


def test_profile_cache_isolation_block_relabeling_and_target_classes():
    profiles = [BlockProfile((6, 6), weights) for weights in ((4, 0), (2, 2), (0, 4))]
    expected = [max(exact_distribution(p.lengths, p.weights, (a, 4-a))[4]
                    for a in range(5)) for p in profiles]
    assert expected[0] == expected[2] != expected[1]
    for index in (0, 1, 2, 1, 0, 2):
        actual = optimize_outer(profiles[index], 4, 4)
        assert actual.log2_probability == pytest.approx(log_fraction(expected[index]))
    orbit = BlockProfile((6, 6), (4, 0), ((0, 1), (1, 0)))
    assert optimize_outer(orbit, 4, 4) == optimize_outer(profiles[0], 4, 4)
    assert orbit.preserving_targets(12) == 6


def test_prange_large_reference_and_balanced_nonzero_gap():
    # Independently recorded QUBE-128 composite profile and finite Prange result.
    instance = next(i for i in hamming_instances(parameter_sets=["QUBE-128"],
                                                goal="msg_recovery") if i.route_id == "composite")
    p = instance.problem.parameters
    result = optimize_outer(instance.block_profile, p["n"]-p["k"], 0)
    assert result.gain == pytest.approx(33.494730767186724, abs=1e-8)
    assert result.method == "exact_discrete_concavity"
    balanced = BlockProfile((10000, 10000), (50, 50))
    probability = optimize_outer(balanced, 10000, 0)
    gap = log2(comb(20000, 100))-2*log2(comb(10000, 50))
    assert gap > 3 and 0 <= probability.gain < 0.01


def test_all_errors_in_information_region_uses_complementary_allocation():
    result = optimize_outer(BlockProfile((100, 100), (20, 0)), 100, 20)
    assert result.log2_probability == 0
    assert result.allocation == (0, 100)


def test_extremely_rare_distribution_coefficients_do_not_underflow():
    profile = BlockProfile((10000, 10000), (1000, 1000))
    distribution = log_distribution(profile, (1000, 1000), 4)
    expected = -2*log2(comb(10000, 1000))
    assert distribution[0] == pytest.approx(expected, abs=1e-10)
    assert distribution[0] < -9000
    assert all(x != float("-inf") for x in distribution)


@pytest.mark.parametrize("data", [
    {"lengths": [], "weights": []}, {"lengths": [3], "weights": [4]},
    {"lengths": [True], "weights": [1]}, {"lengths": [3, 2], "weights": [1]},
    {"lengths": [3, 2], "weights": [1, 1], "target_permutations": [[1, 0]]},
])
def test_invalid_profiles_rejected(data):
    with pytest.raises(ValueError):
        BlockProfile(**data)


def test_profile_roundtrip_and_problem_validation():
    instance = AttackInstance("example", "key_recovery", Problem("sd", {"n": 12, "k": 6, "w": 3}),
                              block_profile=BlockProfile((6, 6), (1, 2)))
    assert AttackInstance.from_dict(asdict(instance)) == instance
    with pytest.raises(ValueError, match="sum"):
        AttackInstance("bad", "key_recovery", instance.problem,
                       block_profile={"lengths": [6, 6], "weights": [1, 1]})
    with pytest.raises(ValueError, match="binary"):
        AttackInstance("bad", "key_recovery", Problem("sd", {"n": 12, "k": 6, "w": 3, "q": 3}),
                       block_profile=instance.block_profile)


def test_hamming_profiles_and_mito_target_classes():
    instances = hamming_instances()
    for instance in instances:
        profile = instance.block_profile
        if profile:
            profile.validate(instance.problem.parameters["n"], instance.problem.parameters["w"])
        if instance.route_id == "parity":
            assert profile is None
    assert all(i.block_profile is None for i in hamming_instances(unbalanced="none"))
    mito = next(i for i in instances if i.parameter_set == "Mito-2-E-128" and i.route_id == "baseline")
    assert mito.block_profile.preserving_targets(mito.targets) == mito.targets//4
    assert mito.block_profile.preserving_targets(1) == 1
    assert mito.block_profile.preserving_targets(7) == 1
    assert len(mito.block_profile.target_permutations) == 4
    with pytest.raises(ValueError, match="unbalanced"):
        hamming_instances(unbalanced="invalid")


def test_cli_profile_enabled_by_default_and_explicit_baseline(tmp_path, capsys):
    from codebased_estimator.__main__ import main

    instance = AttackInstance("cli", "key_recovery",
        Problem("sd", {"n": 24, "k": 12, "w": 4}, log2_solutions=0),
        block_profile=BlockProfile((12, 12), (4, 0)))
    path = tmp_path/"profile.json"
    path.write_text(json.dumps(asdict(instance)))
    arguments = ["estimate", str(path), "--classical-algorithms", "Prange", "--quantum-algorithms", "--json"]
    assert main(arguments) == 0
    corrected = json.loads(capsys.readouterr().out)[0]
    assert main(arguments+["--unbalanced", "none"]) == 0
    baseline = json.loads(capsys.readouterr().out)[0]
    assert corrected["instance"]["block_profile"]["weights"] == [4, 0]
    assert baseline["instance"]["block_profile"] is None
    delta = baseline["results"][0]["time_log2"]-corrected["results"][0]["time_log2"]
    assert delta == pytest.approx(log2(comb(24, 4)/comb(12, 4)), abs=1e-10)
