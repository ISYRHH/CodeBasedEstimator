"""Search contracts checked against fixed costs and exhaustive batch oracles."""

from decimal import Decimal, localcontext
from fractions import Fraction
from math import comb, log2

import pytest

from codebased_estimator.mage_costs import evaluate_parameters
from codebased_estimator.mage_search import (
    BRANCH_LIMIT, POINT_BUDGET, SEARCH_VERSION, _PAPER_BLOCKS, _Search, _optimize, _partition, optimize,
)
from codebased_estimator.mage_targets import optimal_target_batch


def independent_batch_oracle(n, k, w, ell, p, delta, blocks, repetitions, maximum, bound):
    """Scan Decimal objectives, independently of the batching implementation.

    Single-tree probability is covered by the exact rational tests in
    test_mage_costs. Only that scalar is taken from the fixed-point evaluator;
    all u-dependent probability, accounting and memory are calculated here.
    """
    single = evaluate_parameters(n, k, w, ell=ell, p=p, delta=delta,
                                 blocks=blocks, repetitions=repetitions)
    assert single is not None
    left, right = comb(k//2, p), comb(k-k//2, p-delta)
    nodes, gaussian = 1, 0
    for block, repeats in zip(blocks, repetitions):
        nodes *= repeats
        gaussian += n*k*nodes*block
    leaves = nodes*repetitions[-1]
    shared = gaussian+leaves*n*left
    per_target = leaves*n*(right+k+Fraction(left*right, 2**ell))
    with localcontext() as context:
        context.prec = 100
        survival = Decimal(2)**Decimal(single.details["log2_single_target_success_probability"])
        variable_cost = Decimal(per_target.numerator)/Decimal(per_target.denominator)
        candidates = []
        for targets in range(1, maximum+1):
            memory = max(n*(k+left+targets*(right+1)), n*(n-k+targets))
            if bound is not None and log2(memory) > bound:
                continue
            probability = 1-(1-survival)**targets
            cost = (n+targets)*(n-k)**2+(shared+targets*variable_cost)/probability
            candidates.append((cost, targets))
        best_cost, best_targets = min(candidates)
        return best_targets, float(best_cost.ln()/Decimal(2).ln())


@pytest.mark.parametrize("n,k,w,targets", [(24, 12, 4, 1), (101, 51, 12, 51),
                                          (35338, 17669, 132, 17669)])
def test_search_is_replayable_deterministic_and_retains_its_one_level_baseline(n, k, w, targets):
    result = optimize(n, k, w, targets=targets)
    assert result is not None
    _optimize.cache_clear()
    repeated = optimize(n, k, w, targets=targets)
    assert repeated == result and repeated is not result
    replay = evaluate_parameters(n, k, w, **result.parameters)
    assert replay is not None
    assert (replay.time_log2, replay.memory_log2, replay.parameters, replay.details) == (
        result.time_log2, result.memory_log2, result.parameters, result.details)
    baseline = evaluate_parameters(n, k, w, **result.search["one_level_baseline_parameters"])
    assert baseline is not None
    assert baseline.time_log2 == result.search["one_level_baseline_time_log2"]
    assert result.time_log2 <= baseline.time_log2
    assert result.parameters["repetitions"][0] == 1
    assert all(1 <= value <= BRANCH_LIMIT for value in result.parameters["repetitions"])
    assert sum(result.parameters["blocks"]) == k
    assert 1 <= result.parameters["targets_used"] <= targets
    assert result.search["global_optimum"] is False
    assert result.search["version"] == SEARCH_VERSION == "ce-mage-deterministic-multistart-v2"
    assert result.search["candidate_points"] <= result.search["point_budget"] == POINT_BUDGET
    assert result.search["fixed_point_replayed"] is True
    # The returned dictionaries must not allow a caller to poison cached data.
    repeated.parameters["blocks"][0] = -1
    assert optimize(n, k, w, targets=targets) == result


@pytest.mark.parametrize("blocks,repetitions", [((12,), (1, 1)),
                                                ((7, 3, 2), (1, 3, 2, 1)),
                                                ((12,), (1, 12))])
@pytest.mark.parametrize("bound", [None, log2(24*(12+6+8*7))])
@pytest.mark.parametrize("maximum", [1, 2, 7, 120])
def test_fixed_tree_batch_optimization_matches_all_integer_batches(blocks, repetitions, bound, maximum):
    search = _Search(24, 12, 4, maximum, bound)
    result = search.at(2, 1, 0, blocks, repetitions)
    expected_targets, expected_time = independent_batch_oracle(
        24, 12, 4, 2, 1, 0, blocks, repetitions, maximum, bound)
    assert result is not None
    assert result.parameters["targets_used"] == expected_targets
    assert result.time_log2 == pytest.approx(expected_time, abs=1e-11)
    if bound is not None:
        assert result.memory_log2 <= bound
        assert search.batch_cap(1, 0) == min(maximum, 8)


def test_nonrare_batch_counterexample_uses_three_targets_instead_of_union_candidates():
    # S=1/6, A=60, B=30, C(u)=54+9u.  The old min(1,u*S)
    # optimizer only examined 5 and 6, missing the independent-union optimum.
    exact = [(Fraction(54+9*u)+(60+30*u)/(1-Fraction(5, 6)**u), u)
             for u in range(1, 65)]
    expected_cost, expected_targets = min(exact)
    assert expected_targets == 3
    assert expected_cost == Fraction(39771, 91)
    search = _Search(6, 3, 1, 64, None)
    point = search.at(0, 1, 1, (3,), (1, 1))
    assert point.parameters["targets_used"] == expected_targets
    assert point.time_log2 == pytest.approx(log2(expected_cost), abs=1e-12)


@pytest.mark.parametrize("n,k,w,ell,p,delta,blocks,repetitions", [
    (12, 5, 3, 1, 1, 0, (2, 3), (1, 3, 2)),
    (30, 8, 4, 4, 2, 1, (3, 5), (1, 4, 3)),
    (40, 20, 8, 5, 3, 2, (10, 6, 4), (1, 2, 3, 4)),
])
def test_batch_scan_covers_unequal_halves_and_target_list_sizes(n, k, w, ell, p, delta, blocks, repetitions):
    maximum = 96
    expected_targets, expected_time = independent_batch_oracle(
        n, k, w, ell, p, delta, blocks, repetitions, maximum, None)
    search = _Search(n, k, w, maximum, None)
    point = search.at(ell, p, delta, blocks, repetitions)
    assert point is not None
    assert point.parameters["targets_used"] == expected_targets
    assert point.time_log2 == pytest.approx(expected_time, abs=1e-11)


@pytest.mark.parametrize("single", [Fraction(1, 128), Fraction(1, 6), Fraction(1, 2), Fraction(15, 16)])
@pytest.mark.parametrize("shared,target,conversion", [(1, Fraction(1, 5), 1),
                                                       (7, Fraction(5), 3),
                                                       (100, Fraction(90), 30)])
def test_integer_batch_helper_matches_fraction_full_scan(single, shared, target, conversion):
    maximum = 64
    values = [(conversion*u+(shared+target*u)/(1-(1-single)**u), u)
              for u in range(1, maximum+1)]
    expected = min(values)[1]
    actual = optimal_target_batch(log2(single), shared, target, conversion, maximum)
    assert actual == expected


def test_integer_batch_helper_keeps_smallest_exact_tie_and_endpoint_minima():
    # At S=1/2, A=5, B=D=2 both u=1 and u=2 cost 16.
    assert optimal_target_batch(-1.0, 5, Fraction(2), 2, 64) == 1
    assert optimal_target_batch(0.0, 10**10, Fraction(1), 1, 64) == 1
    assert optimal_target_batch(-2000.0, 7, Fraction(5), 3, 64) == 64
    assert optimal_target_batch(-1.0, 5, Fraction(2), 2, 1) == 1


def test_extremely_large_integer_batch_is_locally_minimal_at_independent_decimal_precision():
    shared, target, conversion, maximum = 7, Fraction(5), 3, 1 << 1260
    actual = optimal_target_batch(-2500.0, shared, target, conversion, maximum)
    assert 1 < actual < maximum
    assert actual.bit_length() > 1024
    # Directly evaluate the untransformed objective at 1600 digits. This
    # retains the successive differences that binary64 costs round to zero,
    # without using the implementation's sign formula or expm1 series.
    with localcontext() as context:
        context.prec = 1600
        single = Decimal(2)**-2500
        log_failure = (1-single).ln()

        def objective(targets):
            probability = 1-(Decimal(targets)*log_failure).exp()
            return conversion*Decimal(targets)+(shared+5*Decimal(targets))/probability

        cost = objective(actual)
        assert cost < objective(actual-1)
        assert cost <= objective(actual+1)


def test_memory_bound_reduces_active_batch_instead_of_discarding_the_instance():
    # At most five syndromes fit with p=1,delta=0; more fit with delta=1.
    bound = log2(200*(100+50+5*51))
    result = optimize(200, 100, 20, targets=100, memory_bound_log2_bits=bound)
    assert result is not None
    assert result.memory_log2 <= bound
    assert result.parameters["targets_used"] <= 100
    replay = evaluate_parameters(200, 100, 20, memory_bound_log2_bits=bound, **result.parameters)
    assert replay is not None and replay.time_log2 == result.time_log2
    assert optimize(200, 100, 20, targets=100, memory_bound_log2_bits=0) is None


def test_partition_is_positive_exact_and_preserves_the_published_shape_at_its_size():
    assert _partition(sum(_PAPER_BLOCKS), _PAPER_BLOCKS) == _PAPER_BLOCKS
    for total in (10, 13, 101, 17669):
        partition = _partition(total, _PAPER_BLOCKS)
        assert len(partition) == 10
        assert sum(partition) == total
        assert min(partition) >= 1


@pytest.mark.parametrize("kwargs", [dict(n=12, k=0, w=3), dict(n=12, k=12, w=3),
                                     dict(n=12, k=6, w=7), dict(n=12, k=6, w=0),
                                     dict(n=12, k=6, w=3, targets=0),
                                     dict(n=12, k=6, w=3, targets=True),
                                     dict(n=12, k=6, w=3, memory_bound_log2_bits=float("inf")),
                                     dict(n=12, k=6, w=3, memory_bound_log2_bits=-1)])
def test_invalid_and_unsupported_shapes_return_none(kwargs):
    assert optimize(**kwargs) is None


def test_other_algorithms_are_not_public_aliases_for_this_optimizer():
    with pytest.raises(ValueError, match="Unknown MAGE search algorithm"):
        optimize(24, 12, 4, algorithm="Stern")
