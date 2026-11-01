"""Plain tables or JSON, with no service or UI dependency."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
import json
import sys
from pathlib import Path

from . import AttackInstance, DemoScheme, Options, estimate
from .comparison import compare_routes
from .hamming import (DEFAULT_HAMMING_ALGORITHMS, DOOM_MODES, HAMMING_SCHEMES, UNBALANCED_MODES,
                      hamming_catalogue, hamming_instances)
from .rank import RANK_SCHEMES, rank_catalogue, rank_instances
from .models import QUANTUM_ALGORITHMS
from .matrix_costs import DEFAULT_MATRIX_PROFILE, MATRIX_PROFILES


def _csv_results(reports, comparisons=()):
    """Keep every requested classical/quantum candidate, including placeholders."""
    fields = ("scheme", "parameter_set", "goal", "n", "k", "w", "q", "m", "r", "status",
              "model", "algorithm", "time_log2", "memory_log2", "time_unit",
              "memory_unit", "is_best", "reason", "cost_model", "matrix_profile",
              "matrix_block_size", "problem_kind", "doom", "targets", "active_targets",
              "effective_doom", "effective_targets", "route_id", "instance_name", "is_best_route", "cost_proxy")
    writer = csv.DictWriter(sys.stdout, fieldnames=fields)
    writer.writeheader()
    for report in reports:
        instance = report.instance
        conclusions = report.conclusions
        for row in report.results:
            doom = row.metadata.get("doom", {})
            writer.writerow({
                "scheme": instance.scheme, "parameter_set": instance.parameter_set,
                "goal": instance.goal,
                **{name: instance.problem.parameters.get(name, "") for name in ("n", "k", "w", "q", "m", "r")},
                "model": row.model, "algorithm": row.algorithm, "status": row.status,
                "time_log2": row.time_log2, "memory_log2": row.memory_log2,
                "time_unit": row.time_unit, "memory_unit": row.memory_unit,
                "is_best": row in conclusions[row.model].best, "reason": row.reason,
                "route_id": instance.route_id, "instance_name": instance.name,
                "cost_proxy": (instance.cost_proxy or {}).get("name", ""),
                "is_best_route": any(
                    best.name == instance.name and best.estimate == row
                    for comparison in comparisons
                    for best in comparison.conclusions[row.model].best
                ),
                "cost_model": row.metadata.get("cost_model", doom.get("cost_model", "")),
                "matrix_profile": row.metadata.get("matrix_profile", ""),
                "matrix_block_size": row.metadata.get("matrix", {}).get("block_size", ""),
                "problem_kind": instance.problem.kind,
                "doom": ",".join(instance.tags), "targets": instance.targets,
                "active_targets": doom.get("active_targets", ""),
                "effective_doom": ",".join(row.metadata.get("effective_tags", instance.tags)),
                "effective_targets": row.metadata.get("effective_targets", doom.get(
                    "active_targets", doom.get("active_codewords", instance.targets))),
            })


def _hamming_summary(reports):
    """Compact minima when only classical algorithms were requested."""
    rows = []
    for report in reports:
        instance = report.instance
        best = report.conclusions["classical"]
        for result in best.best or (None,):
            p = instance.problem.parameters
            rows.append((instance.scheme, instance.parameter_set, instance.goal, instance.route_id or "default",
                         *(p.get(name, "") for name in ("n", "k", "w", "q")),
                         ",".join(instance.tags) or "none", instance.targets,
                         best.status, result.algorithm if result else "",
                         f"{result.time_log2:.6f}" if result else "",
                         f"{result.memory_log2:.6f}" if result else ""))
    print("Minimum time among requested classical algorithms; time=log2(bit operations), memory=log2(bits).")
    print(f"{'parameter set':21} {'goal':12} {'route':9} {'n':>7} {'k':>7} {'w':>5} {'q':>5}  {'DOOM':9} {'targets':>7}  {'algorithm/status':16} {'time':>10} {'memory':>10}")
    for row in rows:
        _, parameter_set, goal, route_id, n, k, w, q, doom, targets, status, algorithm, time, memory = row
        print(f"{parameter_set:21} {goal:12} {route_id:9} {str(n):>7} {str(k):>7} {str(w):>5} {str(q):>5}  "
              f"{doom:9} {targets:>7}  {algorithm or status:16} {time or '--':>10} {memory or '--':>10}")
    missing = {report.instance.scheme: report.instance.route for report in reports
               if report.instance.problem.kind == "structural_key_recovery"}
    for reason in missing.values():
        print(f"Unavailable: {reason}")
    print("Use --details for per-algorithm rows; --no-brief for route and input details.")


def _sources(references):
    for reference in dict.fromkeys(references):
        print(f"Source: {reference}")


def _hamming_routes(instances, *, as_json=False):
    """List mapped input problems without invoking a cost estimator."""
    if as_json:
        records = [{
            "scheme": i.scheme, "parameter_set": i.parameter_set, "goal": i.goal,
            "name": i.name, "route_id": i.route_id, "route": i.route,
            "problem": asdict(i.problem), "tags": list(i.tags), "targets": i.targets,
            "cost_proxy": i.cost_proxy,
            "block_profile": i.block_profile.to_dict() if i.block_profile else None,
        } for i in instances]
        print(json.dumps(records, indent=2, ensure_ascii=False, allow_nan=False))
        return
    print(f"{'parameter set':21} {'goal':12} {'route':9} {'problem':23} parameters")
    for i in instances:
        problem = next((tag.split(":", 1)[1].upper() for tag in i.tags
                        if tag.startswith("doom:")), i.problem.kind.upper())
        if i.problem.kind == "structural_key_recovery":
            problem, parameters = "structural_key_recovery", "unavailable"
        else:
            p = {**i.problem.parameters, "targets": i.targets}
            if i.problem.log2_solutions is not None:
                p["log2_solutions"] = i.problem.log2_solutions
            parameters = ", ".join(f"{name}={value}" for name, value in p.items())
        print(f"{i.parameter_set:21} {i.goal:12} {i.route_id or 'default':9} {problem:23} {parameters}")


def _route_summary(comparisons):
    """Show the cross-route winners separately for each resource family."""
    for comparison in comparisons:
        if len(comparison.routes) < 2:
            continue
        print(f"\nRoute comparison: {comparison.parameter_set} | {comparison.goal}")
        for family, conclusion in comparison.conclusions.items():
            if conclusion.status == "not_requested":
                continue
            if not conclusion.best:
                print(f"  Best {family} route: -- ({conclusion.status})")
            for best in conclusion.best:
                print(f"  Best {family} route: {best.route_id or best.name} | "
                      f"{best.estimate.algorithm} | time=2^{best.estimate.time_log2:.6f} "
                      f"{best.estimate.time_unit}")


def _table(reports, *, brief=True):
    print("Costs are log2 in the units shown for each row; '--' means unavailable.")
    for report in reports:
        i = report.instance
        print(f"\n{i.name} | {i.goal} | {i.problem.kind} {i.problem.parameters}")
        if not brief and i.route:
            print(f"  Route: {i.route}")
        if not brief and i.block_profile is not None:
            print(f"  Block profile: lengths={list(i.block_profile.lengths)}; weights={list(i.block_profile.weights)}")
        print(f"  tags={list(i.tags)}; targets={i.targets}")
        if not brief and i.problem.kind == "sd":
            solutions = i.problem.log2_solutions
            print(f"  log2_solutions={solutions if solutions is not None else 'auto'}")
        if not brief and report.options.memory_bound_log2_bits is not None:
            print(f"  memory_bound_log2_bits={report.options.memory_bound_log2_bits}")
        if report.options.quantum_algorithms and report.options.quantum_matrix_profile != DEFAULT_MATRIX_PROFILE:
            print(f"  Quantum matrix profile: {report.options.quantum_matrix_profile}")
        print(f"  {'algorithm':24} {'model':10} {'status':17} {'time':>9} {'memory':>9}  units (time / memory); parameters")
        for r in report.results:
            time = "--" if r.time_log2 is None else f"{r.time_log2:.3f}"
            memory = "not estimated" if r.is_time_only else (
                "--" if r.memory_log2 is None else f"{r.memory_log2:.3f}"
            )
            print(f"  {r.algorithm:24} {r.model:10} {r.status:17} {time:>9} {memory:>9}  {r.time_unit} / {r.memory_unit}; {r.parameters}")
            if r.reason and r.status != "computed" and (brief or r.reason != i.route):
                print(f"    {r.reason}")
        fallback = [r.algorithm for r in report.results if r.status == "computed"
                    and r.metadata.get("doom", {}).get("model") == "single_target_fallback"]
        if fallback:
            print(f"  DOOM fallback: {', '.join(fallback)} use single-target SD (targets=1).")
        if not brief:
            used_targets = [
                f"{r.algorithm}={r.metadata['doom']['active_targets']}"
                for r in report.results
                if r.status == "computed"
                and r.metadata.get("doom", {}).get("model") != "single_target_fallback"
                and r.metadata.get("doom", {}).get("active_targets") not in (None, i.targets)
            ]
            if used_targets:
                print(f"  Targets used: {', '.join(used_targets)}")
            used_codewords = [
                f"{r.algorithm}={r.metadata['doom']['active_codewords']}"
                for r in report.results
                if r.status == "computed"
                and r.metadata.get("doom", {}).get("active_codewords") not in (None, i.targets)
            ]
            if used_codewords:
                print(f"  Codewords used: {', '.join(used_codewords)}")
        if report.options.memory_bound_log2_bits is not None and any(
            r.is_time_only_quantum for r in report.results
        ):
            print("  Quantum memory bound is not applied (time-only estimates).")
        if report.options.memory_bound_log2_bits is not None and any(
            r.is_time_only and r.model == "classical" for r in report.results
        ):
            print("  Classical time-only estimates are excluded from minima under a memory bound.")
        for family, conclusion in report.conclusions.items():
            if conclusion.status == "not_requested":
                continue
            if conclusion.best:
                for best in conclusion.best:
                    memory = ("not estimated" if best.is_time_only else
                              f"2^{best.memory_log2:.3f} {best.memory_unit}")
                    print(f"  Best {family}: {best.algorithm} | "
                          f"time=2^{best.time_log2:.3f} {best.time_unit}; "
                          f"memory={memory}")
            else:
                print(f"  Best {family}: -- ({conclusion.status})")
            if conclusion.status == "incomparable_units":
                print(f"    {conclusion.reason}")
    if not brief:
        _sources(reference for report in reports for reference in report.instance.references)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run small synthetic key/msg examples")
    run = commands.add_parser("estimate", help="estimate a single JSON attack instance")
    run.add_argument("input", type=Path)
    run.add_argument("--doom", choices=("qcsd", "qccf"),
                     help="DOOM tag: qcsd for syndrome targets, qccf for nonzero codewords; must match an existing tag")
    run.add_argument("--targets", type=int,
                     help="override usable count: syndromes for QCSD, distinct nonzero codewords for QCCF")
    run.add_argument("--log2-solutions", "--nsolutions", dest="log2_solutions", type=float,
                     help="override log2 of the acceptable solution count per syndrome (CE nsolutions); omit for QCCF")
    demo.set_defaults(doom=None, targets=None, log2_solutions=None)
    hamming = commands.add_parser("hamming", help="evaluate built-in Hamming parameters and recovery routes")
    rank = commands.add_parser("rank", help="evaluate built-in Rank scheme parameters and recovery routes")
    for command, schemes in ((hamming, HAMMING_SCHEMES), (rank, RANK_SCHEMES)):
        command.add_argument("--schemes", nargs="+", choices=schemes, help="default: all schemes in this catalogue")
        command.add_argument("--parameter-sets", nargs="+", help="exact IDs from --list; default: all sets of selected schemes")
        command.add_argument("--goal", choices=("both", "key_recovery", "msg_recovery"), default="both")
        listing = command.add_mutually_exclusive_group()
        listing.add_argument("--list", action="store_true", help="list source parameter snapshots without running estimators")
        listing.add_argument("--list-routes", action="store_true", help="list key/msg recovery problems and mapped parameters without running estimators")
        command.add_argument("--all-classical", action="store_true", help="use all default classical candidates (already the default)")
        command.add_argument("--details", action="store_true", help="print per-algorithm tables; use --no-brief for route and input details")
        command.add_argument("--progress", action="store_true", help="print route progress to stderr, keeping JSON/CSV stdout clean")
        command.set_defaults(targets=None, log2_solutions=None)
    hamming.add_argument("--doom", choices=DOOM_MODES, default="auto",
                         help="auto: documented QCCF/QCSD orbit proxies; none: original single-target SD baseline")
    rank.set_defaults(doom=None, unbalanced="auto")
    for command in (demo, run, hamming, rank):
        if command is not rank:
            command.add_argument("--unbalanced", choices=UNBALANCED_MODES, default="auto",
                                 help="auto: use supplied block weights in supported outer probabilities; none: total-weight baseline")
        command.add_argument("--brief", action=argparse.BooleanOptionalAction, default=True,
                             help="compact text (default: on); --no-brief adds route, input details and parameter sources; JSON/CSV unchanged")
        command.add_argument("--classical-algorithms", nargs="*", help="classical names; default: all candidates for the problem family (demo uses a small selection); empty disables classical")
        command.add_argument("--quantum-algorithms", nargs="*", help="quantum names; default: all registered candidates (rank: none; demo: explicit selections); empty disables quantum")
        command.add_argument("--quantum-matrix-profile", choices=MATRIX_PROFILES,
                             default=DEFAULT_MATRIX_PROFILE,
                             help="matrix cost profile for QSS/QMMT+; default: %(default)s")
        command.add_argument("--memory-bound", type=float, help="maximum log2(memory in bits); not applied to time-only quantum estimates")
        output = command.add_mutually_exclusive_group()
        output.add_argument("--json", action="store_true", help="emit reproducible result records")
        if command in (hamming, rank):
            output.add_argument("--csv", action="store_true", help="emit all classical/quantum algorithm results and per-family best flags as CSV")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            adapter = DemoScheme()
            selections = {
                "hamming": ("Prange", "Stern", "Dumer"),
                "qary": ("Prange", "Stern", "LeeBrickell"),
                "rank": ("GRS", "MaxMinors", "SupportMinors"),
            }
            jobs = [(instance, names, QUANTUM_ALGORITHMS if family == "hamming" else ())
                    for family, names in selections.items()
                    for goal in ("key_recovery", "msg_recovery")
                    for instance in adapter.instances(family, goal)]
        elif args.command in ("hamming", "rank"):
            if args.command == "hamming":
                instances = hamming_instances(schemes=args.schemes,
                                              parameter_sets=args.parameter_sets, goal=args.goal,
                                              doom=args.doom, unbalanced=args.unbalanced)
                source_catalogue = hamming_catalogue
                classical, quantum = DEFAULT_HAMMING_ALGORITHMS, QUANTUM_ALGORITHMS
            else:
                instances = rank_instances(schemes=args.schemes,
                                           parameter_sets=args.parameter_sets, goal=args.goal)
                source_catalogue = rank_catalogue
                classical, quantum = None, ()
            if args.all_classical and args.classical_algorithms is not None:
                raise ValueError("--all-classical and --classical-algorithms are mutually exclusive")
            if args.csv and args.details:
                raise ValueError("--csv and --details select different output formats; choose one")
            if args.list_routes:
                if args.csv:
                    raise ValueError("--csv requires estimation; use --list-routes --json for the route catalogue")
                _hamming_routes(instances, as_json=args.json)
                return 0
            if args.list:
                if args.csv:
                    raise ValueError("--csv requires estimation; use --list --json for the source catalogue")
                wanted = {instance.parameter_set for instance in instances}
                catalogue = [row for row in source_catalogue() if row["parameter_set"] in wanted]
                if args.json:
                    print(json.dumps(catalogue, indent=2, ensure_ascii=False, allow_nan=False))
                else:
                    for row in catalogue:
                        print(f"{row['parameter_set']:21} {row['scheme']:12} {row['parameters']}")
                    if not args.brief:
                        _sources(reference for row in catalogue for reference in row["references"])
                return 0
            jobs = [(instance, classical, quantum) for instance in instances]
        else:
            try:
                data = json.loads(args.input.read_text(encoding="utf-8"))
                instance = AttackInstance.from_dict(data)
            except (TypeError, KeyError, ValueError) as exc:
                raise ValueError(f"invalid attack instance: {exc}") from exc
            jobs = [(instance, None, QUANTUM_ALGORITHMS)]
        reports = []
        for index, (instance, classical, quantum) in enumerate(jobs, 1):
            if args.command in ("hamming", "rank") and args.progress:
                print(f"[{index}/{len(jobs)}] {instance.name}", file=sys.stderr, flush=True)
            changes = {}
            if args.unbalanced == "none":
                changes["block_profile"] = None
            if args.command != "hamming" and args.doom is not None:
                existing = tuple(tag for tag in instance.tags if tag.startswith("doom:"))
                tag = f"doom:{args.doom}"
                if existing and existing != (tag,):
                    raise ValueError("--doom conflicts with the instance's DOOM tag")
                changes["tags"] = instance.tags if existing else (*instance.tags, tag)
            if args.targets is not None:
                changes["targets"] = args.targets
            if args.log2_solutions is not None:
                changes["problem"] = replace(instance.problem, log2_solutions=args.log2_solutions)
            if changes:
                instance = replace(instance, **changes)
            reports.append(estimate(instance, options=Options(
                classical_algorithms=classical if args.classical_algorithms is None else args.classical_algorithms,
                quantum_algorithms=quantum if args.quantum_algorithms is None else args.quantum_algorithms,
                memory_bound_log2_bits=args.memory_bound,
                quantum_matrix_profile=args.quantum_matrix_profile,
            )))
        comparisons = compare_routes(reports) if args.command in ("hamming", "rank") else []
        if args.json:
            by_route = {name: comparison.to_dict() for comparison in comparisons
                        if len(comparison.routes) > 1 for name in comparison.routes}
            records = [r.to_dict() for r in reports]
            for record in records:
                if record["instance"]["name"] in by_route:
                    record["route_comparison"] = by_route[record["instance"]["name"]]
            print(json.dumps(records, indent=2, ensure_ascii=False, allow_nan=False))
        elif args.command in ("hamming", "rank") and args.csv:
            _csv_results(reports, comparisons)
        elif args.command == "hamming" and args.brief and not args.details and all(not r.options.quantum_algorithms for r in reports):
            _hamming_summary(reports)
        else:
            _table(reports, brief=args.brief)
        if args.command in ("hamming", "rank") and not args.json and not args.csv:
            _route_summary(comparisons)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    except ImportError as exc:
        parser.error(f"backend dependency unavailable: {exc}; install with python -m pip install -e .")
    return 0


if __name__ == "__main__":
    sys.exit(main())
