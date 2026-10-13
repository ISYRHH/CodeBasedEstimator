"""Check submission mappings, scheme-specific DOOM, and the original SD baseline."""

import csv
import importlib
import io
import json
from math import log2
from types import SimpleNamespace

import pytest

from codebased_estimator import AttackInstance, Estimate, Options, Problem, Report, estimate
from codebased_estimator.__main__ import main
from codebased_estimator.hamming import (
    COMPOSITE_MSG_SCHEMES,
    HAMMING_SCHEMES,
    HammingScheme,
    hamming_catalogue,
    hamming_instances,
)


# Independently recorded reference tuples, rather than recomputing the adapter
# formulas in the assertions: (n, key k, key w, message k, message w, q).
# QCTM and UVW intentionally have no key tuple in HammingISD.md.
EXPECTED = {
    "BIKE_MLThre": {
        "BIKE_MLThre-128": (24646, 12323, 142, 12323, 134, 2),
        "BIKE_MLThre-192": (49318, 24659, 206, 24659, 199, 2),
        "BIKE_MLThre-256": (81946, 40973, 274, 40973, 264, 2),
        "BIKE_MLThre-512": (300002, 150001, 546, 150001, 524, 2),
    },
    "TRIKE": {
        "TRIKE-1": (30903, 20602, 81, 10301, 201, 2),
        "TRIKE-2": (46743, 31162, 105, 15581, 263, 2),
        "TRIKE-3": (66009, 44006, 123, 22003, 319, 2),
        "TRIKE-5": (106089, 70726, 165, 35363, 429, 2),
        "TRIKE-7": (209073, 139382, 249, 69691, 659, 2),
        "TRIKE-9": (342129, 228086, 333, 114043, 877, 2),
    },
    "HARE": {
        "HARE-128": (41798, 20899, 158, 20899, 158, 2),
        "HARE-256": (104758, 52379, 262, 52379, 262, 2),
        "HARE-384": (209738, 104869, 386, 104869, 386, 2),
        "HARE-512": (347962, 173981, 518, 173981, 518, 2),
    },
    "NSS-HQC": {
        "NSS-HQC-128": (58886, 29443, 146, 29443, 132, 2),
        "NSS-HQC-256": (108986, 54493, 234, 54493, 212, 2),
        "NSS-HQC-384": (245158, 122579, 350, 122579, 318, 2),
        "NSS-HQC-512": (435802, 217901, 466, 217901, 426, 2),
    },
    "TriQ-KEM": {
        "TriQ-KEM-128": (32602, 16301, 134, 16301, 134, 2),
        "TriQ-KEM-256": (100726, 50363, 264, 50363, 264, 2),
        "TriQ-KEM-384": (195302, 97651, 392, 97651, 392, 2),
        "TriQ-KEM-512": (315254, 157627, 520, 157627, 520, 2),
    },
    "Mito": {
        "Mito-1-128": (61492, 30746, 172, 30746, 176, 2),
        "Mito-1-256": (135308, 67654, 269, 67654, 274, 2),
        "Mito-1-512": (425044, 212522, 527, 212522, 532, 2),
        "Mito-1-E-128": (58484, 29242, 172, 29242, 176, 2),
        "Mito-1-E-256": (129044, 64522, 269, 64522, 274, 2),
        "Mito-1-E-512": (409748, 204874, 527, 204874, 532, 2),
        "Mito-2-E-128": (82024, 41012, 186, 41012, 190, 2),
        "Mito-2-E-256": (172184, 86092, 284, 86092, 288, 2),
        "Mito-2-E-512": (522344, 261172, 544, 261172, 548, 2),
    },
    "QUBE": {
        "QUBE-128": (39327, 13109, 224, 26218, 85, 2),
        "QUBE-192": (76071, 25357, 333, 50714, 125, 2),
        "QUBE-256": (124953, 41651, 443, 83302, 166, 2),
        "QUBE-384": (248271, 82757, 664, 165514, 248, 2),
        "QUBE-512": (407553, 135851, 883, 271702, 329, 2),
    },
    "QCTM": {
        "QCTM128": (10070, None, None, 4957, 142, 2),
        "QCTM256": (19000, None, None, 9783, 256, 2),
        "QCTM512": (38000, None, None, 19891, 503, 2),
    },
    "UVW-KEM": {
        "UVW-KEM-128": (860, None, None, 430, 116, 433),
        "UVW-KEM-256": (1708, None, None, 854, 232, 857),
        "UVW-KEM-512": (3412, None, None, 1706, 463, 1709),
    },
}


EXPECTED_TARGETS = {
    "BIKE_MLThre": [12323, 24659, 40973, 150001],
    "TRIKE": [10301, 15581, 22003, 35363, 69691, 114043],
    "HARE": [20899, 52379, 104869, 173981],
    "NSS-HQC": [29443, 54493, 122579, 217901],
    "TriQ-KEM": [16301, 50363, 97651, 157627],
    "Mito": [30746, 67654, 212522, 29242, 64522, 204874, 41012, 86092, 261172],
    "QUBE": [13109, 25357, 41651, 82757, 135851],
    "QCTM": [19, 19, 19],
    "UVW-KEM": [1, 1, 1],
}


@pytest.mark.parametrize("doom", ["auto", "none"])
@pytest.mark.parametrize("scheme,parameter_set,expected", [
    (scheme, parameter_set, expected)
    for scheme, parameters in EXPECTED.items()
    for parameter_set, expected in parameters.items()
])
def test_every_submission_instance_has_the_reference_decoding_tuple(scheme, parameter_set, expected, doom):
    n, key_k, key_w, msg_k, msg_w, q = expected
    for goal, k, w in (("key_recovery", key_k, key_w), ("msg_recovery", msg_k, msg_w)):
        instances = HammingScheme(scheme).instances(parameter_set, goal, doom=doom)
        multiple = (goal == "msg_recovery" and scheme in COMPOSITE_MSG_SCHEMES) or (goal == "key_recovery" and scheme == "Mito")
        assert len(instances) == (2 if multiple else 1)
        attack = instances[0]
        assert (attack.scheme, attack.parameter_set, attack.goal) == (scheme, parameter_set, goal)
        assert attack.structure == ()
        assert any("HammingISD.md" in ref for ref in attack.references)
        assert any("local/HammingSchemes/" in ref for ref in attack.references)
        assert any("Unbalanced" in note for note in attack.assumptions)
        if k is None:
            assert attack.problem.kind == "structural_key_recovery"
            assert attack.problem.parameters == {}
            assert attack.problem.log2_solutions is None
            assert attack.targets == 1 and attack.tags == ()
        else:
            assert attack.problem.parameters == {"n": n, "k": k, "w": w, "q": q}
            if doom == "auto" and q == 2:
                is_qccf = scheme in ("BIKE_MLThre", "TRIKE") and goal == "key_recovery"
                assert attack.problem.kind == ("cfp" if is_qccf else "sd")
                assert attack.tags == ("doom:qccf" if is_qccf else "doom:qcsd",)
                assert attack.problem.log2_solutions == (None if is_qccf else 0)
                expected_targets = dict(zip(EXPECTED[scheme], EXPECTED_TARGETS[scheme]))
                assert attack.targets == expected_targets[parameter_set]
                assert any("isd_parameter_mapping.md" in ref for ref in attack.references)
            else:
                assert attack.problem.kind == "sd"
                assert attack.problem.log2_solutions == 0
                assert attack.targets == 1 and attack.tags == ()
                assert any("no DOOM" in note for note in attack.assumptions)
                if goal == "key_recovery" and scheme in ("BIKE_MLThre", "TRIKE"):
                    assert any("proxy" in note and "nonzero" in note for note in attack.assumptions)


def test_catalogue_covers_all_sets_and_copies_nested_source_data():
    assert set(HAMMING_SCHEMES) == set(EXPECTED)
    expected_ids = {parameter_set for sets in EXPECTED.values() for parameter_set in sets}
    catalogue = hamming_catalogue()
    assert len(catalogue) == len(expected_ids) == 42
    assert {row["parameter_set"] for row in catalogue} == expected_ids
    for scheme, sets in EXPECTED.items():
        assert set(HammingScheme(scheme).parameter_sets) == set(sets)
    mito = next(row for row in catalogue if row["parameter_set"] == "Mito-1-128")
    mito["parameters"]["wx"][0] = -1
    mito["references"].clear()
    copied = next(row for row in hamming_catalogue() if row["parameter_set"] == "Mito-1-128")
    assert copied["parameters"]["wx"] == [44, 41]
    assert copied["references"]
    attacks = hamming_instances()
    assert len(attacks) == len({attack.name for attack in attacks}) == 119


def test_batch_filters_goals_and_removes_duplicate_scheme_selections():
    attacks = hamming_instances(schemes=["TRIKE", "UVW-KEM", "TRIKE"],
                               parameter_sets=["TRIKE-2", "UVW-KEM-128"], goal="msg_recovery")
    assert [(attack.scheme, attack.parameter_set, attack.goal) for attack in attacks] == [
        ("TRIKE", "TRIKE-2", "msg_recovery"),
        ("UVW-KEM", "UVW-KEM-128", "msg_recovery"),
    ]


@pytest.mark.parametrize("arguments", [
    {"schemes": ["unknown"]},
    {"schemes": []},
    {"parameter_sets": []},
    {"parameter_sets": ["QCTM-128"]},
    {"schemes": ["QCTM"], "parameter_sets": ["UVW-KEM-128"]},
    {"goal": "both_recovery"},
    {"doom": "qcsd"},
    {"doom": None},
])
def test_invalid_batch_filters_fail_before_costing(arguments):
    with pytest.raises(ValueError):
        hamming_instances(**arguments)


@pytest.mark.parametrize("doom", ["auto", "none"])
@pytest.mark.parametrize("scheme,parameter_set", [("QCTM", "QCTM128"), ("UVW-KEM", "UVW-KEM-128")])
def test_missing_key_reductions_remain_unavailable(scheme, parameter_set, doom):
    attack = HammingScheme(scheme).instances(parameter_set, "key_recovery", doom=doom)[0]
    report = estimate(attack, options=Options(classical_algorithms=("Prange", "Stern"),
                                              quantum_algorithms=()))
    assert [row.algorithm for row in report.results] == ["Prange", "Stern"]
    assert all(row.status == "not_implemented" and row.reason for row in report.results)
    assert all(row.time_log2 is None and row.memory_log2 is None for row in report.results)
    assert report.conclusions["classical"].status == "unavailable"
    assert report.conclusions["classical"].best == ()


@pytest.mark.parametrize("doom", ["auto", "none"])
@pytest.mark.parametrize("scheme,parameter_set,goal,family", [
    ("BIKE_MLThre", "BIKE_MLThre-128", "key_recovery", "SD"),
    ("TRIKE", "TRIKE-2", "key_recovery", "SD"),
    ("UVW-KEM", "UVW-KEM-128", "msg_recovery", "SDFq"),
])
def test_real_prange_costs_match_direct_upstream_solution_counts(scheme, parameter_set, goal, family, doom):
    attack = HammingScheme(scheme).instances(parameter_set, goal, doom=doom)[0]
    report = estimate(attack, options=Options(classical_algorithms=("Prange",),
                                              quantum_algorithms=()))
    result = report.results[0]
    module = importlib.import_module(f"cryptographic_estimators.{family}Estimator")
    parameters = dict(attack.problem.parameters)
    solutions = log2(attack.targets) if attack.tags == ("doom:qccf",) else 0
    problem_options = {"nsolutions": solutions}
    if family == "SD":
        parameters.pop("q")
    else:
        problem_options["is_syndrome_zero"] = False
        assert result.metadata["is_syndrome_zero"] is False
    direct = module.Prange(getattr(module, f"{family}Problem")(**parameters, **problem_options),
                           bit_complexities=1, complexity_type=0, memory_access=0)
    assert result.status == "computed"
    assert result.time_log2 == pytest.approx(direct.time_complexity(), abs=1e-10)
    assert result.memory_log2 == pytest.approx(direct.memory_complexity(), abs=1e-10)
    assert result.parameters == direct.get_optimal_parameters_dict()
    assert result.metadata["effective_log2_solutions"] == solutions
    assert result.metadata["targets"] == attack.targets
    assert result.time_unit == "bit_operations"
    assert result.memory_unit == "bits"
    json.dumps(report.to_dict(), allow_nan=False)


def test_cli_list_filters_source_catalogue_without_running_estimators(monkeypatch, capsys):
    cli = importlib.import_module("codebased_estimator.__main__")

    def unexpected_cost(*args, **kwargs):
        pytest.fail("--list must not run a cost estimator")

    monkeypatch.setattr(cli, "estimate", unexpected_cost)
    assert main(["hamming", "--schemes", "Mito", "--parameter-sets", "Mito-1-128",
                 "--list", "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert len(records) == 1
    assert records[0]["parameter_set"] == "Mito-1-128"
    assert records[0]["parameters"]["wx"] == [44, 41]
    assert records[0]["references"]


def test_cli_json_keeps_missing_key_and_computed_message_with_default_algorithms(capsys):
    assert main(["hamming", "--parameter-sets", "UVW-KEM-128", "--json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert [record["instance"]["goal"] for record in records] == ["key_recovery", "msg_recovery"]
    message_rows = records[1]["results"]
    assert {row["algorithm"] for row in message_rows if row["model"] == "classical"} == {
        "Prange", "Stern", "LeeBrickell",
    }
    assert all(row["status"] == "computed" and row["time_log2"] > 0
               for row in message_rows if row["model"] == "classical")
    for record in records:
        quantum_rows = [row for row in record["results"] if row["model"] == "quantum"]
        assert [row["algorithm"] for row in quantum_rows] == ["QPrange", "QSS", "QMMT+"]
        assert all(row["status"] == "not_applicable" and row["reason"] for row in quantum_rows)
        assert all(row["time_log2"] is None and row["memory_log2"] is None
                   for row in quantum_rows)
        assert record["conclusions"]["quantum"]["status"] == "unavailable"
    assert records[0]["conclusions"]["classical"]["status"] == "unavailable"
    assert records[1]["conclusions"]["classical"]["status"] == "computed"
    assert records[1]["instance"]["problem"]["parameters"]["q"] == 433
    assert records[1]["instance"]["references"]
    assert records[1]["backends"]["classical"]["package"] == "cryptographic_estimators"


def test_cli_csv_has_numeric_costs_only_for_available_routes(capsys):
    assert main(["hamming", "--schemes", "UVW-KEM", "--parameter-sets", "UVW-KEM-128",
                 "--csv"]) == 0
    records = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert len(records) == 10
    assert set(records[0]) == {
        "scheme", "parameter_set", "goal", "n", "k", "w", "q", "model",
        "algorithm", "status", "time_log2", "memory_log2", "time_unit",
        "memory_unit", "is_best", "reason", "cost_model", "matrix_profile", "matrix_block_size",
        "problem_kind", "doom", "targets", "active_targets",
        "effective_doom", "effective_targets",
        "route_id", "instance_name", "is_best_route", "cost_proxy",
    }
    keys = [row for row in records if row["goal"] == "key_recovery"]
    messages = [row for row in records if row["goal"] == "msg_recovery"]
    assert len(keys) == 4
    assert all(row["time_log2"] == row["memory_log2"] == row["n"] == "" for row in keys)
    assert all(row["reason"] and row["is_best"] == "False" for row in keys)
    assert all(row["problem_kind"] == "structural_key_recovery" for row in keys)
    assert all(row["problem_kind"] == "sd" for row in messages)
    assert all(row["doom"] == row["active_targets"] == "" and row["targets"] == "1"
               for row in records)
    classical = [row for row in messages if row["model"] == "classical"]
    assert {row["algorithm"] for row in classical} == {"Prange", "Stern", "LeeBrickell"}
    assert all(row["status"] == "computed" and row["q"] == "433" for row in classical)
    assert all(float(row["time_log2"]) > 0 and float(row["memory_log2"]) > 0
               for row in classical)
    assert all(row["time_unit"] == "bit_operations" and row["memory_unit"] == "bits"
               for row in classical)
    minimum = min(float(row["time_log2"]) for row in classical)
    assert all((row["is_best"] == "True") == (float(row["time_log2"]) == minimum)
               for row in classical)
    quantum = [row for row in messages if row["model"] == "quantum"]
    assert [row["algorithm"] for row in quantum] == ["QPrange", "QSS", "QMMT+"]
    assert all(row["status"] == "not_applicable" and row["reason"] for row in quantum)
    assert all(row["time_log2"] == row["memory_log2"] == "" and row["is_best"] == "False"
               for row in quantum)


@pytest.mark.parametrize("extra_arguments", [[], ["--all-classical"]])
def test_cli_default_and_all_classical_pass_family_specific_selection_to_backend(
    extra_arguments, monkeypatch, capsys,
):
    cli = importlib.import_module("codebased_estimator.__main__")
    received = []

    def capture_estimate(attack, *, options):
        received.append((attack.problem.parameters["q"], options.classical_algorithms,
                         options.quantum_algorithms))
        return Report(attack, options, {}, [Estimate("probe", "classical", "computed", 10, 5)])

    monkeypatch.setattr(cli, "estimate", capture_estimate)
    assert main(["hamming", "--parameter-sets", "BIKE_MLThre-128", "UVW-KEM-128",
                 "--goal", "msg_recovery", *extra_arguments, "--json"]) == 0
    assert received == [(2, None, ("QPrange", "QSS", "QMMT+")),
                        (433, None, ("QPrange", "QSS", "QMMT+"))]
    assert len(json.loads(capsys.readouterr().out)) == 2


@pytest.fixture
def small_binary_hamming(monkeypatch):
    """Exercise the real upstream optimizers without the submission-scale search."""
    cli = importlib.import_module("codebased_estimator.__main__")
    attack = AttackInstance(
        name="small binary Hamming route", scheme="synthetic", parameter_set="small",
        goal="msg_recovery", problem=Problem("sd", {"n": 40, "k": 20, "w": 4, "q": 2}, 0),
    )
    monkeypatch.setattr(cli, "hamming_instances", lambda **kwargs: [attack])
    cost = SimpleNamespace(time_log2=19.5, parameters={"ell": 0, "p": 0},
                           details={}, search={"method": "test fixture"})
    monkeypatch.setattr("codebased_estimator.quantum.optimize", lambda *args: cost)
    return attack


BINARY_CLASSICAL_ALGORITHMS = {
    "BallCollision", "BJMMdw", "BJMMpdw", "BJMM", "BJMMplus", "BothMay",
    "Dumer", "MayOzerov", "Prange", "Stern",
}


def test_cli_binary_default_computes_all_upstream_algorithms_and_quantum_time_estimates(
    small_binary_hamming, capsys,
):
    assert main(["hamming", "--json"]) == 0
    record, = json.loads(capsys.readouterr().out)
    classical = [row for row in record["results"] if row["model"] == "classical"]
    assert {row["algorithm"] for row in classical} == BINARY_CLASSICAL_ALGORITHMS
    assert all(row["status"] == "computed" and row["time_log2"] > 0
               and row["memory_log2"] > 0 for row in classical)
    quantum = [row for row in record["results"] if row["model"] == "quantum"]
    assert [row["algorithm"] for row in quantum] == ["QPrange", "QSS", "QMMT+"]
    assert quantum[0]["status"] == "not_implemented" and quantum[0]["time_log2"] is None
    assert all(row["status"] == "computed" and row["time_log2"] > 0 and row["reason"]
               for row in quantum[1:])
    assert all(row["memory_log2"] is None and row["memory_unit"] == "not_estimated"
               for row in quantum[1:])
    assert record["conclusions"]["classical"]["status"] == "computed"
    assert record["conclusions"]["quantum"]["status"] == "computed"


def test_cli_default_text_shows_all_algorithms_and_quantum_time_costs(small_binary_hamming, capsys):
    assert main(["hamming"]) == 0
    output = capsys.readouterr().out
    for name in BINARY_CLASSICAL_ALGORITHMS | {"QPrange", "QSS", "QMMT+"}:
        assert any(line.split()[:1] == [name] for line in output.splitlines())
    assert "not_implemented" in output
    assert "finite quantum costs and independent parameter optimization are pending" in output
    assert "Best classical:" in output
    assert "Best quantum: QSS | time=2^" in output
    assert "Best quantum: QMMT+ | time=2^" in output
    assert "memory=not estimated" in output


@pytest.mark.parametrize("arguments,expected_classical,expected_quantum", [
    (["--classical-algorithms", "Prange", "Stern", "--quantum-algorithms", "QSS"],
     ["Prange", "Stern"], ["QSS"]),
    (["--classical-algorithms", "--quantum-algorithms", "QPrange"], [], ["QPrange"]),
    (["--classical-algorithms", "Prange", "--quantum-algorithms"], ["Prange"], []),
])
def test_cli_explicit_algorithm_subsets_and_empty_family_flags(
    arguments, expected_classical, expected_quantum, small_binary_hamming, capsys,
):
    assert main(["hamming", *arguments, "--json"]) == 0
    record, = json.loads(capsys.readouterr().out)
    for model, expected in (("classical", expected_classical), ("quantum", expected_quantum)):
        assert [row["algorithm"] for row in record["results"] if row["model"] == model] == expected
        if not expected:
            assert record["conclusions"][model]["status"] == "not_requested"


@pytest.mark.parametrize("arguments", [
    ["--schemes", "QCTN"],
    ["--parameter-sets", "QCTM-128", "--list"],
    ["--schemes", "QCTM", "--parameter-sets", "UVW-KEM-128", "--list"],
    ["--parameter-sets", "QCTM128", "--all-classical", "--classical-algorithms", "Prange"],
    ["--parameter-sets", "QCTM128", "--list", "--csv"],
    ["--classical-algorithms", "--quantum-algorithms"],
    ["--doom", "qcsd"],
])
def test_cli_rejects_invalid_or_conflicting_selection(arguments, capsys):
    with pytest.raises(SystemExit) as error:
        main(["hamming", *arguments])
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_cli_details_prints_mapping_and_submission_sources(capsys):
    assert main(["hamming", "--parameter-sets", "QCTM128", "--goal", "key_recovery",
                 "--classical-algorithms", "Prange", "--details", "--no-brief"]) == 0
    output = capsys.readouterr().out
    assert "Source: local/notes/HammingISD.md" in output
    assert "Source: local/HammingSchemes/QCTM/" in output
    assert "Best classical: -- (unavailable)" in output


def test_cli_csv_rejects_conflicting_details_format(capsys):
    with pytest.raises(SystemExit) as error:
        main(["hamming", "--parameter-sets", "UVW-KEM-128", "--goal", "msg_recovery",
              "--csv", "--details"])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "--csv and --details select different output formats" in output.err


def test_cli_csv_keeps_explicit_quantum_selection(small_binary_hamming, capsys):
    assert main(["hamming", "--classical-algorithms", "Prange",
                 "--quantum-algorithms", "QPrange", "--csv"]) == 0
    classical, quantum = csv.DictReader(io.StringIO(capsys.readouterr().out))
    assert classical["algorithm"] == "Prange"
    assert classical["model"] == "classical"
    assert classical["status"] == "computed"
    assert classical["is_best"] == "True"
    assert quantum["algorithm"] == "QPrange"
    assert quantum["model"] == "quantum"
    assert quantum["status"] == "not_implemented"
    assert quantum["time_log2"] == quantum["memory_log2"] == ""
    assert quantum["is_best"] == "False"
    assert quantum["reason"]


def test_cli_csv_declares_quantum_time_only_scope(small_binary_hamming, capsys):
    assert main(["hamming", "--classical-algorithms", "--quantum-algorithms", "QSS",
                 "--memory-bound", "0", "--csv"]) == 0
    quantum, = csv.DictReader(io.StringIO(capsys.readouterr().out))
    assert quantum["status"] == "computed" and quantum["is_best"] == "True"
    assert float(quantum["time_log2"]) > 0
    assert quantum["time_unit"] == "quantum_bit_operations"
    assert quantum["memory_log2"] == "" and quantum["memory_unit"] == "not_estimated"
    assert "memory bound is not applied" in quantum["reason"]


def test_cli_quantum_request_automatically_prints_detailed_rows(capsys):
    assert main(["hamming", "--parameter-sets", "UVW-KEM-128", "--goal", "msg_recovery",
                 "--classical-algorithms", "Prange", "--quantum-algorithms", "QPrange"]) == 0
    output = capsys.readouterr().out
    assert "QPrange" in output
    assert "not_applicable" in output
    assert "only binary syndrome-decoding routes" in output
    assert "Best classical: Prange" in output
    assert "Best quantum: -- (unavailable)" in output
    assert "Source:" not in output
    assert "Assumption:" not in output
