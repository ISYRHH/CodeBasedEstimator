"""Check real upstream costs and the demo's scientific interpretation boundaries."""

import importlib
import json
import subprocess
import sys
from math import comb, log2

import pytest

from codebased_estimator import AttackInstance, Estimate, Options, Problem, estimate


def instance(problem, **kwargs):
    return AttackInstance("test route", "msg_recovery", problem, **kwargs)


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
    report = estimate(instance(problem), options=Options(classical_algorithms=algorithms))
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
                       options=Options(classical_algorithms=("Prange",))).results[0]
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
                   options=Options(classical_algorithms=("LeeBrickell",))).results[0]
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
        classical_algorithms=(algorithm,), memory_bound_log2_bits=0))
    assert report.results
    assert all(row.status in ("infeasible", "not_applicable") for row in report.results)
    assert all(row.reason for row in report.results)
    json.dumps(report.to_dict(), allow_nan=False)


def test_classical_and_requested_quantum_algorithms_share_one_report():
    options = Options(classical_algorithms=("Prange", "Stern"),
                      quantum_algorithms=("QPrange", "QSS", "QMMT+"))
    report = estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 4}, 0)), options=options)
    classical = [row for row in report.results if row.model == "classical"]
    quantum = [row for row in report.results if row.model == "quantum"]
    assert [row.algorithm for row in classical] == ["Prange", "Stern"]
    assert all(row.status == "computed" for row in classical)
    assert [row.algorithm for row in quantum] == ["QPrange", "QSS", "QMMT+"]
    assert set(report.backends) == {"classical", "quantum"}
    for row in quantum:
        assert row.status == "not_implemented"
        assert row.time_log2 is None and row.memory_log2 is None
        assert row.reason
    json.dumps(report.to_dict(), allow_nan=False)


@pytest.mark.parametrize("classical,quantum,expected", [
    ((), ("QSS",), [("quantum", "QSS")]),
    (("Prange",), (), [("classical", "Prange")]),
])
def test_empty_algorithm_tuples_disable_each_family_independently(classical, quantum, expected):
    report = estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 4}, 0)),
                      options=Options(classical_algorithms=classical, quantum_algorithms=quantum))
    assert [(row.model, row.algorithm) for row in report.results] == expected


def test_estimate_requires_at_least_one_enabled_family():
    with pytest.raises(ValueError):
        estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 4})),
                 options=Options(classical_algorithms=(), quantum_algorithms=()))


def test_default_classical_selection_still_includes_all_upstream_algorithms():
    report = estimate(instance(Problem("sd", {"n": 40, "k": 20, "w": 4}, 0)),
                      options=Options(classical_algorithms=None))
    module = importlib.import_module("cryptographic_estimators.SDEstimator")
    direct = module.SDEstimator(n=40, k=20, w=4, nsolutions=0)
    assert {row.algorithm for row in report.results} == {
        type(algorithm).__name__ for algorithm in direct.algorithms()
    }
    assert all(row.model == "classical" for row in report.results)


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
        expected = "not_applicable" if doom_tag == "doom:qccf" and row.model == "quantum" else "not_implemented"
        assert row.status == expected
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
                      options=Options(classical_algorithms=("Prange", "Stern")))
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
    AttackInstance('quantum-only', 'msg_recovery', Problem('sd', {'n': 40, 'k': 20, 'w': 4})),
    options=Options(classical_algorithms=(), quantum_algorithms=('QPrange',)),
)
assert len(report.results) == 1
assert report.results[0].algorithm == 'QPrange'
assert report.results[0].status == 'not_implemented'
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


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
