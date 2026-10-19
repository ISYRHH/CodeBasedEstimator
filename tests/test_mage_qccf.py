"""QCCF uses codeword success events while retaining one-syndrome tree costs."""

from decimal import Decimal, localcontext
from fractions import Fraction
import json
from math import comb, inf, log2, nextafter
from types import SimpleNamespace

import pytest

from codebased_estimator import AttackInstance, Options, Problem, estimate
from codebased_estimator import mage_search
from codebased_estimator.mage_costs import evaluate_parameters


def qccf_instance(*, kind="cfp", codewords=8, parameters=None,
                  tags=("doom:qccf",), structure=()):
    return AttackInstance(
        "MAGE QCCF", "key_recovery",
        Problem(kind, {"n": 40, "k": 20, "w": 4} if parameters is None else parameters),
        targets=codewords, tags=tags, structure=structure,
    )


def fraction_log2(value):
    return log2(value.numerator)-log2(value.denominator)


@pytest.mark.parametrize("codewords", [1, 3, 57, 1000])
def test_fixed_codeword_cost_matches_exact_independent_union(codewords):
    point = evaluate_parameters(20, 10, 3, ell=2, p=1, delta=1, codewords=codewords)
    # One codeword has S=7/57. Neither lists, target transformations nor the
    # input conversion are multiplied by the number of acceptable codewords.
    probability = 1-Fraction(50, 57)**codewords
    assert point is not None
    assert point.time_log2 == pytest.approx(fraction_log2(2100+2345/probability), abs=1e-11)
    assert point.memory_log2 == pytest.approx(log2(340))
    assert point.details["log2_tree_bit_cost"] == pytest.approx(log2(2345))
    assert point.details["log2_conversion_bit_cost"] == pytest.approx(log2(2100))
    assert point.details["log2_success_probability"] == pytest.approx(fraction_log2(probability), abs=1e-11)
    assert point.details["log2_single_target_success_probability"] == point.details["log2_success_probability"]
    assert point.details["log2_single_codeword_success_probability"] == pytest.approx(log2(Fraction(7, 57)))
    assert point.details["log2_single_solution_probability"] == point.details["log2_single_codeword_success_probability"]
    assert point.details["cost_model"] == "ce-mage-qccf-codewords-v1"
    assert point.details["target_success_model"] == "independent-codeword-tree-union-v1"
    assert point.details["codeword_success_model"] == "independent-codeword-tree-union-v1"
    assert point.details["success_event_kind"] == "codewords"
    assert point.details["codeword_count"] == codewords
    assert point.details["effective_syndrome_targets"] == 1
    assert point.parameters["targets_used"] == 1
    assert point.parameters["codewords"] == codewords
    assert evaluate_parameters(20, 10, 3, **point.parameters) == point


@pytest.mark.parametrize("blocks,repetitions", [((10,), (1, 1)), ((6, 4), (2, 3, 2))])
@pytest.mark.parametrize("codewords", [1, 8, 1 << 100])
def test_codewords_preserve_full_tree_work_lists_and_memory(blocks, repetitions, codewords):
    arguments = dict(ell=2, p=1, delta=1, blocks=blocks, repetitions=repetitions)
    ordinary = evaluate_parameters(20, 10, 3, **arguments)
    point = evaluate_parameters(20, 10, 3, **arguments, codewords=codewords)
    assert point is not None
    assert point.memory_log2 == ordinary.memory_log2
    for key in (
        "log2_base_lists", "log2_expanded_base_lists", "log2_outputs_per_target",
        "log2_total_outputs", "log2_tree_bit_cost", "log2_leaf_bit_cost",
        "log2_tree_gaussian_bit_cost", "log2_level_gaussian_bit_costs",
        "log2_leaves", "log2_conversion_bit_cost", "log2_online_memory_bits",
        "log2_conversion_memory_bits", "log2_active_targets",
    ):
        assert point.details[key] == ordinary.details[key], key
    if codewords == 1:
        assert point.time_log2 == ordinary.time_log2
        assert point.details["log2_success_probability"] == ordinary.details["log2_success_probability"]
    else:
        assert point.time_log2 < ordinary.time_log2
    assert evaluate_parameters(20, 10, 3, **arguments, codewords=codewords,
                               memory_bound_log2_bits=ordinary.memory_log2) is not None
    assert evaluate_parameters(20, 10, 3, **arguments, codewords=codewords,
                               memory_bound_log2_bits=nextafter(ordinary.memory_log2, -inf)) is None


def test_enormous_codeword_count_uses_stable_probability_without_expanding_cost():
    n, k, w, ell, codewords = 8000, 4000, 2000, 10, 1 << 2478
    numerator = comb(k//2, 1)*comb(k-k//2, 1)*comb(n-k-ell, w-2)
    denominator = comb(n, w)
    with localcontext() as context:
        context.prec = 1000
        single = Decimal(numerator)/Decimal(denominator)
        probability = 1-(Decimal(codewords)*(1-single).ln()).exp()
        expected = float(probability.ln()/Decimal(2).ln())
    ordinary = evaluate_parameters(n, k, w, ell=ell, p=1)
    point = evaluate_parameters(n, k, w, ell=ell, p=1, codewords=codewords)
    assert point.details["log2_single_codeword_success_probability"] < -1074
    assert point.details["log2_success_probability"] == pytest.approx(expected, abs=1e-9)
    assert point.memory_log2 == ordinary.memory_log2
    assert point.details["log2_tree_bit_cost"] == ordinary.details["log2_tree_bit_cost"]
    assert point.details["log2_conversion_bit_cost"] == ordinary.details["log2_conversion_bit_cost"]
    assert -inf < point.time_log2 < inf


@pytest.mark.parametrize("codewords", [0, -1, True, 1.0, "8"])
def test_invalid_codeword_counts_are_rejected_by_kernel_and_search(codewords):
    assert evaluate_parameters(20, 10, 3, ell=2, p=1, delta=1, codewords=codewords) is None
    assert mage_search.optimize(20, 10, 3, codewords=codewords) is None


@pytest.mark.parametrize("codewords", [1, 2])
def test_codeword_mode_does_not_silently_mix_with_multiple_syndromes(codewords):
    assert evaluate_parameters(20, 10, 3, ell=2, p=1, delta=1,
                               targets=2, codewords=codewords) is None
    assert evaluate_parameters(20, 10, 3, ell=2, p=1, delta=1,
                               targets_used=2, codewords=codewords) is None
    assert mage_search.optimize(20, 10, 3, targets=2, codewords=codewords) is None


def test_none_codewords_preserves_sd_and_qcsd_kernel_results():
    for targets in (1, 8):
        arguments = dict(ell=2, p=1, delta=1, targets=targets)
        ordinary = evaluate_parameters(20, 10, 3, **arguments)
        assert evaluate_parameters(20, 10, 3, **arguments, codewords=None) == ordinary
        assert "codewords" not in ordinary.parameters
        assert ordinary.details["cost_model"] == "ce-mage-generator-v2"


def test_codeword_count_is_used_during_tree_search_and_has_a_separate_cache(monkeypatch):
    evaluated = []
    original = mage_search.evaluate_parameters

    def record_evaluation(*args, **kwargs):
        evaluated.append(dict(kwargs))
        return original(*args, **kwargs)

    def reject_syndrome_batch(*args, **kwargs):
        pytest.fail("QCCF codewords must not use the syndrome batch optimizer")

    monkeypatch.setattr(mage_search, "evaluate_parameters", record_evaluation)
    monkeypatch.setattr(mage_search, "optimal_target_batch", reject_syndrome_batch)
    mage_search._optimize.cache_clear()
    results = []
    for codewords in (1, 64):
        evaluated.clear()
        point = mage_search.optimize(12, 6, 2, codewords=codewords)
        assert point is not None and len(evaluated) > 1
        assert all(call["codewords"] == codewords for call in evaluated)
        assert all(call.get("targets", call.get("targets_used", 1)) == 1 for call in evaluated)
        assert point.parameters["codewords"] == codewords
        assert point.parameters["targets_used"] == 1
        assert point.search["codeword_count"] == codewords
        assert point.search["available_targets"] == 1
        replay = evaluate_parameters(12, 6, 2, **point.parameters)
        assert (point.time_log2, point.memory_log2, point.details) == (
            replay.time_log2, replay.memory_log2, replay.details)
        baseline = evaluate_parameters(12, 6, 2, **point.search["one_level_baseline_parameters"])
        assert baseline.parameters["codewords"] == codewords
        assert point.time_log2 <= baseline.time_log2
        results.append(point)
    assert mage_search._optimize.cache_info().misses == 2
    evaluated.clear()
    repeated = mage_search.optimize(12, 6, 2, codewords=1)
    assert not evaluated
    assert repeated == results[0] and repeated is not results[0]
    assert results[0].time_log2 != results[1].time_log2
    reused_single_word_shape = {**results[0].parameters, "codewords": 64}
    reused = evaluate_parameters(12, 6, 2, **reused_single_word_shape)
    assert results[1].time_log2 < reused.time_log2
    repeated.parameters["codewords"] = -1
    assert mage_search.optimize(12, 6, 2, codewords=1) == results[0]
    mage_search._optimize.cache_clear()


def test_one_codeword_search_preserves_single_solution_cost_with_distinct_mode_cache():
    mage_search._optimize.cache_clear()
    ordinary = mage_search.optimize(12, 6, 2)
    one_word = mage_search.optimize(12, 6, 2, codewords=1)
    assert (one_word.time_log2, one_word.memory_log2) == (ordinary.time_log2, ordinary.memory_log2)
    assert one_word.parameters == {**ordinary.parameters, "codewords": 1}
    assert ordinary.details["cost_model"] == "ce-mage-generator-v2"
    assert one_word.details["cost_model"] == "ce-mage-qccf-codewords-v1"
    assert mage_search._optimize.cache_info().misses == 2
    assert mage_search.optimize(12, 6, 2) == ordinary
    assert mage_search.optimize(12, 6, 2, codewords=1) == one_word
    mage_search._optimize.cache_clear()


@pytest.fixture
def codeword_search(monkeypatch):
    state = SimpleNamespace(calls=[], time_log2=100.0, memory_log2=12.0)

    def optimize(*args, **kwargs):
        state.calls.append((args, dict(kwargs)))
        return SimpleNamespace(
            time_log2=state.time_log2, memory_log2=state.memory_log2,
            parameters={"ell": 4, "p": 1, "delta": 1, "blocks": [10, 10],
                        "repetitions": [1, 2, 1], "targets_used": 1,
                        "codewords": kwargs["codewords"]},
            details={"log2_success_probability": -3.0},
            search={"method": "QCCF integration fixture", "global_optimum": False},
        )

    monkeypatch.setattr(mage_search, "optimize", optimize)
    return state


@pytest.mark.parametrize("kind", ["cfp", "qccf"])
@pytest.mark.parametrize("codewords", [1, 8, 1 << 1024])
def test_qccf_aliases_pass_codewords_before_search_without_extra_discount(kind, codewords, codeword_search):
    instance = qccf_instance(kind=kind, codewords=codewords)
    report = estimate(instance, options=Options(
        classical_algorithms=("MAGE-Stern",), quantum_algorithms=(), memory_bound_log2_bits=16,
    ))
    row, = report.results
    assert codeword_search.calls == [((40, 20, 4), {
        "algorithm": "MAGE-Stern", "targets": 1, "codewords": codewords,
        "memory_bound_log2_bits": 16,
    })]
    assert row.status == "computed"
    assert row.time_log2 == 100.0 and row.memory_log2 == 12.0
    assert row.metadata["cost_model"] == "ce-mage-qccf-codewords-v1"
    assert row.metadata["target_success_model"] == "independent-codeword-tree-union-v1"
    assert row.metadata["effective_log2_solutions"] == log2(codewords)
    assert row.metadata["effective_syndrome_targets"] == 1
    doom = row.metadata["doom"]
    assert doom["model"] == "mage_stern_codeword_proxy"
    assert doom["available_codewords"] == doom["active_codewords"] == codewords
    assert doom["available_targets"] == codewords
    assert "active_targets" not in doom
    assert doom["postprocessing_speedup_applied"] is False
    assert row.parameters["targets_used"] == 1 and row.parameters["codewords"] == codewords
    assert report.instance == instance
    assert "proxy" in " ".join(row.assumptions).lower()
    json.dumps(report.to_dict(), allow_nan=False)


def test_one_codeword_overrides_ce_expected_multiple_solution_default(codeword_search):
    instance = qccf_instance(codewords=1, parameters={"n": 40, "k": 20, "w": 10})
    row, = estimate(instance, options=Options(
        classical_algorithms=("MAGE-Stern",), quantum_algorithms=(),
    )).results
    assert row.status == "computed"
    assert codeword_search.calls[0][1]["codewords"] == 1
    assert row.metadata["effective_log2_solutions"] == 0


@pytest.mark.parametrize("changes", [
    {"parameters": {"n": 40, "k": 20, "w": 4, "q": 3}},
    {"tags": ()}, {"tags": ("doom:qccf", "unmodeled")}, {"structure": ("regular",)},
])
def test_qccf_unmodeled_context_is_rejected_before_search(changes, codeword_search):
    row, = estimate(qccf_instance(**changes), options=Options(
        classical_algorithms=("MAGE-Stern",), quantum_algorithms=(),
    )).results
    assert row.status == "not_implemented" and row.reason
    assert row.time_log2 is None and row.memory_log2 is None
    assert not codeword_search.calls


def test_qccf_memory_bound_is_applied_to_the_single_syndrome_workspace():
    instance = qccf_instance(codewords=1000, parameters={"n": 20, "k": 10, "w": 3})
    row, = estimate(instance, options=Options(
        classical_algorithms=("MAGE-Stern",), quantum_algorithms=(), memory_bound_log2_bits=log2(600),
    )).results
    assert row.status == "computed" and row.memory_log2 <= log2(600)
    replay = evaluate_parameters(20, 10, 3, memory_bound_log2_bits=log2(600),
                                 **{key: value for key, value in row.parameters.items() if key != "strategy"})
    assert (row.time_log2, row.memory_log2) == (replay.time_log2, replay.memory_log2)
    assert row.parameters["codewords"] == 1000
    infeasible, = estimate(instance, options=Options(
        classical_algorithms=("MAGE-Stern",), quantum_algorithms=(), memory_bound_log2_bits=0,
    )).results
    assert infeasible.status == "infeasible" and infeasible.reason
