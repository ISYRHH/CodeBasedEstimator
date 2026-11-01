"""QPrange reuses the native block event, not a second support/cost kernel."""
from dataclasses import asdict, replace
from fractions import Fraction
import json
from math import log2, prod, sqrt

import pytest

from codebased_estimator import AttackInstance, BlockProfile, Options, Problem, estimate, hamming_instances
from codebased_estimator.__main__ import main
from codebased_estimator.assumptions import BLOCK_OUTER, BLOCK_SOLUTIONS
from codebased_estimator.matrix_costs import MATRIX_PROFILES, matrix_budget
from codebased_estimator.qprange import evaluate_qprange
from codebased_estimator.quantum_costs import evaluate_parameters


def attack(solutions=0, **changes):
    original = AttackInstance("native block qPrange", "msg_recovery",
        Problem("sd", {"n": 12, "k": 6, "w": 4}, solutions),
        block_profile=BlockProfile((6, 6), (1, 3)))
    return replace(original, **changes)


def result(instance, profile=MATRIX_PROFILES[0], **options):
    return estimate(instance, options=Options(classical_algorithms=(),
        quantum_algorithms=("QPrange",), quantum_matrix_profile=profile, **options)).results[0]


@pytest.mark.parametrize("profile", MATRIX_PROFILES)
@pytest.mark.parametrize("solutions", [0, 2, 1024])
@pytest.mark.parametrize("blocks", [
    BlockProfile((6, 6), (1, 3)), BlockProfile((12,), (4,)),
    BlockProfile((3, 4, 5), (0, 0, 4)),
])
def test_block_fixed_point_exactly_reuses_native_cost(profile, solutions, blocks):
    native = evaluate_parameters(12, 6, 4, "QSS", ell=0, p=0,
        matrix_profile=profile, log2_solutions=solutions, block_profile=blocks)
    got = evaluate_qprange(12, 6, 4, matrix_profile=profile,
        log2_solutions=solutions, block_profile=blocks)
    assert got.time_log2 == native.time_log2
    assert got.unbalanced == native.unbalanced
    assert got.parameters["ell"] == got.parameters["p"] == 0
    assert got.search["attack_parameter_search"] is False
    assert all(got.details[key] == value for key, value in native.details.items())
    assert got.matrix["profile"] == profile


@pytest.mark.parametrize("profile", MATRIX_PROFILES)
def test_one_twelfth_probability_uses_rank_once_and_no_extra_block_check(profile):
    got = evaluate_qprange(12, 6, 4, matrix_profile=profile,
        block_profile=BlockProfile((6, 6), (1, 3)))
    rho = prod(1-Fraction(1,2**j) for j in range(1,7)) / prod(
        1-Fraction(1,2**j) for j in range(7,13))
    assert got.details["log2_P"] == pytest.approx(-log2(12), abs=1e-12)
    assert got.details["log2_rho"] == pytest.approx(log2(rho), abs=1e-12)
    assert got.details["log2_P_eff_model"] == pytest.approx(log2(rho/12), abs=1e-12)
    assert got.details["log2_direct_check"] == 0  # native one-vector aggregate budget
    budget = matrix_budget(12, 6, 0, profile)
    expected = log2(12*7 + 12*(budget.total+1)/sqrt(float(rho/12)))
    assert got.time_log2 == pytest.approx(expected, abs=1e-12)
    assert got.unbalanced["allocation"] == (1,5)


@pytest.mark.parametrize("profile", MATRIX_PROFILES)
@pytest.mark.parametrize("solutions", [None, 0, 2])
def test_profile_metadata_and_qcsd_fallback_are_preserved(profile, solutions, monkeypatch):
    monkeypatch.setattr("codebased_estimator.quantum.optimize",
        lambda *a, **k: pytest.fail("qPrange does not optimize ell/p"))
    plain = attack(solutions)
    direct = result(plain, profile, memory_bound_log2_bits=0)
    fallback = result(replace(plain, targets=32, tags=("doom:qcsd",)), profile,
        memory_bound_log2_bits=0)
    native = evaluate_parameters(12, 6, 4, "QSS", ell=0, p=0,
        matrix_profile=profile, log2_solutions=solutions or 0,
        block_profile=plain.block_profile)
    assert direct.status == fallback.status == "computed"
    assert direct.time_log2 == fallback.time_log2 == native.time_log2
    assert direct.parameters == fallback.parameters
    assert direct.metadata["unbalanced"] == fallback.metadata["unbalanced"] == native.unbalanced
    assert direct.metadata["resource_scope"] == "time_only"
    assert direct.metadata["memory_bound_applied"] is False
    assert direct.memory_log2 is None and direct.memory_unit == "not_estimated"
    assert fallback.metadata["effective_targets"] == 1
    assert fallback.metadata["doom"]["applied"] is False
    assert BLOCK_OUTER in direct.assumptions and BLOCK_SOLUTIONS in direct.assumptions
    assert "actual structured-matrix rank" in direct.metadata["not_included"]
    json.dumps(asdict(direct), allow_nan=False)


@pytest.mark.parametrize("profile", MATRIX_PROFILES)
def test_single_block_degenerates_to_generic_budget(profile):
    generic = evaluate_qprange(40, 20, 4, matrix_profile=profile)
    blocked = evaluate_qprange(40, 20, 4, matrix_profile=profile,
        block_profile=BlockProfile((40,), (4,)))
    assert blocked.time_log2 == generic.time_log2
    assert blocked.details["log2_P"] == generic.details["log2_P"]


@pytest.mark.parametrize("changes", [
    {"targets": 2}, {"tags": ("unknown",)}, {"structure": ("truncated",)},
    {"tags": ("doom:qcsd", "unknown"), "targets": 16},
    {"tags": ("doom:qcsd",), "targets": 16, "structure": ("truncated",)},
    {"problem": Problem("cfp", {"n": 12, "k": 6, "w": 4}),
     "targets": 8, "tags": ("doom:qccf",)},
])
def test_unmodeled_profile_contexts_do_not_enter_fixed_point(changes, monkeypatch):
    monkeypatch.setattr("codebased_estimator.qprange.evaluate_qprange",
        lambda *a, **k: pytest.fail("unsupported profile context reached direct point"))
    row = result(attack(**changes))
    assert row.status == "not_implemented" and row.time_log2 is None


def test_hamming_default_profiles_and_uniform_baseline_use_same_qprange():
    common = dict(parameter_sets=["HARE-2"], goal="both", doom="none")
    profiled, uniform = hamming_instances(**common), hamming_instances(**common, unbalanced="none")
    assert len(profiled) == len(uniform) == 3
    for current, baseline in zip(profiled, uniform):
        assert current.block_profile is not None and baseline.block_profile is None
        assert current.route_id == baseline.route_id and current.cost_proxy == baseline.cost_proxy
        row = result(current)
        p = current.problem.parameters
        native = evaluate_parameters(p["n"], p["k"], p["w"], "QSS", ell=0, p=0,
            block_profile=current.block_profile)
        assert row.status == "computed" and row.time_log2 == native.time_log2
        assert row.metadata["unbalanced"] == native.unbalanced
        assert row.time_log2 <= result(baseline).time_log2 + 1e-12


def test_cli_profile_and_unbalanced_none_keep_existing_schema(tmp_path, capsys):
    path = tmp_path/"block.json"
    path.write_text(json.dumps(asdict(attack())))
    args = ["estimate", str(path), "--classical-algorithms", "--quantum-algorithms", "QPrange", "--json"]
    assert main(args) == 0
    profiled, = json.loads(capsys.readouterr().out)
    assert main(args + ["--unbalanced", "none"]) == 0
    uniform, = json.loads(capsys.readouterr().out)
    assert profiled["instance"]["block_profile"]["weights"] == [1,3]
    assert profiled["results"][0]["metadata"]["unbalanced"]
    assert uniform["instance"]["block_profile"] is None
    assert "unbalanced" not in uniform["results"][0]["metadata"]
    assert uniform["results"][0]["time_log2"] == result(replace(attack(), block_profile=None)).time_log2
