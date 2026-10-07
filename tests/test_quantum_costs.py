"""Check finite quantum time estimates against small independent calculations."""

from fractions import Fraction
from math import isfinite, log2, prod, sqrt

import pytest

from cryptographic_estimators.SDEstimator.sd_helper import _list_merge_complexity

from codebased_estimator.list_costs import ce_ordered_merge_cost, setup_list_sizes
from codebased_estimator.quantum_costs import evaluate_parameters, optimize


def _rho(n, k, ell):
    """Ordinary arithmetic is adequate for the small hand-calculated examples."""
    m, r, K = n - k, n - k - ell, k + ell
    return (
        prod(1 - 2 ** (i - m) for i in range(r))
        * prod(1 - 2 ** (i - K) for i in range(ell))
        / prod(1 - 2 ** (i - n) for i in range(m))
    )


@pytest.mark.parametrize("length", [1, 7, 8, 9, 256])
def test_ordered_merge_primitive_matches_ce_on_ordinary_integer_lengths(length):
    # Include full collisions and collision expectations below one, as well
    # as the singleton convention and both sides of sorting-depth boundaries.
    for matching_bits in (0, 1, 7, 2 * length.bit_length() + 5):
        assert ce_ordered_merge_cost(length, matching_bits) == _list_merge_complexity(
            length, matching_bits, hmap=False)


def test_ordered_merge_uses_exact_floor_log_at_huge_integer_boundaries():
    power = 1 << 2000
    # Floating log2(power-1) rounds to 2000; its exact floor is 1999.
    # This deliberately follows the intended integer primitive rather than
    # duplicating that upstream floating-point boundary artifact.
    assert ce_ordered_merge_cost(power - 1, 5000) == 3998 * (power - 1)
    assert ce_ordered_merge_cost(power, 4000) == 4000 * power + 1
    assert ce_ordered_merge_cost(power + 1, 3999) == 4000 * (power + 1) + 2


@pytest.mark.parametrize("u,f,ell,expected", [
    (1, 5, 10, (1, 0)),
    (6, 4, 4, (2, 4)),
    (1 << 1000, 1500, 4000, (1 << 500, 0)),
])
def test_setup_proxies_round_each_level_and_keep_an_empty_output_empty(u, f, ell, expected):
    # In particular u=6,f=ell=4 gives J2=4, not floor(u^4/2^(ell+f))=5.
    assert setup_list_sizes(u, f, ell) == expected


@pytest.mark.parametrize("algorithm,V,numerator,R", [
    ("QSS", 4, 256, 1),
    ("QMMT+", 8, 784, 4),
])
def test_report_combinatorial_anchor_keeps_ss_and_plain_qmmt_distinct(
        algorithm, V, numerator, R):
    result = evaluate_parameters(24, 12, 4, algorithm, ell=4, p=4)
    assert result is not None
    assert result.details["log2_V"] == pytest.approx(log2(V))
    assert result.details["log2_P"] == pytest.approx(log2(numerator / 10626))
    assert result.details["log2_R"] == pytest.approx(log2(R))
    assert result.details["log2_sigma"] == 0


def test_walk_budget_includes_exact_lazy_four_axis_gap_and_one_time_preparation():
    result = evaluate_parameters(24, 12, 4, "QSS", ell=4, p=4, u=2, a=1)
    assert result is not None
    assert result.parameters["branch"] == "walk"
    # Here epsilon=1/16 and delta=1/8. The following values are calculated
    # directly for V=4,u=2,f=1, not through the implementation's cost helpers.
    walk_cost = 40 + 60 * sqrt(8)
    expected_components = {
        "log2_D1": 2,
        "log2_D2": 0.5,
        "log2_g_leaf": 2.5,
        "log2_G": 420,
        "log2_S": 36,
        "log2_U": 15,
        "log2_C": 1,
        "log2_Q": walk_cost,
        "log2_T0": 362,
        "log2_delta": 1 / 8,
        "log2_epsilon_lower": 1 / 16,
        "log2_setup_list_size": 2,
        "log2_setup_merge_first": 6,
        "log2_setup_merge_last": 4,
    }
    for key, expected in expected_components.items():
        assert result.details[key] == pytest.approx(log2(expected))
    assert result.details["log2_setup_output_count"] is None
    assert result.details["log2_setup_output_index"] is None
    success = (256 / 10626) * _rho(24, 12, 4)
    expected_time = 362 + 24 / sqrt(success) * (420 + sqrt(2) * walk_cost)
    assert result.time_log2 == pytest.approx(log2(expected_time))


def test_cached_old_leaf_and_output_bundle_preserve_dynamic_index_work():
    result = evaluate_parameters(12, 4, 4, "QMMT+",
                                 ell=4, p=4, d=2, u=2, a=1)
    assert result is not None
    # g=4: generate the new leaf for 4, delete its cached predecessor for 1.
    # U=(4+1)+2*2+2*1*(1+2)+2*(1/4)*(1+2)=16.5.
    # The last term keeps the candidate index but bundles output/check work.
    assert result.details["log2_g_leaf"] == pytest.approx(log2(4))
    assert result.details["log2_U"] == pytest.approx(log2(16.5))
    assert result.details["log2_S"] == pytest.approx(log2(48))
    assert result.details["log2_Q"] == pytest.approx(log2(57 + 148.5 * sqrt(32 / 3)))


def test_fractional_dynamic_loads_survive_integer_setup_proxy_rounding():
    result = evaluate_parameters(24, 12, 4, "QSS", ell=4, p=4, u=1, a=3)
    assert result is not None
    # Actual mean loads remain 1/8 and 1/128; the setup-only CE proxies are
    # J1=1 and J2=0. Neither the singleton convention nor empty setup output
    # erases the nonzero mean fanout used to maintain the quantum walk.
    assert result.details["log2_D1"] == -3
    assert result.details["log2_D2"] == -7
    assert result.details["log2_setup_list_size"] == 0
    assert result.details["log2_setup_output_count"] is None
    assert result.details["log2_setup_output_index"] is None
    assert result.details["log2_S"] == pytest.approx(log2(13))
    assert result.details["log2_U"] == pytest.approx(log2(8.296875))


def test_full_list_branch_does_not_apply_the_walk_or_low_fanout_constraints():
    # u=V=4 and f=0 violate the walk's u<=V/2 and first-layer fanout bounds.
    result = evaluate_parameters(24, 12, 4, "QSS", ell=4, p=4, u=4)
    assert result is not None
    assert result.parameters["branch"] == "full_list"
    assert result.details["log2_S"] == pytest.approx(log2(328))
    assert result.details["log2_Q"] == pytest.approx(log2(329))
    success = (256 / 10626) * _rho(24, 12, 4)
    assert result.time_log2 == pytest.approx(log2(362 + 24 / sqrt(success) * 749))


def test_qmmt_total_uses_representation_survival_without_an_extra_r_speedup():
    result = evaluate_parameters(12, 4, 4, "QMMT+",
                                 ell=4, p=4, d=2, u=6, b=4)
    assert result is not None
    assert result.parameters["branch"] == "full_list"
    # V=6, R=16, g_leaf=4; the mean intermediate length is 9/4, while
    # setup uses J1=2 and J2=4 after rounding each level separately.
    # Full-list Q=S+1, and R enters success through sigma=16/31 only.
    assert result.details["log2_S"] == pytest.approx(log2(168))
    assert result.details["log2_Q"] == pytest.approx(log2(169))
    assert result.details["log2_setup_list_size"] == pytest.approx(log2(2))
    assert result.details["log2_setup_output_count"] == pytest.approx(log2(4))
    assert result.details["log2_setup_output_index"] == pytest.approx(log2(12))
    success = (36 / 495) * _rho(12, 4, 4) * (16 / 31)
    expected_time = 183 + 12 / sqrt(success) * (172 + 169)
    assert result.time_log2 == pytest.approx(log2(expected_time))


@pytest.mark.parametrize("algorithm", ["QSS", "QMMT+"])
@pytest.mark.parametrize("p,support_probability,candidate_cost", [
    (0, Fraction(1, 6), 1),
    (3, Fraction(1, 30), 4),
])
def test_unique_candidate_bypasses_divisibility_and_charges_its_linear_image(
        algorithm, p, support_probability, candidate_cost):
    # K=3 is not divisible by four (or two); p=K remains a valid direct check.
    result = evaluate_parameters(10, 2, 4, algorithm, ell=1, p=p)
    assert result is not None
    assert result.parameters["branch"] == "direct"
    assert result.details["log2_P"] == pytest.approx(log2(support_probability))
    assert result.details["log2_sigma"] == 0
    assert result.details["log2_T0"] == pytest.approx(log2(90))
    success = float(support_probability) * _rho(10, 2, 1)
    expected_time = 90 + 10 / sqrt(success) * (194 + candidate_cost)
    assert result.time_log2 == pytest.approx(log2(expected_time))


@pytest.mark.parametrize("unused_parameters", [{"d": 2}, {"u": 2}, {"a": 1}, {"b": 1}])
def test_direct_branch_has_one_canonical_parameter_choice(unused_parameters):
    assert evaluate_parameters(12, 4, 4, "QMMT+", ell=4, p=0,
                               **unused_parameters) is None


@pytest.mark.parametrize("changes", [
    {"u": 0}, {"u": 3}, {"a": 0}, {"a": 5}, {"b": 1},
    {"d": 2}, {"ell": 3}, {"ell": 13}, {"p": 2}, {"p": 8},
])
def test_infeasible_points_are_not_silently_rounded_or_relaxed(changes):
    parameters = {"ell": 4, "p": 4, "u": 2, "a": 1}
    parameters.update(changes)
    assert evaluate_parameters(24, 12, 4, "QSS", **parameters) is None


@pytest.mark.parametrize("arguments", [
    (8, 0, 1, "QSS"), (8, 4, 5, "QMMT+"),
    (8.0, 4, 1, "QSS"), (8, 4, True, "QSS"), (8, 4, 1, "QPrange"),
])
def test_cost_api_rejects_invalid_instances_and_unimplemented_algorithms(arguments):
    with pytest.raises(ValueError):
        evaluate_parameters(*arguments, ell=0, p=0)
    with pytest.raises(ValueError):
        optimize(*arguments)


def test_large_lists_and_tiny_expected_loads_remain_in_log_space():
    b = 1000
    result = evaluate_parameters(100000, 50000, 10000, "QMMT+",
                                 ell=20000, p=4000, d=2000, b=b)
    assert result is not None
    assert isfinite(result.time_log2)
    assert result.details["log2_V"] > 1024
    assert isfinite(result.details["log2_R"])
    assert result.details["log2_D1"] == pytest.approx(-b)
    assert result.details["log2_D2"] == pytest.approx(-20000 - b)
    assert result.details["log2_setup_list_size"] == 0
    assert result.details["log2_setup_output_count"] is None
    assert result.details["log2_setup_output_index"] is None
    assert result.details["log2_sigma"] <= 0
    assert isfinite(result.details["log2_sigma"])
