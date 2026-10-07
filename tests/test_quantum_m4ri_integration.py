"""Matrix-profile integration: isolated cost changes and candidate retention."""

from dataclasses import replace
import json
from math import log2

import pytest

from codebased_estimator import quantum_costs as costs
from codebased_estimator.matrix_costs import (
    DEFAULT_MATRIX_PROFILE, M4RI_MATRIX_PROFILE, matrix_budget,
)


def parameters(cost):
    return {key: value for key, value in cost.parameters.items() if key != "branch"}


@pytest.mark.parametrize("algorithm,point", [
    ("QSS", dict(ell=4, p=4, u=2, a=1)),
    ("QMMT+", dict(ell=4, p=4, d=2, u=28, b=4)),
    ("QSS", dict(ell=3, p=0)),
])
def test_all_branches_preserve_the_accepted_nonmatrix_costs(algorithm, point):
    legacy = costs.evaluate_parameters(24, 12, 4, algorithm, **point)
    new = costs.evaluate_parameters(24, 12, 4, algorithm,
                                    matrix_profile=M4RI_MATRIX_PROFILE, **point)
    assert legacy is not None and new is not None
    assert legacy.matrix == {}
    assert legacy.parameters == new.parameters
    assert {k: v for k, v in legacy.details.items() if k != "log2_G"} == {
        k: v for k, v in new.details.items() if k != "log2_G"
    }
    budget = matrix_budget(24, 12, point["ell"], M4RI_MATRIX_PROFILE)
    assert new.details["log2_G"] == log2(budget.total)
    assert new.matrix["log2_G_core"] == log2(budget.core)
    assert new.matrix["log2_G_prepare"] == log2(budget.preparation)
    assert new.time_log2 <= legacy.time_log2


def test_no_tail_has_zero_core_and_strict_json_metadata():
    point = costs.evaluate_parameters(8, 4, 4, "QSS", ell=4, p=4, u=1,
                                      matrix_profile=M4RI_MATRIX_PROFILE)
    assert point is not None
    assert point.matrix["block_size"] == 0
    assert point.matrix["table_peak_records"] == 0
    assert point.matrix["log2_G_core"] is None
    assert point.details["log2_G"] == point.matrix["log2_G_prepare"]
    json.dumps(point.matrix, allow_nan=False)


def test_legacy_default_and_explicit_profile_have_identical_results():
    implicit = costs.optimize(24, 12, 4, "QMMT+")
    explicit = costs.optimize(24, 12, 4, "QMMT+", matrix_profile=DEFAULT_MATRIX_PROFILE)
    assert implicit == explicit
    assert implicit.matrix == {}
    assert "legacy_retention" not in implicit.search


def test_new_profile_retains_the_legacy_point_even_if_its_search_misses_it(monkeypatch):
    legacy = costs.optimize(24, 12, 4, "QSS")
    retained = costs.evaluate_parameters(24, 12, 4, "QSS",
                                         matrix_profile=M4RI_MATRIX_PROFILE, **parameters(legacy))
    poor = max((costs.evaluate_parameters(24, 12, 4, "QSS", ell=ell, p=0,
                                         matrix_profile=M4RI_MATRIX_PROFILE) for ell in range(9)),
               key=lambda point: point.time_log2)
    assert poor.time_log2 > retained.time_log2

    def search(n, k, w, algorithm, matrix_profile=DEFAULT_MATRIX_PROFILE):
        selected = legacy if matrix_profile == DEFAULT_MATRIX_PROFILE else poor
        return replace(selected, search={"evaluated_points": 7, "global_optimum": False})

    monkeypatch.setattr(costs, "_optimize", search)
    result = costs.optimize(24, 12, 4, "QSS", matrix_profile=M4RI_MATRIX_PROFILE)
    assert result.parameters == retained.parameters
    assert result.time_log2 == retained.time_log2
    assert result.matrix == retained.matrix
    assert result.search["legacy_retention"]["selected_from"] == "legacy_replay"
    assert result.search["evaluated_points"] == 15


@pytest.mark.parametrize("call", [
    lambda: costs.optimize(24, 12, 4, "QSS", matrix_profile="unknown"),
    lambda: costs.evaluate_parameters(24, 12, 4, "QSS", ell=4, p=4, matrix_profile="unknown"),
])
def test_unknown_profiles_are_not_silently_treated_as_the_default(call):
    with pytest.raises(ValueError):
        call()
