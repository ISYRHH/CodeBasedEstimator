"""Check real upstream costs and the demo's scientific interpretation boundaries."""

import importlib
import json
import subprocess
import sys
from math import comb, log2
from types import SimpleNamespace

import pytest

from codebased_estimator import AttackInstance, BlockProfile, Estimate, Options, Problem, estimate


def instance(problem, **kwargs):
    return AttackInstance("test route", "msg_recovery", problem, **kwargs)


@pytest.fixture
def quantum_cost(monkeypatch):
    cost = SimpleNamespace(time_log2=19.5, parameters={"ell": 0, "p": 0},
                           details={"G_log2": 8}, search={"method": "test fixture"})
    monkeypatch.setattr("codebased_estimator.quantum.optimize", lambda *args: cost)
    return cost


def upstream_algorithm(family, algorithm, parameters, **problem_options):
    module = importlib.import_module(f"cryptographic_estimators.{family}Estimator")
    problem_class = getattr(module, f"{family}Problem")
    return getattr(module, algorithm)(
        problem_class(**parameters, **problem_options),
        bit_complexities=1, complexity_type=0, memory_access=0,
    )


@pytest.mark.parametrize("kind,parameters,family,algorithms", [
    ("sd", {"n": 40, "k": 20, "w": 4}, "SD", ("Prange", "Stern")),
    ("sd", {"n": 40, "k": 20, "w": 4, "q": 3}, "SDFq",
     ("Prange", "Stern", "LeeBrickell")),
    ("rank_sd", {"q": 2, "m": 8, "n": 8, "k": 4, "r": 2}, "RankSD",
     ("BasisEnumeration", "GRS", "OJ2", "SupportMinors")),
])
def test_costs_and_parameters_match_fresh_upstream_algorithms(kind, parameters, family, algorithms):
    problem = Problem(kind, parameters, None if kind == "rank_sd" else 0)
    report = estimate(instance(problem), options=Options(
        classical_algorithms=algorithms, quantum_algorithms=()))
    assert [row.algorithm for row in report.results] == list(algorithms)
    for row in report.results:
        problem_options = {} if kind == "rank_sd" else {"nsolutions": 0}
        if family == "SDFq":
            problem_options["is_syndrome_zero"] = False
        direct = upstream_algorithm(family, row.algorithm, parameters, **problem_options)
        assert row.status == "computed"
        assert row.time_unit == "bit_operations"
        assert row.memory_unit == "bits"
        assert row.time_log2 == pytest.approx(direct.time_complexity(), abs=1e-10)
        assert row.memory_log2 == pytest.approx(direct.memory_complexity(), abs=1e-10)
        assert row.parameters == direct.get_optimal_parameters_dict()
    # In particular RankSD's changing base/extension-field convention must not
    # contaminate another algorithm's result or create invalid numeric JSON.
    json.dumps(report.to_dict(), allow_nan=False)


@pytest.mark.parametrize("q,w,family", [(2, 10, "SD"), (3, 12, "SDFq")])
def test_none_preserves_expected_solutions_and_zero_means_one_solution(q, w, family):
    parameters = {"n": 40, "k": 20, "w": w, "q": q}
    results = []
    for solutions in (None, 0):
        row = estimate(instance(Problem("sd", parameters, solutions)),
                       options=Options(classical_algorithms=("Prange",),
                                       quantum_algorithms=())).results[0]
        direct_parameters = dict(parameters)
        direct_options = {} if solutions is None else {"nsolutions": solutions}
        if q == 2:
            direct_parameters.pop("q")
        else:
            direct_options["is_syndrome_zero"] = False
        direct = upstream_algorithm(family, "Prange", direct_parameters, **direct_options)
        assert row.time_log2 == pytest.approx(direct.time_complexity())
        assert row.metadata["effective_log2_solutions"] == pytest.approx(direct.problem.nsolutions)
        results.append(row)
    expected = max(0, log2(comb(40, w)) + w * log2(q - 1) - 20 * log2(q))
    assert expected > 0  # This instance actually distinguishes the two inputs.
    assert results[0].metadata["effective_log2_solutions"] == pytest.approx(expected)
    assert results[1].metadata["effective_log2_solutions"] == 0
    assert results[0].time_log2 < results[1].time_log2


def test_qary_generic_decoding_uses_nonzero_syndrome_model():
    parameters = {"n": 40, "k": 20, "w": 4, "q": 3}
    row = estimate(instance(Problem("sd", parameters, 0)),
                   options=Options(classical_algorithms=("LeeBrickell",),
                                   quantum_algorithms=())).results[0]
    nonzero = upstream_algorithm("SDFq", "LeeBrickell", parameters,
                                 nsolutions=0, is_syndrome_zero=False)
    zero = upstream_algorithm("SDFq", "LeeBrickell", parameters,
                              nsolutions=0, is_syndrome_zero=True)
    assert row.metadata["is_syndrome_zero"] is False
    assert row.time_log2 == pytest.approx(nonzero.time_complexity())
    assert row.time_log2 != pytest.approx(zero.time_complexity())


@pytest.mark.parametrize("problem,algorithm", [
    (Problem("sd", {"n": 40, "k": 20, "w": 4}, 0), "Prange"),
    (Problem("sd", {"n": 40, "k": 20, "w": 4, "q": 3}, 0), "LeeBrickell"),
    (Problem("rank_sd", {"q": 2, "m": 8, "n": 8, "k": 4, "r": 2}), "GRS"),
])
def test_zero_memory_bound_never_reports_a_feasible_estimate(problem, algorithm):
    report = estimate(instance(problem), options=Options(
        classical_algorithms=(algorithm,), quantum_algorithms=(), memory_bound_log2_bits=0))
    assert report.results
    assert all(row.status in ("infeasible", "not_applicable") for row in report.results)
    assert all(row.reason for row in report.results)
    json.dumps(report.to_dict(), allow_nan=False)


def test_classical_and_requested_quantum_algorithms_share_one_report(quantum_cost):
    options = Options(classical_algorithms=("Prange", "Stern"),
                      quantum_algorithms=("QPrange", "QSS", "QMMT+"))
    report = estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 4}, 0)), options=options)
    classical = [row for row in report.results if row.model == "classical"]
    quantum = [row for row in report.results if row.model == "quantum"]
    assert [row.algorithm for row in classical] == ["Prange", "Stern"]
    assert all(row.status == "computed" for row in classical)
    assert [row.algorithm for row in quantum] == ["QPrange", "QSS", "QMMT+"]
    assert set(report.backends) == {"classical", "quantum"}
    assert quantum[0].status == "computed"
    assert quantum[0].time_log2 is not None
    for row in quantum[1:]:
        assert row.status == "computed"
        assert row.time_log2 == quantum_cost.time_log2 and row.memory_log2 is None
        assert row.time_unit == "quantum_bit_operations"
        assert row.memory_unit == "not_estimated"
        assert row.metadata["resource_scope"] == "time_only"
        assert row.metadata["cost_breakdown"] == quantum_cost.details
        assert row.metadata["search"] == quantum_cost.search
        assert row.reason
    assert report.backends["quantum"]["implemented_algorithms"] == ["QPrange", "QSS", "QMMT+"]
    json.dumps(report.to_dict(), allow_nan=False)


def test_ce_list_profile_and_zero_setup_outputs_survive_public_json(monkeypatch):
    from codebased_estimator.quantum_costs import COST_MODEL, evaluate_parameters

    point = evaluate_parameters(24, 12, 4, "QSS", ell=4, p=4, u=2, a=1)
    monkeypatch.setattr("codebased_estimator.quantum.optimize", lambda *args: point)
    report = estimate(instance(Problem("sd", {"n": 24, "k": 12, "w": 4}, 0)),
                      options=Options(classical_algorithms=("Prange",), quantum_algorithms=("QSS",)))
    classical, quantum = report.results
    upstream = upstream_algorithm("SD", "Prange", {"n": 24, "k": 12, "w": 4}, nsolutions=0)
    assert classical.time_log2 == pytest.approx(upstream.time_complexity())
    assert quantum.metadata["cost_model"] == COST_MODEL == "ka17-ce-ordered-average-v2"
    assert quantum.metadata["list_cost_profile"]["name"] == "ce-2.1.1-ordered-v1"
    serialized = json.loads(json.dumps(report.to_dict(), allow_nan=False))
    breakdown = serialized["results"][1]["metadata"]["cost_breakdown"]
    assert breakdown["log2_setup_output_count"] is None
    assert breakdown["log2_setup_output_index"] is None
    assert breakdown["log2_D2"] == -1  # Mean dynamic load remains positive.


@pytest.mark.parametrize("classical,quantum,expected", [
    ((), ("QSS",), [("quantum", "QSS")]),
    (("Prange",), (), [("classical", "Prange")]),
])
def test_empty_algorithm_tuples_disable_each_family_independently(classical, quantum, expected, quantum_cost):
    report = estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 4}, 0)),
                      options=Options(classical_algorithms=classical, quantum_algorithms=quantum))
    assert [(row.model, row.algorithm) for row in report.results] == expected


def test_estimate_requires_at_least_one_enabled_family():
    with pytest.raises(ValueError):
        estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 4})),
                 options=Options(classical_algorithms=(), quantum_algorithms=()))


def test_defaults_include_upstream_classical_mage_and_registered_quantum_algorithms(quantum_cost):
    from codebased_estimator.quantum import QuantumModel

    report = estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 4}, 0)))
    module = importlib.import_module("cryptographic_estimators.SDEstimator")
    direct = module.SDEstimator(n=40, k=20, w=4, nsolutions=0)
    classical = [row for row in report.results if row.model == "classical"]
    quantum = [row for row in report.results if row.model == "quantum"]
    assert {row.algorithm for row in classical} == {
        type(algorithm).__name__ for algorithm in direct.algorithms()
    } | {"MAGE-Stern"}
    assert {"Prange", "Stern", "BJMM", "BJMMplus", "BothMay", "MayOzerov"} <= {
        row.algorithm for row in classical
    }
    assert all(row.status == "computed" for row in classical)
    upstream = {type(algorithm).__name__: algorithm for algorithm in direct.algorithms()}
    for row in classical:
        if row.algorithm in upstream:
            algorithm = upstream[row.algorithm]
            assert row.time_log2 == pytest.approx(algorithm.time_complexity(), abs=1e-10)
            assert row.memory_log2 == pytest.approx(algorithm.memory_complexity(), abs=1e-10)
            assert row.parameters == algorithm.get_optimal_parameters_dict()
    assert tuple(row.algorithm for row in quantum) == QuantumModel.algorithms
    assert {row.algorithm for row in quantum} == {"QPrange", "QSS", "QMMT+"}
    assert report.options.classical_algorithms is None
    assert report.options.quantum_algorithms == QuantumModel.algorithms
    assert set(report.backends) == {"classical", "quantum"}
    assert quantum[0].status == "computed" and quantum[0].time_log2 is not None
    assert all(row.status == "computed" and row.time_log2 == quantum_cost.time_log2
               and row.memory_log2 is None and row.reason for row in quantum[1:])
    minimum = min(row.time_log2 for row in classical)
    assert report.conclusions["classical"].status == "computed"
    assert report.conclusions["classical"].best == tuple(
        row for row in classical if row.time_log2 == minimum
    )
    assert report.conclusions["quantum"].status == "computed"
    quantum_minimum = min(row.time_log2 for row in quantum)
    assert report.conclusions["quantum"].best == tuple(
        row for row in quantum if row.time_log2 == quantum_minimum)
    json.dumps(report.to_dict(), allow_nan=False)


@pytest.mark.parametrize("doom_tag", ["doom:qccf", "doom:qcsd"])
@pytest.mark.parametrize("targets", [1, 32])
def test_doom_is_instance_context_and_preserves_each_requested_algorithm(doom_tag, targets):
    kind, solutions = ("cfp", None) if doom_tag == "doom:qccf" else ("sd", 2)
    attack = instance(Problem(kind, {"n": 40, "k": 20, "w": 4}, solutions),
                      tags=(doom_tag,), targets=targets)
    report = estimate(attack, options=Options(
        classical_algorithms=("Prange", "Stern"), quantum_algorithms=("QPrange", "QMMT+")))
    assert [(row.model, row.algorithm) for row in report.results] == [
        ("classical", "Prange"), ("classical", "Stern"),
        ("quantum", "QPrange"), ("quantum", "QMMT+"),
    ]
    assert report.instance.tags == (doom_tag,)
    assert report.instance.targets == targets
    assert report.instance.problem.log2_solutions == solutions
    for row in report.results:
        if row.model == "classical":
            assert row.status == "computed"
            assert row.time_log2 is not None and row.memory_log2 is not None
            assert row.metadata["doom"]["available_targets"] == targets
            continue
        if row.algorithm == "QMMT+":
            assert row.status == "computed"
            assert row.time_log2 is not None and row.memory_log2 is None
            assert row.metadata["doom"]["available_targets"] == targets
            if doom_tag == "doom:qcsd":
                assert row.metadata["doom"]["model"] == "single_target_fallback"
                assert row.metadata["effective_targets"] == 1
                assert row.metadata["effective_log2_solutions"] == solutions
        elif doom_tag == "doom:qcsd":
            assert row.status == "computed"
            assert row.time_log2 is not None and row.memory_log2 is None
            assert row.metadata["effective_targets"] == 1
        else:
            assert row.status == "not_implemented"
            assert row.time_log2 is None and row.memory_log2 is None
        assert row.reason


@pytest.mark.parametrize("doom_tag", ["doom:qccf", "doom:qcsd"])
def test_builtin_algorithm_hooks_receive_original_target_context(doom_tag):
    from codebased_estimator.backend import ClassicalModel
    from codebased_estimator.quantum import QuantumModel

    received = []

    class ClassicalProbe(ClassicalModel):
        def estimate_algorithm(self, name, attack, options):
            received.append((self.name, name, attack.tags, attack.targets,
                             attack.problem.log2_solutions, options.classical_algorithms))
            return super().estimate_algorithm(name, attack, options)

    class QuantumProbe(QuantumModel):
        def estimate_algorithm(self, name, attack, options):
            received.append((self.name, name, attack.tags, attack.targets,
                             attack.problem.log2_solutions, options.quantum_algorithms))
            return super().estimate_algorithm(name, attack, options)

    kind, solutions = ("cfp", None) if doom_tag == "doom:qccf" else ("sd", 2)
    attack = instance(Problem(kind, {"n": 40, "k": 20, "w": 4}, solutions),
                      tags=(doom_tag,), targets=32)
    estimate(attack, classical_model=ClassicalProbe(), quantum_model=QuantumProbe(),
             options=Options(classical_algorithms=("Prange", "Stern"),
                             quantum_algorithms=("QPrange", "QSS")))
    assert received == [
        ("classical", "Prange", (doom_tag,), 32, solutions, ("Prange", "Stern")),
        ("classical", "Stern", (doom_tag,), 32, solutions, ("Prange", "Stern")),
        ("quantum", "QPrange", (doom_tag,), 32, solutions, ("QPrange", "QSS")),
        ("quantum", "QSS", (doom_tag,), 32, solutions, ("QPrange", "QSS")),
    ]


def test_conflicting_doom_problem_types_are_rejected():
    with pytest.raises(ValueError):
        instance(Problem("sd", {"n": 40, "k": 20, "w": 4}),
                 tags=("doom:qccf", "doom:qcsd"))


@pytest.mark.parametrize("kind,solutions,tags", [
    ("sd", None, ("doom",)),
    ("sd", None, ("doom:unknown",)),
    ("sd", None, ("doom:qcsd", "doom:qcsd")),
    ("sd", None, ("doom:qccf",)),
    ("cfp", None, ("doom:qcsd",)),
    ("cfp", 0, ("doom:qccf",)),
])
def test_invalid_doom_context_is_rejected(kind, solutions, tags):
    with pytest.raises(ValueError):
        instance(Problem(kind, {"n": 40, "k": 20, "w": 4}, solutions), tags=tags)


def test_doom_is_not_a_separate_estimate_mode():
    with pytest.raises(TypeError):
        estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 4})), model="doom")


@pytest.mark.parametrize("problem,instance_options", [
    (Problem("sd", {"n": 40, "k": 20, "w": 4}, 0), {"targets": 8}),
    (Problem("sd", {"n": 40, "k": 20, "w": 4}, 0), {"structure": ("block weights",)}),
    (Problem("cfp", {"n": 40}), {}),
    (Problem("rsl", {"q": 2, "m": 8}), {}),
    (Problem("low_weight_codeword", {"n": 40, "k": 20, "w": 4}), {}),
])
def test_generic_backend_does_not_silently_discard_problem_structure(problem, instance_options):
    report = estimate(instance(problem, **instance_options),
                      options=Options(classical_algorithms=("Prange", "Stern"),
                                      quantum_algorithms=()))
    assert [row.algorithm for row in report.results] == ["Prange", "Stern"]
    assert all(row.status == "not_implemented" for row in report.results)
    assert all(row.time_log2 is None and row.memory_log2 is None and row.reason
               for row in report.results)


@pytest.mark.parametrize("kind,parameters", [
    ("sd", {"n": 40, "k": 40, "w": 4}),
    ("sd", {"n": 40, "k": 20, "w": 21}),
    ("sd", {"n": 40, "k": 20, "w": 0}),
    ("sd", {"n": 40, "k": 20, "w": 4, "q": True}),
    ("sd", {"n": 40, "k": 20, "w": 4, "q": 6}),
    ("rank_sd", {"q": 6, "m": 8, "n": 8, "k": 4, "r": 2}),
    ("rank_sd", {"q": 2, "m": 8, "n": 8, "k": 4, "r": 8}),
    ("rank_sd", {"q": 2, "m": 12, "n": 8, "k": 4, "r": 9}),
])
def test_invalid_decoding_parameters_are_rejected(kind, parameters):
    with pytest.raises(ValueError):
        estimate(instance(Problem(kind, parameters)))


@pytest.mark.parametrize("solutions", [-1, float("nan"), float("inf"), True])
def test_invalid_solution_counts_are_rejected(solutions):
    with pytest.raises(ValueError):
        Problem("sd", {"n": 40, "k": 20, "w": 4}, solutions)


def test_rank_solution_count_cannot_be_silently_ignored():
    with pytest.raises(ValueError, match="log2_solutions"):
        Problem("rank_sd", {"q": 2, "m": 8, "n": 8, "k": 4, "r": 2}, 0)


@pytest.mark.parametrize("kind", ["cfp", "qccf"])
def test_profile_qccf_with_extra_tag_is_unsupported_without_inserting_solution_count(kind):
    attack = instance(Problem(kind, {"n": 20, "k": 10, "w": 3}),
                      targets=6, tags=("doom:qccf", "unmodeled"),
                      block_profile=BlockProfile((10, 10), (1, 2)))
    rows = estimate(attack, options=Options(
        classical_algorithms=("Prange", "MAGE-Stern"), quantum_algorithms=())).results
    assert all(row.status == "not_implemented" and row.reason for row in rows)
    assert attack.problem.log2_solutions is None


@pytest.mark.parametrize("algorithm", ["DoesNotExist", "LeeBrickell"])
def test_unknown_or_wrong_family_algorithm_is_rejected(algorithm):
    with pytest.raises(ValueError, match="Unknown or unavailable"):
        estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 4})),
                 options=Options(classical_algorithms=(algorithm,)))


def test_unknown_quantum_algorithm_is_rejected():
    with pytest.raises(ValueError):
        estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 4})),
                 options=Options(classical_algorithms=(), quantum_algorithms=("QUnknown",)))


def test_quantum_only_can_run_without_importing_classical_dependency():
    code = """
import importlib.abc
import sys

class NoClassicalDependency(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('cryptographic_estimators'):
            raise ImportError('Classical dependency intentionally unavailable')

sys.meta_path.insert(0, NoClassicalDependency())
from codebased_estimator import AttackInstance, Options, Problem, estimate
report = estimate(
    AttackInstance('quantum-only', 'msg_recovery', Problem('sd', {'n': 4, 'k': 3, 'w': 1})),
    options=Options(classical_algorithms=(), quantum_algorithms=('QPrange', 'QSS', 'QMMT+')),
)
assert len(report.results) == 3
assert report.results[0].algorithm == 'QPrange'
assert report.results[0].status == 'computed'
assert all(row.status == 'computed' for row in report.results[1:])
assert report.conclusions['quantum'].status == 'computed'
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("solutions", [None, 0])
def test_quantum_single_solution_policy_and_memory_scope_are_explicit(solutions, quantum_cost):
    report = estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 10}, solutions)),
                      options=Options(classical_algorithms=(), quantum_algorithms=("QSS",),
                                      memory_bound_log2_bits=0))
    row, = report.results
    assert row.status == "computed"
    assert row.metadata["effective_log2_solutions"] == 0
    assert row.metadata["memory_bound_applied"] is False
    assert row.metadata["memory_bound_log2_bits"] == 0
    assert ("null input" in row.metadata["solution_count_policy"]) == (solutions is None)
    assert report.conclusions["quantum"].best == (row,)
    assert "memory bound is not applied" in report.conclusions["quantum"].reason


def test_each_quantum_algorithm_is_optimized_with_its_original_parameters(monkeypatch, quantum_cost):
    calls = []
    def capture(*args):
        calls.append(args)
        return quantum_cost
    monkeypatch.setattr("codebased_estimator.quantum.optimize", capture)
    estimate(instance(Problem("sd", {"n": 64, "k": 31, "w": 6}, 0)),
             options=Options(classical_algorithms=(), quantum_algorithms=("QMMT+", "QSS")))
    assert calls == [(64, 31, 6, "QMMT+"), (64, 31, 6, "QSS")]


@pytest.mark.parametrize("problem,context,status", [
    (Problem("sd", {"n": 40, "k": 20, "w": 4}, 0), {"targets": 2}, "not_implemented"),
    (Problem("sd", {"n": 40, "k": 20, "w": 4}, 0), {"tags": ("custom",)}, "not_implemented"),
    (Problem("sd", {"n": 40, "k": 20, "w": 4}, 0), {"structure": ("block weights",)}, "not_implemented"),
    (Problem("sd", {"n": 40, "k": 20, "w": 4, "q": 3}, 0), {}, "not_applicable"),
])
def test_quantum_unsupported_context_never_reaches_optimizer(problem, context, status, monkeypatch):
    def unexpected(*args):
        pytest.fail("Unsupported context reached the quantum optimizer")
    monkeypatch.setattr("codebased_estimator.quantum.optimize", unexpected)
    rows = estimate(instance(problem, **context), options=Options(
        classical_algorithms=(), quantum_algorithms=("QSS", "QMMT+"))).results
    assert all(row.status == status and row.time_log2 is None and row.reason for row in rows)


def test_quantum_search_failure_remains_unavailable(monkeypatch):
    monkeypatch.setattr("codebased_estimator.quantum.optimize", lambda *args: None)
    report = estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 4}, 0)),
                      options=Options(classical_algorithms=(), quantum_algorithms=("QSS",)))
    row, = report.results
    assert row.status == "infeasible" and row.time_log2 is None
    assert row.memory_log2 is None and row.memory_unit == "not_estimated"
    assert "searched parameter domain" in row.reason
    assert report.conclusions["quantum"].status == "unavailable"
    assert "do not assess memory feasibility" in report.conclusions["quantum"].reason


@pytest.mark.parametrize("doom_tag", ["doom:qccf", "doom:qcsd"])
def test_custom_models_receive_context_and_own_all_target_cost_changes(doom_tag):
    received = []

    class NewModel:
        def __init__(self, family, cost):
            self.family = family
            self.name = f"custom-{family}-research-model"
            self.cost = cost

        def estimate(self, attack, options):
            names = getattr(options, f"{self.family}_algorithms")
            received.append((self.family, names, attack.problem.kind,
                             attack.tags, attack.targets, attack.problem.log2_solutions))
            assert options.memory_bound_log2_bits == 9
            return [Estimate(name, self.family, "computed", time_log2=self.cost, memory_log2=8)
                    for name in names]

    kind, solutions = ("qccf", None) if doom_tag == "doom:qccf" else ("qcsd", 2)
    attack = instance(Problem(kind, {"size": 7}, solutions), targets=32, tags=(doom_tag,))
    report = estimate(attack, classical_model=NewModel("classical", 100),
                      quantum_model=NewModel("quantum", 200), options=Options(
                          classical_algorithms=("Prange", "Stern"),
                          quantum_algorithms=("QPrange",), memory_bound_log2_bits=9))
    assert received == [
        ("classical", ("Prange", "Stern"), kind, (doom_tag,), 32, solutions),
        ("quantum", ("QPrange",), kind, (doom_tag,), 32, solutions),
    ]
    assert report.backends["classical"]["name"] == "custom-classical-research-model"
    assert report.backends["quantum"]["name"] == "custom-quantum-research-model"
    # No dispatcher-wide log2(targets) correction may be applied afterwards.
    assert [row.time_log2 for row in report.results] == [100, 100, 200]
    assert all(row.status == "computed" for row in report.results)
