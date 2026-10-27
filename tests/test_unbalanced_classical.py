"""Classical block probabilities, CE replay, and QCSD/QCCF target routing."""

import builtins
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from importlib import import_module
from itertools import combinations
import json
from math import comb, isfinite, log2, nextafter

import pytest
from cryptographic_estimators.SDEstimator.sd_problem import SDProblem

from codebased_estimator import AttackInstance, Options, Problem, estimate
from codebased_estimator.backend import ClassicalModel, _install_ce_outer_probability
from codebased_estimator.classical_doom import evaluate_parameters
from codebased_estimator.unbalanced import BlockProfile, optimize_outer

doom_point = evaluate_parameters


def instance(*, n=40, k=20, weights=(0, 4), targets=1, permutations=(), solutions=0):
    return AttackInstance(
        "block test", "key_recovery",
        Problem("sd", {"n": n, "k": k, "w": sum(weights), "q": 2}, solutions),
        targets=targets, tags=("doom:qcsd",) if targets > 1 else (),
        block_profile=BlockProfile((n//2, n-n//2), weights, permutations),
    )


def classical_row(attack, name):
    return ClassicalModel().estimate_algorithm(name, attack, Options(
        classical_algorithms=(name,), quantum_algorithms=(),
    ))


@pytest.mark.parametrize("name,params,inside,split_count", [
    ("Prange", {}, 0, 1),
    ("Stern", {"l": 2, "p_left": 1, "p_right": 1}, 2, 9),
    ("Dumer", {"l": 2, "p_left": 1, "p_right": 1}, 2, 16),
    ("BJMM", {"l": 2, "p": 2, "p1": 1, "weight_deficit": 1}, 3, 24),
])
def test_local_probability_matches_enumerated_profile_support_and_conditional_split(name, params, inside, split_count):
    profile = BlockProfile((6, 6), (1, 3))
    tail = 6 if name == "Stern" else 6-params.get("l", 0)
    outer = optimize_outer(profile, tail, inside)
    # Independently enumerate support intersections at the selected allocation.
    allocation = outer.allocation
    assert allocation is not None
    tail_set = set(range(allocation[0])) | set(range(6, 6+allocation[1]))
    supports = [set(left) | set(right) for left in combinations(range(6), 1)
                for right in combinations(range(6, 12), 3)]
    probability = Fraction(sum(len(s-tail_set) == inside for s in supports), len(supports))
    probability *= Fraction(split_count, comb(12-tail, inside))
    point = evaluate_parameters(12, 6, 4, name, targets=1, r=0,
                                block_profile=profile, **params)
    assert point.details["log2_single_solution_probability"] == pytest.approx(log2(probability))


@pytest.mark.parametrize("name", ["Prange", "Dumer", "BJMM", "BJMMdw"])
def test_ce_optimization_uses_block_event_and_preserves_generic_candidate(name):
    attack = instance()
    baseline = classical_row(replace(attack, block_profile=None), name)
    result = classical_row(attack, name)
    assert result.status == "computed"
    assert result.time_log2 < baseline.time_log2
    details = result.metadata["unbalanced"]
    assert details["applied"] is True
    assert details["allocation"] == [0, 20]
    assert details["log2_permutations_after"] == pytest.approx(0)
    assert details["generic_baseline_time_log2"] == baseline.time_log2


def test_corrected_ce_search_can_change_inner_parameters():
    attack = instance(n=100, k=50, weights=(0, 10))
    generic = classical_row(replace(attack, block_profile=None), "Dumer")
    profile = classical_row(attack, "Dumer")
    assert generic.parameters["p"] > 0
    assert profile.parameters["p"] == 0
    assert profile.parameters != generic.parameters


def test_saturation_is_applied_after_block_probability_and_target_count():
    profile = BlockProfile((10, 10), (0, 3))
    point = evaluate_parameters(20, 10, 3, "Prange", targets=4, r=0,
                                log2_solutions=2, block_profile=profile)
    assert point.details["log2_single_solution_probability"] == pytest.approx(0)
    assert point.details["log2_success_probability"] == 0
    assert point.time_log2 == pytest.approx(point.details["log2_iteration_bit_cost"])
    assert point.time_log2 == pytest.approx(log2(20*100+3*100))


@pytest.mark.parametrize("name", ["BothMay"])
def test_permuted_target_classes_do_not_receive_free_independent_allocations(name):
    attack = instance(n=20, k=10, weights=(0, 3), targets=6,
                      permutations=((0, 1), (1, 0)))
    generic = classical_row(replace(attack, block_profile=None), name)
    result = classical_row(attack, name)
    assert result.time_log2 <= generic.time_log2
    details = result.metadata["unbalanced"]
    assert details["profile_preserving_targets"] == 3
    if details["strategy"] != "generic_full_orbit":
        assert result.metadata["doom"]["active_targets"] <= 3


@pytest.mark.parametrize("name", ["Prange", "Dumer", "BJMMdw"])
def test_qccf_permuted_codewords_compare_subgroup_with_generic_full_orbit(name):
    attack = instance(n=20, k=10, weights=(0, 3), targets=6,
                      permutations=((0, 1), (1, 0)))
    attack = replace(attack, problem=replace(attack.problem, kind="cfp", log2_solutions=None),
                     tags=("doom:qccf",))
    generic = classical_row(replace(attack, block_profile=None), name)
    result = classical_row(attack, name)
    assert result.time_log2 <= generic.time_log2
    details = result.metadata["unbalanced"]
    assert details["profile_preserving_targets"] == 3
    if details["strategy"] == "profile_preserving_codewords":
        assert result.metadata["effective_log2_solutions"] == log2(3)
        assert result.metadata["doom"]["active_codewords"] == 3
    else:
        assert result.metadata["effective_log2_solutions"] == log2(6)


PUBLIC_NAMES = (
    "Prange", "Stern", "Dumer", "BJMM", "BallCollision", "BothMay",
    "BJMMplus", "MayOzerov", "BJMMdw", "BJMMpdw",
)


DEPTH_NAMES = ("BJMMd2", "BJMMd3", "MayOzerovD2", "MayOzerovD3")


LEAF_NAMES = tuple(n for n in PUBLIC_NAMES if n not in ("BJMM", "MayOzerov")) + DEPTH_NAMES


def algorithm(name, *, n=20, k=10, w=6, solutions=0):
    classes = import_module("cryptographic_estimators.SDEstimator.SDAlgorithms")
    problem = SDProblem(n, k, w, nsolutions=solutions)
    if name in DEPTH_NAMES:
        family = "BJMM" if name.startswith("BJMM") else "MayOzerov"
        return getattr(getattr(classes, family)(problem), f"{family}_depth_{name[-1]}")
    return getattr(classes, name)(problem)


def binomial(n, k):
    return comb(n, k) if 0 <= k <= n else 0


def exact_best_probability(tail, inside, lengths=(10, 10), weights=(1, 5)):
    """Enumerate every two-block allocation using exact support counts."""
    n1, n2 = lengths
    w1, w2 = weights
    denominator = comb(n1, w1) * comb(n2, w2)
    best = Fraction(0)
    for r1 in range(max(0, tail-n2), min(tail, n1)+1):
        r2 = tail-r1
        count = sum(
            binomial(n1-r1, j) * binomial(r1, w1-j)
            * binomial(n2-r2, inside-j) * binomial(r2, w2-inside+j)
            for j in range(inside+1)
        )
        best = max(best, Fraction(count, denominator))
    return best


def event(name, parameters, *, n=20, k=10, constraints=None):
    p = parameters.get("p", 0)
    ell = parameters.get("l", 0)
    if name == "Prange":
        return n-k, 0
    if name == "Stern":
        return n-k, 2*p
    if name == "BallCollision":
        return n-k-ell, 2*(p+parameters["pl"])
    if name == "BothMay":
        return n-k-ell, 2*p+parameters["w2"]
    if name in ("BJMMdw", "BJMMpdw"):
        return n-k-sum(constraints), 2*(p+parameters["w2"]+parameters.get("w1", 0))
    return n-k-ell, 2*p


@pytest.mark.parametrize("name", tuple(n for n in LEAF_NAMES if n not in ("BJMMdw", "BJMMpdw")))
@pytest.mark.parametrize("solutions", (0, 6))
def test_fixed_ce_cost_replaces_only_repetitions_using_exact_probability(name, solutions):
    # Choose nontrivial finite parameters under one solution; independently
    # exercise both unsaturated and saturated multiple-solution repetition.
    original = algorithm(name)
    original.time_complexity()
    parameters = original.optimal_parameters().copy()
    raw_verbose = {}
    original._time_and_memory_complexity(parameters, raw_verbose)
    current = algorithm(name, solutions=solutions)
    old_verbose = {}
    # CE's depth-three verbose path returns a dictionary, unlike its numeric
    # path and the other algorithms. Read each contract separately.
    current._time_and_memory_complexity(parameters, old_verbose)
    old_time, old_memory = current._time_and_memory_complexity(parameters)
    tail, inside = event(name, parameters)
    uniform = Fraction(comb(20-tail, inside)*comb(tail, 6-inside), comb(20, 6))
    gain = log2(exact_best_probability(tail, inside)/uniform)
    if name == "MayOzerovD3":
        # Upstream overwrites its permutations entry with representation
        # counts in this one verbose implementation. Recover the repetition
        # price by saturating solutions while leaving its inner costs fixed.
        iteration = algorithm(name, solutions=128)._time_and_memory_complexity(parameters)[0]
        raw_repetitions = original._time_and_memory_complexity(parameters)[0]-iteration
        old_repetitions = old_time-iteration
    else:
        raw_repetitions = raw_verbose["permutations"]
        old_repetitions = old_verbose["permutations"]
    expected_repetitions = max(0, raw_repetitions-solutions-gain)

    details = _install_ce_outer_probability(current, BlockProfile((10, 10), (1, 5)))
    actual_time, actual_memory = current._time_and_memory_complexity(parameters)
    actual_details = details(parameters)
    assert actual_time == pytest.approx(old_time-old_repetitions+expected_repetitions)
    assert actual_memory == pytest.approx(old_memory)
    assert actual_details["log2_permutations_after"] == pytest.approx(expected_repetitions)


@pytest.mark.parametrize("name", PUBLIC_NAMES + DEPTH_NAMES)
@pytest.mark.parametrize("profile", [BlockProfile((20,), (6,)), BlockProfile((10, 10), (1, 5))])
def test_optimized_parameters_replay_after_verbose_and_in_fresh_instance(name, profile):
    optimized = algorithm(name)
    details = _install_ce_outer_probability(optimized, profile)
    expected = optimized.time_complexity(), optimized.memory_complexity()
    if len(profile.lengths) == 1:
        original = algorithm(name)
        assert expected == pytest.approx((original.time_complexity(), original.memory_complexity()))
    parameters = deepcopy(optimized.optimal_parameters())
    state = deepcopy(optimized._optimal_parameters)
    verbose = optimized._get_verbose_information()
    assert optimized._optimal_parameters == state
    assert verbose["permutations"] == pytest.approx(details(parameters)["log2_permutations_after"])
    # Public CE methods include bit conversion, whereas its cost callback
    # returns basic-operation units. Replay through the same public methods.
    assert (optimized.time_complexity(**parameters), optimized.memory_complexity(**parameters)) == pytest.approx(expected)
    fresh = algorithm(name)
    _install_ce_outer_probability(fresh, profile)
    # A parent {r, depth} call constrains only depth and reruns the child
    # search; it is not a fully specified point. Verify the reported child's
    # complete parameters separately on a fresh leaf instance.
    assert (fresh.time_complexity(**parameters), fresh.memory_complexity(**parameters)) == pytest.approx(expected)
    if name in ("BJMM", "MayOzerov"):
        information = details(parameters)
        assert information["depth"] == parameters["depth"]
        child = getattr(algorithm(name), f'{name}_depth_{information["depth"]}')
        _install_ce_outer_probability(child, profile)
        child_parameters = information["child_parameters"]
        assert {"p", "l", "p1", "r"} <= child_parameters.keys()
        assert (child.time_complexity(**child_parameters), child.memory_complexity(**child_parameters)) == pytest.approx(expected)


@pytest.mark.parametrize("name", ("Dumer", "BJMM", "BJMMdw", "BJMMpdw"))
def test_pruning_keeps_same_optimum_as_unpruned_ce_search(name):
    costs = []
    for prune in (True, False):
        current = algorithm(name, n=40, k=20, w=6)
        _install_ce_outer_probability(current, BlockProfile((20, 20), (1, 5)))
        if not prune:
            current._is_early_abort_possible = lambda *_: False
            if name in ("BJMM", "MayOzerov"):
                for depth in (2, 3):
                    getattr(current, f"{name}_depth_{depth}")._is_early_abort_possible = lambda *_: False
        costs.append(current.time_complexity())
    assert costs[0] == pytest.approx(costs[1])


def disjoint_candidates(original, parameters, profile, monkeypatch):
    """Enumerate installed CE hidden pairs, then apply exact block probabilities."""
    n, k, w = original.problem.get_parameters()
    name = type(original).__name__
    module = import_module(type(original).__module__)
    candidates = []
    for l1 in range(n-k):
        for l2 in range(n-k):
            selections = iter((l1, l2))

            def one_candidate(*args):
                selected = next(selections)
                return (selected,) if selected in builtins.range(*args) else ()

            with monkeypatch.context() as patch:
                patch.setattr(module, "range", one_candidate, raising=False)
                verbose = {}
                time, memory = original._time_and_memory_complexity(parameters, verbose)
            if not isfinite(time):
                continue
            tail, inside = event(name, parameters, n=n, k=k, constraints=verbose["constraints"])
            uniform = Fraction(comb(n-tail, inside)*comb(tail, w-inside), comb(n, w))
            gain = log2(exact_best_probability(tail, inside, profile.lengths, profile.weights)/uniform)
            corrected = time-verbose["permutations"]+max(0, verbose["permutations"]-gain)
            candidates.append((corrected, memory, l1, l2))
    return candidates


@pytest.mark.parametrize("name", ("BJMMdw", "BJMMpdw"))
def test_disjoint_hidden_minimum_matches_each_upstream_candidate_corrected_before_min(name, monkeypatch):
    original = algorithm(name)
    original.time_complexity()
    parameters = original.optimal_parameters().copy()
    profile = BlockProfile((10, 10), (1, 5))
    expected = min(disjoint_candidates(original, parameters, profile, monkeypatch))
    current = algorithm(name)
    details = _install_ce_outer_probability(current, profile)
    assert current._time_and_memory_complexity(parameters) == pytest.approx(expected[:2])
    assert details(parameters)["hidden_constraints"] == {"l1": expected[2], "l2": expected[3]}


def test_profile_hooks_do_not_modify_other_instances_or_upstream_class():
    baseline = algorithm("Dumer")
    before_method = type(baseline)._time_and_memory_complexity
    expected = baseline.time_complexity(), baseline.memory_complexity()
    corrected = algorithm("Dumer")
    _install_ce_outer_probability(corrected, BlockProfile((10, 10), (0, 6)))
    assert corrected.time_complexity() < expected[0]
    fresh = algorithm("Dumer")
    assert type(fresh)._time_and_memory_complexity is before_method
    assert (fresh.time_complexity(), fresh.memory_complexity()) == pytest.approx(expected)
    assert (baseline.time_complexity(), baseline.memory_complexity()) == pytest.approx(expected)


@pytest.mark.parametrize("name,n,k,w,parameters,bit_bound", [
    ("BJMMdw", 20, 10, 6,
     {"r": 0, "p": 0, "p1": 1, "w1": 0, "w11": 0, "w2": 0}, 9.461152823997605),
    ("BJMMpdw", 40, 20, 8,
     {"r": 0, "p": 0, "p1": 1, "w2": 0}, 11.224195296384977),
])
@pytest.mark.parametrize("bit_complexities", [0, 1])
def test_disjoint_hidden_constraints_filter_memory_before_minimizing(
    name, n, k, w, parameters, bit_bound, bit_complexities, monkeypatch,
):
    cls = getattr(import_module("cryptographic_estimators.SDEstimator.SDAlgorithms"), name)
    original = cls(SDProblem(n, k, w, nsolutions=0), bit_complexities=bit_complexities)
    profile = BlockProfile((n//2, n-n//2), (0, w))
    bound = bit_bound if bit_complexities else bit_bound-log2(n)
    candidates = disjoint_candidates(original, parameters, profile, monkeypatch)
    converted = lambda memory: memory+(log2(n) if bit_complexities else 0)
    assert converted(min(candidates)[1]) > bound
    expected = min(row for row in candidates if converted(row[1]) < bound)
    current = cls(SDProblem(n, k, w, nsolutions=0, memory_bound=bound),
                  bit_complexities=bit_complexities)
    details = _install_ce_outer_probability(current, profile)
    assert current._time_and_memory_complexity(parameters) == pytest.approx(expected[:2])
    assert details(parameters)["hidden_constraints"] == {"l1": expected[2], "l2": expected[3]}


def test_public_disjoint_search_keeps_the_feasible_hidden_alternative(monkeypatch):
    profile = BlockProfile((20, 20), (4, 4))
    bound = log2(40*20)+1.5
    parameters = {"r": 0, "p": 2, "p1": 1, "w1": 0, "w11": 0, "w2": 0}
    original = algorithm("BJMMdw", n=40, k=20, w=8)
    candidates = disjoint_candidates(original, parameters, profile, monkeypatch)
    expected = min(time+log2(40) for time, memory, _, _ in candidates
                   if memory+log2(40) < bound)
    result = row(instance(weights=(4, 4)), "BJMMdw", bound)
    assert result.status == "computed" and result.memory_log2 <= bound
    assert result.time_log2 <= expected+1e-12
    assert result.time_log2 == pytest.approx(18.7699473046922)
    assert result.metadata["unbalanced"]["hidden_constraints"] == {"l1": 2, "l2": 0}


def attack(*, weights=(1, 2), targets=20, solutions=0, codewords=False, profile=None):
    return AttackInstance(
        "target consistency", "key_recovery",
        Problem("cfp" if codewords else "sd",
                {"n": 20, "k": 10, "w": sum(weights), "q": 2},
                None if codewords else solutions),
        targets=targets, tags=("doom:qccf" if codewords else "doom:qcsd",),
        block_profile=profile or BlockProfile((10, 10), weights, ((0, 1), (1, 0))),
    )


def row(instance, algorithm, bound=None):
    report = estimate(instance, options=Options(
        classical_algorithms=(algorithm,), quantum_algorithms=(),
        memory_bound_log2_bits=bound,
    ))
    json.dumps(report.to_dict(), allow_nan=False)
    result, = report.results
    return result


@pytest.mark.parametrize("algorithm", ["Prange", "Stern", "Dumer", "BJMM"])
@pytest.mark.parametrize("targets,solutions", [(6, 0), (20, 1.5), (20, None)])
def test_public_doom_selected_strategy_replays_cost_probability_and_solutions(algorithm, targets, solutions):
    instance = attack(targets=targets, solutions=solutions)
    result = row(instance, algorithm)
    assert result.status == "computed"
    details, doom = result.metadata["unbalanced"], result.metadata["doom"]
    expected_solutions = 0 if solutions is None else solutions
    assert result.metadata["effective_log2_solutions"] == expected_solutions
    assert doom["available_targets"] == targets
    active = doom["active_targets"]
    assert 1 <= active <= targets
    if details["strategy"] != "generic_full_orbit":
        assert active <= instance.block_profile.preserving_targets(targets)

    if "targets_used" in result.parameters:
        profiled = details["strategy"] == "profile_preserving_batch"
        replay = doom_point(
            20, 10, 3, algorithm, targets=active,
            log2_solutions=expected_solutions,
            block_profile=instance.block_profile if profiled else None,
            **result.parameters,
        )
        assert replay is not None
        assert replay.time_log2 == pytest.approx(result.time_log2, abs=1e-12)
        assert replay.memory_log2 == pytest.approx(result.memory_log2, abs=1e-12)
        assert replay.details == result.metadata["cost_breakdown"]
        # The target multiplicity enters exactly once, after the block event.
        expected_success = min(0, replay.details["log2_single_solution_probability"]
                               + expected_solutions + log2(active))
        assert replay.details["log2_success_probability"] == pytest.approx(expected_success)
    elif doom["model"] == "sqrt_targets_approximation":
        from cryptographic_estimators.SDEstimator import SDProblem
        from cryptographic_estimators.SDEstimator.SDAlgorithms.bjmm import BJMMd3
        from codebased_estimator.backend import _install_ce_outer_probability

        assert algorithm == "BJMM" and result.parameters["depth"] == 3
        child = BJMMd3(SDProblem(20, 10, 3, nsolutions=expected_solutions),
                        bit_complexities=1, complexity_type=0, memory_access=0)
        if details["strategy"] != "generic_full_orbit":
            _install_ce_outer_probability(child, instance.block_profile)
        parameters = {key: value for key, value in result.parameters.items() if key != "depth"}
        assert result.time_log2 == pytest.approx(max(0, child.time_complexity(**parameters)
                                                    -log2(active)/2), abs=1e-12)
        assert result.memory_log2 == pytest.approx(child.memory_complexity(**parameters), abs=1e-12)
        assert doom["log2_proxy_speedup"] == log2(active)/2
    else:
        single = row(replace(instance, tags=(), targets=1,
                             block_profile=(None if details["strategy"] == "generic_full_orbit"
                                            else instance.block_profile)), algorithm)
        assert active == 1
        assert result.time_log2 == single.time_log2
        assert result.memory_log2 == single.memory_log2
        assert result.parameters == single.parameters


def test_report_distinguishes_selected_profile_search_from_generic_search(monkeypatch):
    import codebased_estimator.classical_doom as doom

    original = doom._optimize

    def identified_search(*args, **kwargs):
        point, search = original(*args, **kwargs)
        profile = args[8] if len(args) > 8 else kwargs.get("block_profile")
        return point, {**search, "test_probability_model": "profile" if profile is not None else "uniform"}

    monkeypatch.setattr(doom, "_optimize", identified_search)
    result = row(attack(targets=20), "Dumer")
    assert result.metadata["doom"]["strategy"] == "profile_preserving_batch"
    assert result.metadata["doom"]["search"] == result.metadata["unbalanced"]["search"]
    assert result.metadata["doom"]["search"]["method"] == "finite enumeration"
    assert result.metadata["doom"]["search"]["test_probability_model"] == "profile"
    assert result.metadata["doom"]["generic_full_orbit_search"]["test_probability_model"] == "uniform"
    assert result.metadata["gaussian_elimination_search"] == (
        "all nondominated CE block widths under the DOOM memory budget"
    )


def test_report_identifies_selected_profile_ce_single_target_search():
    result = row(attack(weights=(0, 3), targets=6), "Prange")
    assert result.metadata["doom"]["strategy"] == "profile_single_target"
    assert result.metadata["doom"]["search"]["method"] == "single-target block-aware CE optimization"
    assert result.metadata["doom"]["active_targets"] == 1


@pytest.mark.parametrize("algorithm", ["Prange", "Stern", "Dumer", "BJMM"])
@pytest.mark.parametrize("profile", [BlockProfile((20,), (3,)),
                                    BlockProfile((10, 10), (1, 2))])
def test_one_target_doom_preserves_the_same_block_aware_ce_candidate(algorithm, profile):
    instance = attack(targets=1, profile=profile)
    tagged = row(instance, algorithm)
    single = row(replace(instance, tags=()), algorithm)
    assert tagged.status == single.status == "computed"
    assert tagged.time_log2 == single.time_log2
    assert tagged.memory_log2 == single.memory_log2
    assert tagged.parameters == single.parameters
    assert tagged.metadata["doom"]["active_targets"] == 1


@pytest.mark.parametrize("targets,expected_strategy", [(6, "generic_full_orbit"),
                                                        (20, "profile_preserving_batch")])
def test_prange_public_route_matches_independent_full_orbit_and_subgroup_minimum(targets, expected_strategy):
    result = row(attack(targets=targets), "Prange")
    choose = lambda length, weight: comb(length, weight) if 0 <= weight <= length else 0
    profile_probability = max(
        choose(first, 1)*choose(10-first, 2)/(comb(10, 1)*comb(10, 2))
        for first in range(11)
    )
    uniform_probability = comb(10, 3)/comb(20, 3)
    # For this small matrix r=0 is cheapest. Enumerate every integer batch,
    # including the profile subgroup and every generic full-orbit candidate.
    expected = min(
        log2((2000+(batch-1)*100)/min(1, batch*probability))
        for probability, maximum in [(profile_probability, targets//2),
                                     (uniform_probability, targets)]
        for batch in range(1, maximum+1)
    )
    assert result.metadata["unbalanced"]["strategy"] == expected_strategy
    assert result.time_log2 == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("algorithm", ["Prange", "Stern", "Dumer", "BJMM"])
def test_profile_doom_replay_and_public_search_enforce_memory_boundary(algorithm):
    instance = attack()
    result = row(instance, algorithm)
    assert result.metadata["unbalanced"]["strategy"] == "profile_preserving_batch"
    kwargs = dict(targets=result.metadata["doom"]["active_targets"],
                  block_profile=instance.block_profile, **result.parameters)
    exact = doom_point(20, 10, 3, algorithm,
                       memory_bound_log2_bits=result.memory_log2, **kwargs)
    assert exact is not None
    bound = nextafter(result.memory_log2, 0)
    assert doom_point(20, 10, 3, algorithm, memory_bound_log2_bits=bound, **kwargs) is None
    limited = row(instance, algorithm, bound)
    assert limited.status != "computed" or limited.memory_log2 <= bound


@pytest.mark.parametrize("algorithm", ["Prange", "Dumer"])
def test_profile_default_solution_count_is_preserved_through_target_routing(algorithm):
    instance = attack(weights=(0, 8), targets=6, solutions=None)
    # Ambient SD predicts multiple solutions, while the restricted support
    # set has expectation below one: both strategies must use the latter.
    assert log2(comb(20, 8))-10 > 0
    assert log2(comb(10, 8))-10 < 0
    implicit = row(instance, algorithm)
    explicit = row(replace(instance, problem=replace(instance.problem, log2_solutions=0)), algorithm)
    assert implicit.status == explicit.status == "computed"
    assert implicit.time_log2 == explicit.time_log2
    assert implicit.parameters == explicit.parameters
    assert implicit.metadata["effective_log2_solutions"] == 0
