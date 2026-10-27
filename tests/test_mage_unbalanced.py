"""Block quotas enter MAGE's conditional branching events, not its exponent."""

from collections import Counter
from dataclasses import asdict, replace
from fractions import Fraction
from itertools import combinations, product
import json
from math import comb, log2, nextafter

import pytest

from codebased_estimator import AttackInstance, Options, Problem, estimate
from codebased_estimator.mage_costs import (
    block_profile_success_log2, evaluate_parameters, single_target_success_log2,
)
from codebased_estimator.mage_search import _Search, optimize
from codebased_estimator.unbalanced import BlockProfile


def exact_profile_tree(n, k, w, ell, p, delta, blocks, repetitions, profile, allocation):
    """Enumerate first-block choices, then use rational conditional branches."""
    choose = lambda a, b: comb(a, b) if 0 <= b <= a else 0
    selections = [list(combinations(range(length), length-tail))
                  for length, tail in zip(profile.lengths, allocation)]
    counts = Counter(sum(sum(position < weight for position in selected)
                         for selected, weight in zip(selection, profile.weights))
                     for selection in product(*selections))
    total = sum(counts.values())
    z = 2*p-delta
    terminal = (Fraction(choose(k//2, p)*choose(k-k//2, p-delta), choose(k, z))
                * Fraction(choose(n-k-ell, w-z), choose(n-k, w-z)))
    alive = [Fraction(0)]*z + [1-(1-terminal)**repetitions[-1]]
    previous = k
    for block, repeats in reversed(list(zip(blocks[1:], repetitions[1:-1]))):
        previous -= block
        remaining = n-previous
        updated = []
        for old in range(z+1):
            denominator = choose(remaining, w-old)
            child = sum((Fraction(choose(block, new-old)*choose(remaining-block, w-new), denominator)
                         * alive[new] for new in range(old, z+1)), Fraction(0)) if denominator else Fraction(0)
            updated.append(1-(1-child)**repeats)
        alive = updated
    child = sum((Fraction(counts[j], total)*alive[j] for j in range(z+1)), Fraction(0))
    return 1-(1-child)**repetitions[0]


@pytest.mark.parametrize("blocks,repetitions", [
    ((6,), (1, 1)), ((3, 3), (2, 3, 4)), ((2, 2, 2), (1, 4, 3, 2)),
])
def test_profile_tree_matches_enumerated_root_and_exact_descendant_events(blocks, repetitions):
    profile = BlockProfile((6, 6), (3, 0))
    allocation = (6-blocks[0]//2, 6-(blocks[0]-blocks[0]//2))
    exact = exact_profile_tree(12, 6, 3, 1, 1, 0, blocks, repetitions, profile, allocation)
    actual = block_profile_success_log2(12, 6, 3, 1, 1, 0, blocks, repetitions, profile, allocation)
    assert actual == pytest.approx(log2(exact.numerator)-log2(exact.denominator), abs=1e-12)


def test_branching_gain_is_not_a_scalar_one_leaf_gain():
    profile = BlockProfile((6, 6), (3, 0))
    arguments = (12, 6, 3, 1, 1, 0, (3, 3))
    repeats, allocation = (2, 3, 4), (5, 4)
    tree = block_profile_success_log2(*arguments, repeats, profile, allocation)
    uniform_tree = single_target_success_log2(*arguments, repeats)
    leaf = block_profile_success_log2(*arguments, (1, 1, 1), profile, allocation)
    uniform_leaf = single_target_success_log2(*arguments, (1, 1, 1))
    assert abs(tree-(uniform_tree+leaf-uniform_leaf)) > 0.1


def test_allocation_search_matches_all_small_integer_quotas_and_replays():
    profile = BlockProfile((6, 6), (3, 0))
    point = evaluate_parameters(12, 6, 3, ell=1, p=1, blocks=(3, 3),
                                repetitions=(2, 3, 4), targets=3, block_profile=profile)
    expected = max(exact_profile_tree(12, 6, 3, 1, 1, 0, (3, 3), (2, 3, 4),
                                     profile, (first, 9-first)) for first in range(3, 7))
    assert point.details["log2_single_target_success_probability"] == pytest.approx(
        log2(expected.numerator)-log2(expected.denominator), abs=1e-12)
    expected_union = 1-(1-expected)**3
    assert point.details["log2_success_probability"] == pytest.approx(
        log2(expected_union.numerator)-log2(expected_union.denominator), abs=1e-12)
    assert evaluate_parameters(12, 6, 3, **point.parameters) == point
    json.dumps(asdict(point), allow_nan=False)


def test_impossible_requested_quota_retains_uniform_strategy_and_json_is_finite():
    profile = BlockProfile((6, 6), (3, 0))
    point = evaluate_parameters(12, 6, 3, ell=1, p=1, block_profile=profile,
                                first_tail_allocation=(0, 6))
    uniform = evaluate_parameters(12, 6, 3, ell=1, p=1)
    assert point.time_log2 == uniform.time_log2
    assert point.details["unbalanced"]["selected_strategy"] == "uniform"
    json.dumps(asdict(point), allow_nan=False)


def test_profile_is_optimized_before_target_batch_selection():
    profile = BlockProfile((12, 12), (4, 0))
    search = _Search(24, 12, 4, 40, None, block_profile=profile)
    point = search.at(2, 1, 0, (7, 5), (1, 3, 2))
    exhaustive = [evaluate_parameters(24, 12, 4, ell=2, p=1, blocks=(7, 5),
                                      repetitions=(1, 3, 2), targets=targets,
                                      block_profile=profile) for targets in range(1, 41)]
    best = min(exhaustive, key=lambda result: (result.time_log2, result.parameters["targets_used"]))
    assert point.time_log2 == pytest.approx(best.time_log2)
    assert point.parameters["targets_used"] == best.parameters["targets_used"]


def test_profile_search_replay_and_no_profile_contract():
    profile = BlockProfile((12, 12), (4, 0))
    result = optimize(24, 12, 4, block_profile=profile)
    replay = evaluate_parameters(24, 12, 4, **result.parameters)
    assert replay.time_log2 == result.time_log2
    assert replay.details == result.details
    assert result.search["unbalanced"]["scope"].startswith("first pivot")
    assert "unbalanced" not in optimize(24, 12, 4).details


def test_profile_codewords_use_probability_union_without_expanding_syndrome_costs():
    profile = BlockProfile((12, 12), (4, 0))
    one = evaluate_parameters(24, 12, 4, ell=2, p=1, block_profile=profile)
    many = evaluate_parameters(24, 12, 4, ell=2, p=1, block_profile=profile, codewords=20)
    survival = 2**one.details["log2_single_solution_probability"]
    assert many.details["log2_success_probability"] == pytest.approx(log2(1-(1-survival)**20))
    assert many.details["log2_tree_bit_cost"] == one.details["log2_tree_bit_cost"]
    assert many.memory_log2 == one.memory_log2
    assert many.parameters["targets_used"] == 1
    assert many.details["codeword_sampling_model"] == "block_profile_first_transition_proxy"


def test_backend_keeps_full_orbit_and_limits_profile_targets(monkeypatch):
    from types import SimpleNamespace
    from codebased_estimator import AttackInstance, Options, Problem, estimate
    import codebased_estimator.mage_search as search

    profile = BlockProfile((6, 6), (3, 0), ((0, 1), (1, 0)))
    calls = []

    def fake_optimize(n, k, w, **options):
        calls.append(options)
        return SimpleNamespace(time_log2=9.0 if "block_profile" in options else 10.0,
                               memory_log2=8.0, parameters={"blocks": [k], "targets_used": options["targets"]},
                               details={}, search={})

    monkeypatch.setattr(search, "optimize", fake_optimize)
    instance = AttackInstance("profile", "key_recovery", Problem("qcsd", {"n": 12, "k": 6, "w": 3}, 0),
                              targets=20, tags=("doom:qcsd",), block_profile=profile)
    result, = estimate(instance, options=Options(classical_algorithms=("MAGE-Stern",), quantum_algorithms=())).results
    assert [call["targets"] for call in calls] == [20, 10]
    assert result.metadata["unbalanced"]["full_orbit_baseline_retained"] is True
    assert result.metadata["unbalanced"]["selected_strategy"] == "block_profile"
    assert result.metadata["doom"]["active_targets"] == 10


@pytest.mark.parametrize("codewords,targets,profile", [
    (False, 1, BlockProfile((10, 10), (1, 2), ((0, 1), (1, 0)))),
    (False, 6, BlockProfile((10, 10), (1, 2), ((0, 1), (1, 0)))),
    (True, 6, BlockProfile((10, 10), (1, 2), ((0, 1), (1, 0)))),
    (False, 6, BlockProfile((20,), (3,))),
])
def test_public_profile_tree_replays_selected_targets_and_memory(codewords, targets, profile):
    attack = AttackInstance("profile replay", "key_recovery",
        Problem("cfp" if codewords else "sd", {"n": 20, "k": 10, "w": 3},
                None if codewords else 0),
        targets=targets, tags=("doom:qccf" if codewords else "doom:qcsd",),
        block_profile=profile)
    options = Options(classical_algorithms=("MAGE-Stern",), quantum_algorithms=())
    report = estimate(attack, options=options)
    result, = report.results
    assert result.status == "computed"
    json.dumps(report.to_dict(), allow_nan=False)
    parameters = dict(result.parameters)
    parameters.pop("strategy")
    replay = evaluate_parameters(20, 10, 3, **parameters)
    assert replay.time_log2 == result.time_log2
    assert replay.memory_log2 == result.memory_log2
    assert replay.details == result.metadata["cost_breakdown"]
    doom = result.metadata["doom"]
    active = doom["active_codewords" if codewords else "active_targets"]
    if codewords:
        assert parameters["codewords"] == active
        assert parameters["targets_used"] == doom["effective_syndrome_targets"] == 1
    else:
        assert parameters["targets_used"] == active
    assert result.metadata["effective_log2_solutions"] == (log2(active) if codewords else 0)
    profiled = result.metadata["unbalanced"]["selected_strategy"] == "block_profile"
    assert active <= (profile.preserving_targets(targets) if profiled else targets)
    assert ("block_profile" in parameters) == profiled
    probability = 2**replay.details["log2_single_solution_probability"]
    assert replay.details["log2_success_probability"] == pytest.approx(
        log2(1-(1-probability)**active), abs=1e-12)
    bound = nextafter(result.memory_log2, 0)
    assert evaluate_parameters(20, 10, 3, memory_bound_log2_bits=bound, **parameters) is None
    limited, = estimate(attack, options=replace(options, memory_bound_log2_bits=bound)).results
    assert limited.status != "computed" or limited.memory_log2 <= bound


def test_profile_default_solution_count_is_preserved_before_mage_dispatch():
    attack = AttackInstance("profile solutions", "key_recovery",
        Problem("sd", {"n": 20, "k": 10, "w": 8}), targets=6,
        tags=("doom:qcsd",), block_profile=BlockProfile((10, 10), (0, 8)))
    # Ambient SD has several expected solutions; the accepted profile has one.
    assert log2(comb(20, 8))-10 > 0 > log2(comb(10, 8))-10
    options = Options(classical_algorithms=("MAGE-Stern",), quantum_algorithms=())
    implicit, = estimate(attack, options=options).results
    explicit, = estimate(replace(attack, problem=replace(attack.problem, log2_solutions=0)),
                         options=options).results
    assert implicit.status == explicit.status == "computed"
    assert implicit.time_log2 == explicit.time_log2
    assert implicit.parameters == explicit.parameters
    assert implicit.metadata["effective_log2_solutions"] == 0

