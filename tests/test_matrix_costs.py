"""Independent checks of exact partial GE/M4RI vector-budget conventions."""

import json

import pytest

from codebased_estimator.matrix_costs import (
    DEFAULT_MATRIX_PROFILE,
    M4RI_MATRIX_PROFILE,
    MATRIX_PROFILES,
    cost_model_for_profile,
    matrix_budget,
    validate_profile,
)


def _enumerated_core(rows, pivots, block_size):
    if block_size == 0:
        return rows * pivots
    total = 0
    for start in range(0, pivots, block_size):
        width = min(block_size, pivots - start)
        total += width ** 2 + 2 ** width + rows - width
    return total


def test_profiles_are_explicit_and_default_cost_version_is_preserved():
    assert MATRIX_PROFILES == (DEFAULT_MATRIX_PROFILE, M4RI_MATRIX_PROFILE)
    assert validate_profile(DEFAULT_MATRIX_PROFILE) == DEFAULT_MATRIX_PROFILE
    assert cost_model_for_profile(DEFAULT_MATRIX_PROFILE) == "ka17-ce-ordered-average-v2"
    assert cost_model_for_profile(M4RI_MATRIX_PROFILE) == "ka17-ce-ordered-partial-m4ri-v3"
    assert matrix_budget(128, 64, 16).profile == DEFAULT_MATRIX_PROFILE


@pytest.mark.parametrize("profile", [None, 1, True, [], {}, "m4ri", "partial-ge-aggregate-v2"])
def test_invalid_profiles_are_rejected(profile):
    for function in (validate_profile, cost_model_for_profile):
        with pytest.raises(ValueError, match="matrix profile"):
            function(profile)
    with pytest.raises(ValueError, match="matrix profile"):
        matrix_budget(12, 6, 2, profile)


@pytest.mark.parametrize("parameters", [
    (1, 0, 0), (0, 0, 0), (8, 0, 0), (8, 8, 0), (8, 9, 0),
    (8, 4, -1), (8, 4, 5), (8.0, 4, 0), (8, 4.0, 0),
    (8, 4, 0.0), (True, 1, 0), (8, True, 0), (8, 4, False),
])
def test_invalid_dimensions_are_rejected_even_after_equivalent_cache_keys(parameters):
    matrix_budget(8, 1, 0)
    matrix_budget(8, 4, 0)
    with pytest.raises(ValueError, match="integer parameters"):
        matrix_budget(*parameters)


def test_small_domain_matches_independent_full_block_width_enumeration():
    for rows in range(1, 25):
        n, k = 2 * rows + 1, rows + 1
        for pivots in range(rows + 1):
            ell = rows - pivots
            expected = min((_enumerated_core(rows, pivots, h), h)
                           for h in range(pivots + 1))
            budget = matrix_budget(n, k, ell, M4RI_MATRIX_PROFILE)
            assert (budget.core, budget.block_size) == expected
            ordinary = matrix_budget(n, k, ell)
            assert ordinary.core == rows * pivots
            assert budget.preparation == ordinary.preparation
            assert budget.total <= ordinary.total
            search = budget.metadata()["search"]
            assert search["domain"] == {"min": 0, "max": pivots}
            assert search["complete"] is True
            if search["stop_reason"] == "exponential_lower_bound":
                assert search["pruning_bound"] == 2 ** search["next_block_size"]
                assert search["pruning_bound"] >= budget.core
                assert all(_enumerated_core(rows, pivots, h) >= budget.core
                           for h in range(search["next_block_size"], pivots + 1))


@pytest.mark.parametrize("profile", MATRIX_PROFILES)
@pytest.mark.parametrize("pivots", [0, 1])
def test_empty_and_single_pivot_keep_h_zero_and_preparation(profile, pivots):
    budget = matrix_budget(128, 64, 64 - pivots, profile)
    assert (budget.core, budget.block_size) == (64 * pivots, 0)
    assert budget.preparation == 64 * 8 ** 2 + 128
    assert budget.total == budget.core + budget.preparation
    assert budget.metadata()["table_peak_records"] == 0


def test_short_last_panel_is_not_padded_to_the_selected_block_width():
    # m=64, r=47 chooses h=4: eleven full panels followed by a width-3 panel.
    budget = matrix_budget(128, 64, 17, M4RI_MATRIX_PROFILE)
    assert budget.block_size == 4
    assert budget.core == 11 * (4 ** 2 + 2 ** 4 + 64 - 4) + (3 ** 2 + 2 ** 3 + 64 - 3)
    assert budget.core < 12 * (4 ** 2 + 2 ** 4 + 64 - 4)


def test_metadata_certifies_only_its_profile_domain_and_is_independent_of_cache():
    ordinary = matrix_budget(128, 64, 16)
    metadata = ordinary.metadata()
    assert metadata["search"]["domain"] == {"min": 0, "max": 0}
    assert metadata["search"]["evaluated_block_sizes"] == [0]
    assert metadata["search"]["stop_reason"] == "profile_fixed"
    accelerated = matrix_budget(128, 64, 16, M4RI_MATRIX_PROFILE)
    metadata = accelerated.metadata()
    assert metadata["block_size"] == accelerated.block_size
    assert metadata["rows"] == 64 and metadata["pivots"] == 48
    assert metadata["table_peak_records"] == 2 ** accelerated.block_size
    assert json.loads(json.dumps(metadata)) == metadata
    metadata["search"]["evaluated_block_sizes"].append(999)
    metadata["normalization_assumptions"]["unit"] = "changed"
    fresh = matrix_budget(128, 64, 16, M4RI_MATRIX_PROFILE).metadata()
    assert 999 not in fresh["search"]["evaluated_block_sizes"]
    assert fresh["normalization_assumptions"]["unit"] != "changed"
