"""Prove the bounded Gaussian search preserves the pinned upstream model."""

from copy import deepcopy
from math import inf
from types import SimpleNamespace

import pytest

from cryptographic_estimators.SDEstimator import Dumer, Prange, SDProblem, Stern
from cryptographic_estimators.SDEstimator.sd_helper import _optimize_m4ri
from cryptographic_estimators.SDFqEstimator import Prange as FqPrange, SDFqProblem

from codebased_estimator import AttackInstance, Options, Problem, estimate
from codebased_estimator import backend


@pytest.mark.parametrize("mem", [-inf, -1, 0, 0.1, 1, 1.25, 2, 2.5, 4, 10, inf])
def test_bounded_search_matches_upstream_across_dimensions_and_memory(mem):
    for n in (2, 3, 5, 10, 25, 100, 1000):
        for k in sorted({1, n // 2, n - 1}):
            assert backend._bounded_m4ri_r(n, k, mem) == _optimize_m4ri(n, k, mem)


def test_search_preserves_upstreams_selected_parameter_memory_comparison():
    # Upstream checks the previous selected r, not the candidate. Thus it can
    # select r=3 while mem=1, and then never accept another candidate.
    assert _optimize_m4ri(200, 100, 1) == 3
    assert backend._bounded_m4ri_r(200, 100, 1) == 3


def test_large_submission_search_evaluates_only_a_logarithmic_prefix(monkeypatch):
    calls = []
    original = backend._m4ri_cost

    def count_cost(n, k, r):
        calls.append(r)
        return original(n, k, r)

    backend._bounded_m4ri_r.cache_clear()
    monkeypatch.setattr(backend, "_m4ri_cost", count_cost)
    assert backend._bounded_m4ri_r(522344, 261172) == 15
    assert calls == list(range(len(calls)))
    assert 1 < len(calls) < 40  # Upstream otherwise scans 261172 candidates.
    # Cached scalar dimensions/memory can be reused by Prange and Stern.
    evaluated = len(calls)
    backend._bounded_m4ri_r(522344, 261172)
    assert len(calls) == evaluated
    backend._bounded_m4ri_r.cache_clear()


def test_nonpositive_effective_memory_short_circuits_without_gaussian_costs(monkeypatch):
    def unexpected_cost(*args):
        pytest.fail("No update is possible when selected r=0 is not below mem")

    backend._bounded_m4ri_r.cache_clear()
    monkeypatch.setattr(backend, "_m4ri_cost", unexpected_cost)
    assert backend._bounded_m4ri_r(522344, 261172, 0) == 0
    assert backend._bounded_m4ri_r(522344, 261172, -10) == 0
    backend._bounded_m4ri_r.cache_clear()


def test_seeded_stern_retains_adaptive_ranges_and_full_upstream_costs():
    def fresh_stern():
        return Stern(SDProblem(200, 100, 20, nsolutions=0),
                     bit_complexities=1, complexity_type=0, memory_access=0)

    direct, seeded = fresh_stern(), fresh_stern()
    initial_ranges = deepcopy(direct.parameter_ranges)
    assert backend._seed_bounded_m4ri(seeded)
    assert seeded._variable_parameter_ranges == direct._variable_parameter_ranges == 1
    assert seeded.time_complexity() == direct.time_complexity()
    assert seeded.memory_complexity() == direct.memory_complexity()
    assert seeded.get_optimal_parameters_dict() == direct.get_optimal_parameters_dict()
    assert direct.parameter_ranges["p"] != initial_ranges["p"]
    assert seeded.parameter_ranges == direct.parameter_ranges


def test_shortcut_scope_excludes_other_algorithms_fields_and_versions(monkeypatch):
    dumer = Dumer(SDProblem(200, 100, 20, nsolutions=0))
    nonbinary = FqPrange(SDFqProblem(860, 430, 116, 433, nsolutions=0,
                                   is_syndrome_zero=False))
    assert not backend._seed_bounded_m4ri(dumer)
    assert not backend._seed_bounded_m4ri(nonbinary)
    monkeypatch.setattr(backend, "metadata", SimpleNamespace(
        version=lambda name: "2.1.2", PackageNotFoundError=backend.metadata.PackageNotFoundError,
    ))
    binary = Prange(SDProblem(200, 100, 20, nsolutions=0))
    assert not backend._seed_bounded_m4ri(binary)
    assert binary._optimal_parameters == {}


def test_adapter_records_the_exact_search_shortcut_only_where_used():
    for q in (2, 433):
        attack = AttackInstance("metadata", "msg_recovery",
                                Problem("sd", {"n": 100, "k": 50, "w": 10, "q": q}, 0))
        row = estimate(attack, options=Options(classical_algorithms=("Prange",),
                                             quantum_algorithms=())).results[0]
        assert row.status == "computed"
        if q == 2:
            assert "exact bounded equivalent" in row.metadata["gaussian_elimination_search"]
        else:
            assert "gaussian_elimination_search" not in row.metadata
