"""Finite branching probabilities and CE-compatible MAGE-Stern accounting."""

from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import combinations
from math import comb, inf, log2, nextafter

import pytest

from codebased_estimator.mage_costs import _log_any, evaluate_parameters, single_target_success_log2


def exact_tree_survival(n, k, w, ell, p, delta, blocks, repetitions):
    """Independent rational implementation of the paper's conditional events."""
    choose = lambda length, weight: comb(length, weight) if 0 <= weight <= length else 0
    z = 2*p-delta
    terminal = (Fraction(choose(k//2, p)*choose(k-k//2, p-delta), choose(k, z))
                * Fraction(choose(n-k-ell, w-z), choose(n-k, w-z)))
    survival = [Fraction(0)]*z + [1-(1-terminal)**repetitions[-1]]
    previous_size = k
    for block, repeats in reversed(list(zip(blocks, repetitions[:-1]))):
        previous_size -= block
        remaining = n-previous_size
        next_survival = []
        for old_weight in range(z+1):
            denominator = choose(remaining, w-old_weight)
            one_child = sum((Fraction(choose(block, new_weight-old_weight)
                                     * choose(remaining-block, w-new_weight), denominator)
                             * survival[new_weight] for new_weight in range(old_weight, z+1)),
                            Fraction(0)) if denominator else Fraction(0)
            next_survival.append(1-(1-one_child)**repeats)
        survival = next_survival
    return survival[0]


def fraction_log2(value):
    return log2(value.numerator)-log2(value.denominator)


def test_one_level_probability_is_stern_with_unequal_half_weights():
    n, k, w, ell, p, delta = 40, 20, 4, 3, 2, 1
    probability = comb(k//2, p)*comb(k-k//2, p-delta)*comb(n-k-ell, w-2*p+delta)/comb(n, w)
    assert single_target_success_log2(n, k, w, ell, p, delta, (k,), (1, 1)) == pytest.approx(log2(probability))


def test_odd_dimension_split_matches_enumerated_errors():
    n, k, w, ell, p, delta = 12, 5, 3, 2, 1, 0
    left, right, zero = set(range(2)), set(range(2, 5)), set(range(5, 7))
    errors = [set(support) for support in combinations(range(n), w)]
    accepted = sum(len(error & left) == p and len(error & right) == p-delta
                   and not error & zero for error in errors)
    assert single_target_success_log2(n, k, w, ell, p, delta, (k,), (1, 1)) == pytest.approx(log2(accepted/len(errors)))


def test_small_tree_probability_matches_exact_fraction_recursion():
    # Two blocks of two positions, with 2 and 3 children, then 2 trials of
    # the balanced split and one-position zero window.  All values are exact.
    n, k, w, ell, z = 8, 4, 2, 1, 2
    terminal = Fraction(comb(2, 1)**2, comb(4, 2))
    alive = [Fraction(0), Fraction(0), 1-(1-terminal)**2]
    for previous_size, block, repeats in ((2, 2, 3), (0, 2, 2)):
        previous = []
        for old in range(z+1):
            probability = sum(Fraction(comb(block, new-old)*comb(n-previous_size-block, w-new),
                                       comb(n-previous_size, w-old))*alive[new]
                              for new in range(old, z+1))
            previous.append(1-(1-probability)**repeats)
        alive = previous
    actual = single_target_success_log2(n, k, w, ell, 1, 0, (2, 2), (2, 3, 2))
    assert actual == pytest.approx(log2(alive[0]))


def test_probability_far_below_float_range_remains_finite():
    result = single_target_success_log2(8000, 4000, 2000, 10, 1, 0, (4000,), (1, 1))
    expected = 2*log2(2000)+log2(comb(3990, 1998))-log2(comb(8000, 2000))
    assert -inf < result < -1074
    assert result == pytest.approx(expected)


def test_huge_repetition_does_not_underflow_intermediate_probability():
    assert _log_any(-2000, 1 << 1900) == pytest.approx(-100)
    assert _log_any(-2000, 1 << 2000) == pytest.approx(log2(1-2.718281828459045**-1))
    assert _log_any(-2000, 1 << 2100) == 0


def test_ce_fixed_point_matches_independent_integer_accounting():
    point = evaluate_parameters(20, 10, 3, ell=2, p=1, delta=1, targets=3)
    # L_left=5, L_right=1, collisions=5/4.  Independent target success is
    # 1-(1-5*C(8,2)/C(20,3))**3.  GE costs 2000 bits, and the leaf costs
    # 20*(5+3*(1+5/4))+3*20*10=835 bits.  Input conversion costs 2300.
    probability = 1-(1-Fraction(7, 57))**3
    assert point.time_log2 == pytest.approx(fraction_log2(2300+2835/probability))
    assert point.memory_log2 == pytest.approx(log2(420))
    assert point.details["log2_success_probability"] == pytest.approx(fraction_log2(probability))
    assert point.details["log2_conversion_bit_cost"] == pytest.approx(log2(2300))
    assert point.details["log2_tree_bit_cost"] == pytest.approx(log2(2835))
    assert point.details["log2_conversion_memory_bits"] == pytest.approx(log2(260))
    assert point.details["target_success_model"] == "independent-target-tree-union-v1"
    assert point.details["target_success_formula"] == "1-(1-single_target_tree_survival)**targets"
    assert point.details["target_independence_assumption"] == "unconditional_independence_of_target_tree_failures"
    assert point.details["tree_execution_model"] == "complete_tree_without_early_stopping"


def test_partial_ge_counts_all_nodes_and_repetitions():
    point = evaluate_parameters(20, 10, 3, ell=2, p=1, delta=1, targets=3,
                                blocks=(6, 4), repetitions=(2, 3, 2))
    assert point.details["log2_tree_gaussian_bit_cost"] == pytest.approx(log2(7200))
    assert point.details["log2_level_gaussian_bit_costs"] == pytest.approx([log2(2400), log2(4800)])
    assert point.details["log2_leaves"] == pytest.approx(log2(12))
    assert point.details["log2_tree_bit_cost"] == pytest.approx(log2(17220))


def test_unbranched_partial_elimination_is_additive():
    one = evaluate_parameters(40, 20, 5, ell=3, p=2, delta=1)
    split = evaluate_parameters(40, 20, 5, ell=3, p=2, delta=1,
                                blocks=(7, 5, 3, 5), repetitions=(1, 1, 1, 1, 1))
    assert split.time_log2 == pytest.approx(one.time_log2)
    assert split.memory_log2 == pytest.approx(one.memory_log2)
    assert split.details["log2_tree_gaussian_bit_cost"] == pytest.approx(one.details["log2_tree_gaussian_bit_cost"])
    assert split.details["log2_single_target_success_probability"] == pytest.approx(
        one.details["log2_single_target_success_probability"])


def test_syndrome_conversion_workspace_participates_in_memory_bound():
    point = evaluate_parameters(30, 4, 2, ell=0, p=1)
    # Online storage is 30*(4+1+2+2)=270 bits, but the input conversion
    # stores 26 rows and one representative, requiring 810 bits.
    assert point.memory_log2 == pytest.approx(log2(810))
    assert evaluate_parameters(30, 4, 2, ell=0, p=1, memory_bound_log2_bits=log2(400)) is None


def test_memory_boundary_and_target_expanded_records():
    point = evaluate_parameters(20, 10, 3, ell=2, p=1, delta=1, targets=3)
    args = dict(ell=2, p=1, delta=1, targets=3)
    assert evaluate_parameters(20, 10, 3, **args, memory_bound_log2_bits=point.memory_log2) is not None
    assert evaluate_parameters(20, 10, 3, **args,
                               memory_bound_log2_bits=nextafter(point.memory_log2, -inf)) is None
    one = evaluate_parameters(20, 10, 3, ell=2, p=1, delta=1)
    # Each additional target stores its n-bit representative and its right list.
    assert 2**point.memory_log2 - 2**one.memory_log2 == pytest.approx(2*20*(1+1))


def test_fixed_parameters_replay_and_json_serialization():
    import json
    from dataclasses import asdict

    point = evaluate_parameters(21, 11, 3, ell=2, p=1, delta=1, targets=3,
                                blocks=(6, 5), repetitions=(2, 3, 2))
    replay = evaluate_parameters(21, 11, 3, targets=3, **point.parameters)
    assert replay == point
    assert evaluate_parameters(21, 11, 3, **point.parameters) == point
    json.dumps(asdict(point), allow_nan=False)


def test_terminal_event_is_independent_of_ce_stern_projection_kernel(monkeypatch):
    import codebased_estimator.classical_doom as doom
    import codebased_estimator.mage_costs as mage

    # CE Stern now uses a separate outer event and integer projections;
    # MAGE must retain the original full terminal event and expected lists.
    monkeypatch.setattr(doom, "_simple_terms", lambda *a, **kw: pytest.fail("CE kernel reused"))
    mage._list_logs.cache_clear()
    point = evaluate_parameters(41, 21, 5, ell=3, p=2, delta=1)
    probability = comb(10, 2)*comb(11, 1)*comb(17, 2)/comb(41, 5)
    assert point.details["log2_single_target_success_probability"] == pytest.approx(log2(probability))
    left, right, collisions, terminal = mage._list_logs(41, 21, 5, 3, 2, 1)
    assert (left, right, collisions, terminal) == pytest.approx(
        (log2(45), log2(11), log2(45*11/8), log2(probability)))


def test_many_targets_do_not_saturate_at_union_bound():
    point = evaluate_parameters(20, 10, 3, ell=2, p=1, delta=1, targets=100)
    probability = 1-(1-Fraction(7, 57))**100
    assert point.details["log2_success_probability"] == pytest.approx(fraction_log2(probability), abs=1e-12)
    assert point.details["log2_success_probability"] < 0
    assert point.details["log2_permutations"] > 0


@pytest.mark.parametrize("blocks,repetitions", [
    ((10,), (1, 1)), ((6, 4), (2, 3, 2)), ((3, 3, 4), (1, 2, 3, 2)),
])
@pytest.mark.parametrize("targets", [1, 2, 3, 8])
def test_independent_target_probability_and_complete_tree_cost_match_exact_oracle(blocks, repetitions, targets):
    n, k, w, ell, p, delta = 20, 10, 3, 2, 1, 1
    single = exact_tree_survival(n, k, w, ell, p, delta, blocks, repetitions)
    probability = 1-(1-single)**targets
    left, right = comb(k//2, p), comb(k-k//2, p-delta)
    matches = Fraction(left*right, 2**ell)
    leaf_cost = n*(left+targets*(right+matches+k))
    nodes, gaussian_cost = 1, 0
    for block, repeats in zip(blocks, repetitions):
        nodes *= repeats
        gaussian_cost += nodes*n*k*block
    leaves = nodes*repetitions[-1]
    tree_cost = gaussian_cost+leaves*leaf_cost
    conversion_cost = (n+targets)*(n-k)**2
    memory = max(n*(k+left+targets*(1+right)), n*(n-k+targets))
    point = evaluate_parameters(n, k, w, ell=ell, p=p, delta=delta,
                                blocks=blocks, repetitions=repetitions, targets=targets)
    assert point is not None
    assert point.time_log2 == pytest.approx(fraction_log2(conversion_cost+tree_cost/probability), abs=1e-11)
    assert point.memory_log2 == pytest.approx(log2(memory))
    assert point.details["log2_single_target_success_probability"] == pytest.approx(fraction_log2(single))
    assert point.details["log2_success_probability"] == pytest.approx(fraction_log2(probability), abs=1e-11)
    assert point.details["log2_tree_bit_cost"] == pytest.approx(fraction_log2(tree_cost))
    if targets == 1:
        assert point.details["log2_success_probability"] == point.details["log2_single_target_success_probability"]


@pytest.mark.parametrize("targets", [5, 6, 7, 12])
def test_probability_remains_exact_around_previous_union_saturation(targets):
    point = evaluate_parameters(6, 3, 1, ell=0, p=1, delta=1, targets=targets)
    exact = 1-Fraction(5, 6)**targets
    assert point.details["log2_success_probability"] == pytest.approx(fraction_log2(exact), abs=1e-12)
    assert point.details["log2_success_probability"] < 0


def test_near_certain_tree_union_retains_small_failure_probability():
    repetitions, targets = (4, 3), 12
    single = exact_tree_survival(6, 3, 1, 0, 1, 1, (3,), repetitions)
    with localcontext() as context:
        context.prec = 100
        success = Decimal(single.numerator)/Decimal(single.denominator)
        probability = 1-(1-success)**targets
        expected = float(probability.ln()/Decimal(2).ln())
    point = evaluate_parameters(6, 3, 1, ell=0, p=1, delta=1,
                                repetitions=repetitions, targets=targets)
    assert point.details["log2_success_probability"] == pytest.approx(expected, abs=1e-15)


def test_tiny_probability_huge_target_batch_matches_high_precision_decimal():
    # S is below double precision's smallest positive number, while u*S is
    # close to one. Compute 1-(1-S)**u at sufficient precision to retain S.
    n, k, w, ell, targets = 8000, 4000, 2000, 10, 1 << 2478
    numerator = comb(k//2, 1)*comb(k-k//2, 1)*comb(n-k-ell, w-2)
    denominator = comb(n, w)
    with localcontext() as context:
        context.prec = 1000
        single = Decimal(numerator)/Decimal(denominator)
        probability = -((Decimal(targets)*(1-single).ln()).exp()-1)
        expected = float(probability.ln()/Decimal(2).ln())
    point = evaluate_parameters(n, k, w, ell=ell, p=1, targets=targets)
    assert point.details["log2_single_target_success_probability"] < -1074
    assert point.details["log2_success_probability"] == pytest.approx(expected, abs=1e-9)
    assert -inf < point.time_log2 < inf
    assert -inf < point.memory_log2 < inf


def test_log_union_boundary_probabilities_and_single_target_are_preserved():
    for targets in (1, 2, 1 << 2000):
        assert _log_any(-inf, targets) == -inf
        assert _log_any(0, targets) == 0
    assert _log_any(-2000, 1) == -2000


@pytest.mark.parametrize("overrides", [
    {"n": 10}, {"k": True}, {"w": 0}, {"w": 11}, {"ell": -1}, {"ell": 11},
    {"p": 0}, {"p": 7}, {"delta": -1}, {"delta": 2}, {"targets": 0},
    {"targets": 1.0}, {"targets": 1, "targets_used": 2}, {"blocks": (4, 4)},
    {"blocks": (0, 10)}, {"blocks": (True, 9)}, {"blocks": "10"},
    {"repetitions": (1,)}, {"repetitions": (1, 0)}, {"repetitions": (1, 2.0)},
    {"memory_bound_log2_bits": -1}, {"memory_bound_log2_bits": inf},
    {"memory_bound_log2_bits": float("nan")}, {"memory_bound_log2_bits": True},
])
def test_invalid_fixed_points_return_none(overrides):
    parameters = dict(n=20, k=10, w=3, ell=2, p=1, delta=1)
    parameters.update(overrides)
    assert evaluate_parameters(**parameters) is None
