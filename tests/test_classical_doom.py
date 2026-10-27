"""Classical DOOM routing, optimization, and approximation contracts."""

import json
from itertools import combinations
from math import comb, inf, log2, nextafter

import pytest

from codebased_estimator import AttackInstance, Options, Problem, estimate


EXPLICIT_ALGORITHMS = ("Prange", "Stern", "Dumer", "BJMM")
APPROXIMATE_ALGORITHMS = (
    "BallCollision", "BJMMdw", "BJMMpdw", "BJMMplus", "BothMay", "MayOzerov",
)


def classical_rows(algorithms, *, targets=1, doom=True, solutions=0,
                   memory_bound=None, n=40, k=20, w=4, q=2,
                   tags=None, structure=()):
    attack = AttackInstance(
        "classical DOOM test", "msg_recovery",
        Problem("sd", {"n": n, "k": k, "w": w, "q": q}, solutions),
        targets=targets, tags=(("doom:qcsd",) if doom else ()) if tags is None else tags,
        structure=structure,
    )
    report = estimate(attack, options=Options(
        classical_algorithms=algorithms, quantum_algorithms=(),
        memory_bound_log2_bits=memory_bound,
    ))
    json.dumps(report.to_dict(), allow_nan=False)
    return report.results


@pytest.mark.parametrize("algorithm", EXPLICIT_ALGORITHMS)
def test_one_target_preserves_upstream_cost_memory_and_parameters(algorithm):
    baseline, = classical_rows((algorithm,), doom=False)
    result, = classical_rows((algorithm,), targets=1)
    assert result.status == baseline.status == "computed"
    assert result.time_log2 == baseline.time_log2
    assert result.memory_log2 == baseline.memory_log2
    assert result.parameters == baseline.parameters
    assert result.metadata["doom"]["available_targets"] == 1
    assert result.metadata["doom"]["active_targets"] == 1


@pytest.mark.parametrize("algorithm", EXPLICIT_ALGORITHMS)
def test_explicit_optimizer_can_keep_the_single_target_strategy(algorithm):
    baseline, = classical_rows((algorithm,), doom=False)
    result, = classical_rows((algorithm,), targets=32)
    assert result.status == "computed"
    assert result.time_log2 <= baseline.time_log2
    doom = result.metadata["doom"]
    assert doom["model"] == "parameter_optimized"
    assert doom["cost_model"] == "ce-doom-finite-v2"
    assert doom["available_targets"] == 32
    assert 1 <= doom["active_targets"] <= 32
    assert doom["strategy"] in ("single_target_baseline", "explicit_doom")
    assert doom["search"]
    if doom["strategy"] == "single_target_baseline":
        assert result.parameters == baseline.parameters
        assert result.memory_log2 == baseline.memory_log2
    else:
        assert result.parameters["targets_used"] == doom["active_targets"]


@pytest.mark.parametrize("algorithm", APPROXIMATE_ALGORITHMS)
def test_complex_algorithms_keep_the_requested_sqrt_target_approximation(algorithm):
    baseline, = classical_rows((algorithm,), doom=False)
    result, = classical_rows((algorithm,), targets=32)
    assert result.status == baseline.status == "computed"
    assert result.time_log2 == pytest.approx(max(0, baseline.time_log2 - log2(32) / 2))
    assert result.memory_log2 == baseline.memory_log2
    assert result.parameters == baseline.parameters
    doom = result.metadata["doom"]
    assert doom["model"] == "sqrt_targets_approximation"
    assert doom["available_targets"] == 32
    assert doom["log2_speedup"] == log2(32) / 2


def test_approximation_does_not_produce_negative_work_for_many_targets():
    result, = classical_rows(("BothMay",), targets=1 << 100)
    assert result.status == "computed"
    assert result.time_log2 == 0


@pytest.mark.parametrize("algorithm", ("Prange", "Stern", "Dumer", "BJMM", "BothMay"))
def test_target_count_does_not_replace_per_syndrome_solution_count(algorithm):
    result, = classical_rows((algorithm,), targets=32, solutions=2)
    assert result.status == "computed"
    assert result.metadata["effective_log2_solutions"] == 2
    assert result.metadata["doom"]["available_targets"] == 32


@pytest.mark.parametrize("algorithm", EXPLICIT_ALGORITHMS + ("BothMay",))
def test_doom_does_not_turn_an_impossible_memory_budget_into_a_feasible_result(algorithm):
    result, = classical_rows((algorithm,), targets=32, memory_bound=0)
    assert result.status in ("infeasible", "not_applicable")
    assert result.reason


@pytest.mark.parametrize("options", [
    {"q": 3, "structure": ("block weights",)},
    {"q": 3, "tags": ("doom:qcsd", "unmodeled tag")},
    {"structure": ("block weights",)},
    {"tags": ("doom:qcsd", "unmodeled tag")},
    {"doom": False},
])
def test_doom_does_not_discard_unmodeled_context(options):
    rows = classical_rows(("Prange", "Stern"), targets=32, **options)
    assert all(row.status == "not_implemented" for row in rows)
    assert all(row.time_log2 is None and row.memory_log2 is None and row.reason
               for row in rows)


@pytest.mark.parametrize("algorithm", ["Prange", "Stern", "LeeBrickell"])
@pytest.mark.parametrize("solutions", [None, 0, 2])
@pytest.mark.parametrize("targets", [1, 1 << 100])
def test_qary_qcsd_falls_back_to_the_same_single_target_cost(algorithm, solutions, targets):
    settings = dict(q=3, solutions=solutions)
    baseline, = classical_rows((algorithm,), doom=False, **settings)
    row, = classical_rows((algorithm,), targets=targets, **settings)
    assert row.status == baseline.status == "computed"
    assert row.time_log2 == baseline.time_log2
    assert row.memory_log2 == baseline.memory_log2
    assert row.parameters == baseline.parameters
    assert row.metadata["is_syndrome_zero"] is False
    assert row.metadata["effective_log2_solutions"] == baseline.metadata["effective_log2_solutions"]
    assert row.metadata["tags"] == ["doom:qcsd"] and row.metadata["targets"] == targets
    assert row.metadata["effective_tags"] == [] and row.metadata["effective_targets"] == 1
    assert row.metadata["doom"]["model"] == "single_target_fallback"
    assert row.metadata["doom"]["available_targets"] == targets
    assert row.metadata["doom"]["active_targets"] == 1
    assert row.metadata["doom"]["applied"] is False
    assert row.metadata["doom"]["fallback_reason"] in row.reason


@pytest.mark.parametrize("algorithm", ["Prange", "Stern", "LeeBrickell"])
def test_qary_fallback_preserves_an_impossible_memory_budget(algorithm):
    baseline, = classical_rows((algorithm,), doom=False, q=3, memory_bound=0)
    row, = classical_rows((algorithm,), targets=32, q=3, memory_bound=0)
    assert row.status == baseline.status
    assert row.status in ("infeasible", "not_applicable")
    assert row.time_log2 == baseline.time_log2
    assert row.memory_log2 == baseline.memory_log2
    assert row.parameters == baseline.parameters
    assert row.metadata["doom"]["applied"] is False


def test_bjmm_weight_deficit_matches_enumerated_errors_and_xor_representations():
    from codebased_estimator.doom_bjmm import bjmm_terms

    # R=12 needs ceil(log2 R)=4 matching bits; l=2 is no longer admissible.
    assert bjmm_terms(12, 6, 4, ell=2, p=2, p1=2, weight_deficit=1) is None
    point = bjmm_terms(12, 4, 4, ell=4, p=2, p1=2, weight_deficit=1)
    assert point is not None
    errors = [set(support) for support in combinations(range(12), 4)]
    matching = [error for error in errors
                if len(error & set(range(4))) == 2
                and len(error & set(range(4, 8))) == 1]
    assert point["log2_probability"] == pytest.approx(log2(len(matching) / len(errors)))

    def count_representations(target, first_weight, second_weight):
        return sum(set(first) ^ set(second) == target
                   for first in combinations(range(4), first_weight)
                   for second in combinations(range(4), second_weight))

    representations = (count_representations({0, 1}, 2, 2)
                       * count_representations({0}, 2, 1))
    assert representations == 12
    assert point["log2_representations"] == pytest.approx(log2(representations))
    assert point["parameters"]["l1"] == 4
    assert point["details"]["base_weights"] == [2, 2, 2, 1]
    assert point["details"]["outside_weight"] == 3


@pytest.mark.parametrize("targets,solutions", [(1, 0), (3, 0), (20, 0), (3, 2)])
def test_fixed_prange_cost_counts_shared_elimination_and_extra_syndromes(targets, solutions):
    from codebased_estimator.classical_doom import evaluate_parameters

    point = evaluate_parameters(20, 10, 3, "Prange", targets=targets,
                                log2_solutions=solutions, r=0)
    probability = min(1, targets * 2**solutions * comb(10, 3) / comb(20, 3))
    work = 20 * 10**2 + (targets - 1) * 10**2
    memory = 20 * 11 + (targets - 1) * 10
    assert point.time_log2 == pytest.approx(log2(work / probability))
    assert point.memory_log2 == pytest.approx(log2(memory))
    assert point.details["log2_success_probability"] == pytest.approx(log2(probability))


@pytest.mark.parametrize("algorithm,left,right", [("Stern", 10, 10), ("Dumer", 12, 12)])
def test_fixed_unequal_list_cost_matches_the_doom_success_and_merge_formula(algorithm, left, right):
    from codebased_estimator.classical_doom import evaluate_parameters

    n, k, w, ell, targets = 42, 21, 5, 4, 8
    point = evaluate_parameters(n, k, w, algorithm, targets=targets,
                                r=0, l=ell, p_left=2, p_right=1)
    a, b = comb(left, 2), comb(right, 1)
    tail = n-k if algorithm == "Stern" else n-k-ell
    numerator = comb(tail, w-3)*a*b
    probability = min(1, targets*numerator/comb(n, w))
    projections = (max(1, (comb(n-k, w-3)//comb(n-k-ell, w-3))
                       //max(1, targets*numerator//comb(n, w)))
                   if algorithm == "Stern" else 1)
    work = (n * (n-k)**2 + (targets-1) * (n-k)**2
            + n * projections * (a + targets*(b + a*b//2**ell)))
    memory = n * (n-k+1 + a + targets*b) + (targets-1) * (n-k)
    assert point.time_log2 == pytest.approx(log2(work / probability))
    assert point.memory_log2 == pytest.approx(log2(memory))
    assert point.details["half_lengths"] == [left, right]


@pytest.mark.parametrize("targets,active,work", [(9, 9, 2800 * 19 / 18),
                                                (10, 10, 2900), (64, 10, 2900)])
def test_optimizer_selects_the_integer_batch_at_success_saturation(targets, active, work):
    row, = classical_rows(("Prange",), n=20, k=10, w=3, targets=targets)
    assert row.status == "computed"
    assert row.parameters == {"r": 0, "targets_used": active}
    assert row.time_log2 == pytest.approx(log2(work))
    assert row.metadata["doom"]["strategy"] == "explicit_doom"


def test_memory_bound_can_select_a_smaller_target_batch_at_the_boundary():
    row, = classical_rows(("Prange",), n=20, k=10, w=3, targets=64,
                          memory_bound=log2(280))
    assert row.status == "computed"
    assert row.parameters == {"r": 0, "targets_used": 7}
    assert row.memory_log2 == pytest.approx(log2(280))
    assert row.time_log2 == pytest.approx(log2(2600 * 19 / 14))


@pytest.mark.parametrize("algorithm", ("Stern", "Dumer"))
def test_extra_targets_change_the_optimized_list_weight_distribution(algorithm):
    two, = classical_rows((algorithm,), targets=2)
    many, = classical_rows((algorithm,), targets=32)
    assert two.metadata["doom"]["strategy"] == many.metadata["doom"]["strategy"] == "explicit_doom"
    assert two.parameters["p_left"] == two.parameters["p_right"]
    assert many.parameters["p_left"] > many.parameters["p_right"]
    assert many.time_log2 < two.time_log2
    assert many.time_log2 != pytest.approx(two.time_log2 - log2(32 / 2) / 2)


def test_bjmm_optimizes_the_weight_deficit_of_the_target_dependent_leaf():
    two, = classical_rows(("BJMM",), targets=2)
    eight, = classical_rows(("BJMM",), targets=8)
    assert two.metadata["doom"]["strategy"] == eight.metadata["doom"]["strategy"] == "explicit_doom"
    assert two.parameters["weight_deficit"] == 0
    assert eight.parameters["weight_deficit"] > 0
    assert eight.time_log2 < two.time_log2


@pytest.mark.parametrize("algorithm,parameters", [
    ("Prange", {}),
    ("Stern", {"l": 4, "p_left": 2, "p_right": 1}),
    ("Dumer", {"l": 4, "p_left": 2, "p_right": 1}),
    ("BJMM", {"l": 4, "p": 2, "p1": 1, "weight_deficit": 1}),
])
def test_fixed_points_replay_and_respect_the_bit_memory_boundary(algorithm, parameters):
    from codebased_estimator.classical_doom import evaluate_parameters

    point = evaluate_parameters(40, 20, 4, algorithm, targets=8, r=0, **parameters)
    replay = evaluate_parameters(40, 20, 4, algorithm, targets=8,
                                 memory_bound_log2_bits=point.memory_log2,
                                 **point.parameters)
    assert replay == point
    assert evaluate_parameters(
        40, 20, 4, algorithm, targets=8,
        memory_bound_log2_bits=nextafter(point.memory_log2, -inf),
        **point.parameters,
    ) is None
    assert evaluate_parameters(40, 20, 4, algorithm, targets=7, **point.parameters) is None
