"""Plain tables or JSON, with no service or UI dependency."""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
import sys
from pathlib import Path

from . import AttackInstance, DemoScheme, Options, estimate
from .hamming import (DEFAULT_HAMMING_ALGORITHMS, HAMMING_SCHEMES,
                      hamming_catalogue, hamming_instances)
from .models import QUANTUM_ALGORITHMS
from .matrix_costs import DEFAULT_MATRIX_PROFILE, MATRIX_PROFILES


def _csv_results(reports):
    """Keep every requested classical/quantum candidate, including placeholders."""
    fields = ("scheme", "parameter_set", "goal", "n", "k", "w", "q", "status",
              "model", "algorithm", "time_log2", "memory_log2", "time_unit",
              "memory_unit", "is_best", "reason", "cost_model", "matrix_profile",
              "matrix_block_size")
    writer = csv.DictWriter(sys.stdout, fieldnames=fields)
    writer.writeheader()
    for report in reports:
        instance = report.instance
        conclusions = report.conclusions
        for row in report.results:
            writer.writerow({
                "scheme": instance.scheme, "parameter_set": instance.parameter_set,
                "goal": instance.goal,
                **{name: instance.problem.parameters.get(name, "") for name in ("n", "k", "w", "q")},
                "model": row.model, "algorithm": row.algorithm, "status": row.status,
                "time_log2": row.time_log2, "memory_log2": row.memory_log2,
                "time_unit": row.time_unit, "memory_unit": row.memory_unit,
                "is_best": row in conclusions[row.model].best, "reason": row.reason,
                "cost_model": row.metadata.get("cost_model", ""),
                "matrix_profile": row.metadata.get("matrix_profile", ""),
                "matrix_block_size": row.metadata.get("matrix", {}).get("block_size", ""),
            })


def _hamming_summary(reports):
    """Compact minima when only classical algorithms were requested."""
    rows = []
    for report in reports:
        instance = report.instance
        best = report.conclusions["classical"]
        for result in best.best or (None,):
            p = instance.problem.parameters
            rows.append((instance.scheme, instance.parameter_set, instance.goal,
                         *(p.get(name, "") for name in ("n", "k", "w", "q")),
                         best.status, result.algorithm if result else "",
                         f"{result.time_log2:.6f}" if result else "",
                         f"{result.memory_log2:.6f}" if result else ""))
    print("Preliminary single-target SD baseline: no DOOM, Unbalanced or structural speedups.")
    print("Minimum time among requested classical algorithms; time=log2(bit operations), memory=log2(bits).")
    print("Key rows use the HammingISD.md SD proxy; these are not whole-scheme security levels.")
    print(f"{'parameter set':21} {'goal':12} {'n':>7} {'k':>7} {'w':>5} {'q':>5}  {'algorithm/status':16} {'time':>10} {'memory':>10}")
    for row in rows:
        _, parameter_set, goal, n, k, w, q, status, algorithm, time, memory = row
        print(f"{parameter_set:21} {goal:12} {str(n):>7} {str(k):>7} {str(w):>5} {str(q):>5}  "
              f"{algorithm or status:16} {time or '--':>10} {memory or '--':>10}")
    missing = {report.instance.scheme: report.instance.route for report in reports
               if report.instance.problem.kind != "sd"}
    for reason in missing.values():
        print(f"Unavailable: {reason}")
    print("Use --details or --json for per-algorithm costs, assumptions and source references.")


def _table(reports):
    print("Costs are log2 in the units shown for each row; '--' means unavailable.")
    print("Each row estimates one decoding route, not overall scheme security.")
    for report in reports:
        i = report.instance
        print(f"\n{i.name} | {i.goal} | {i.problem.kind} {i.problem.parameters}")
        print(f"  {i.route}")
        print(f"  tags={list(i.tags)}; targets={i.targets}")
        if report.options.quantum_algorithms and report.options.quantum_matrix_profile != DEFAULT_MATRIX_PROFILE:
            print(f"  Quantum matrix profile: {report.options.quantum_matrix_profile}")
        print(f"  {'algorithm':24} {'model':10} {'status':17} {'time':>9} {'memory':>9}  units (time / memory); parameters")
        for r in report.results:
            time = "--" if r.time_log2 is None else f"{r.time_log2:.3f}"
            memory = "not estimated" if r.is_time_only_quantum else (
                "--" if r.memory_log2 is None else f"{r.memory_log2:.3f}"
            )
            print(f"  {r.algorithm:24} {r.model:10} {r.status:17} {time:>9} {memory:>9}  {r.time_unit} / {r.memory_unit}; {r.parameters}")
            if r.reason:
                print(f"    {r.reason}")
        for family, conclusion in report.conclusions.items():
            if conclusion.best:
                for best in conclusion.best:
                    memory = ("not estimated" if best.is_time_only_quantum else
                              f"2^{best.memory_log2:.3f} {best.memory_unit}")
                    print(f"  Best {family}: {best.algorithm} | "
                          f"time=2^{best.time_log2:.3f} {best.time_unit}; "
                          f"memory={memory}; "
                          f"parameters={best.parameters}")
            else:
                print(f"  Best {family}: -- ({conclusion.status})")
            print(f"    {conclusion.reason}")
        for note in i.assumptions:
            print(f"  Assumption: {note}")
        for reference in i.references:
            print(f"  Source: {reference}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run small synthetic key/msg examples")
    run = commands.add_parser("estimate", help="estimate a single JSON attack instance")
    run.add_argument("input", type=Path)
    run.add_argument("--doom", choices=("qccf", "qcsd"), help="DOOM mechanism tag, interpreted inside each algorithm")
    run.add_argument("--targets", type=int, help="usable candidate/target count, interpreted according to the DOOM tag")
    demo.set_defaults(doom=None, targets=None)
    hamming = commands.add_parser("hamming", help="evaluate local HammingSchemes parameter snapshots without DOOM/Unbalanced")
    hamming.add_argument("--schemes", nargs="+", choices=HAMMING_SCHEMES, help="default: all nine schemes")
    hamming.add_argument("--parameter-sets", nargs="+", help="exact IDs from --list; default: all sets of selected schemes")
    hamming.add_argument("--goal", choices=("both", "key_recovery", "msg_recovery"), default="both")
    hamming.add_argument("--list", action="store_true", help="list source parameter snapshots without running estimators")
    hamming.add_argument("--all-classical", action="store_true", help="use all upstream classical algorithms per field (already the default)")
    hamming.add_argument("--details", action="store_true", help="print full per-algorithm tables")
    hamming.add_argument("--progress", action="store_true", help="print route progress to stderr, keeping JSON/CSV stdout clean")
    hamming.set_defaults(doom=None, targets=None)
    for command in (demo, run, hamming):
        command.add_argument("--classical-algorithms", nargs="*", help="classical names; default: all upstream candidates (demo uses a small selection); empty disables classical")
        command.add_argument("--quantum-algorithms", nargs="*", help="quantum names; default: all registered candidates (demo uses explicit selections); empty disables quantum")
        command.add_argument("--quantum-matrix-profile", choices=MATRIX_PROFILES,
                             default=DEFAULT_MATRIX_PROFILE,
                             help="matrix cost profile for QSS/QMMT+; default: %(default)s")
        command.add_argument("--memory-bound", type=float, help="maximum log2(memory in bits); not applied to time-only quantum estimates")
        output = command.add_mutually_exclusive_group()
        output.add_argument("--json", action="store_true", help="emit reproducible result records")
        if command is hamming:
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
        elif args.command == "hamming":
            instances = hamming_instances(schemes=args.schemes,
                                          parameter_sets=args.parameter_sets, goal=args.goal)
            if args.all_classical and args.classical_algorithms is not None:
                raise ValueError("--all-classical and --classical-algorithms are mutually exclusive")
            if args.csv and args.details:
                raise ValueError("--csv and --details select different output formats; choose one")
            if args.list:
                if args.csv:
                    raise ValueError("--csv requires estimation; use --list --json for the source catalogue")
                wanted = {instance.parameter_set for instance in instances}
                catalogue = [row for row in hamming_catalogue() if row["parameter_set"] in wanted]
                if args.json:
                    print(json.dumps(catalogue, indent=2, ensure_ascii=False, allow_nan=False))
                else:
                    for row in catalogue:
                        print(f"{row['parameter_set']:21} {row['scheme']:12} {row['parameters']}")
                        for note in row.get("notes", ()):
                            print(f"  {note}")
                return 0
            jobs = [(instance, DEFAULT_HAMMING_ALGORITHMS, QUANTUM_ALGORITHMS) for instance in instances]
        else:
            try:
                data = json.loads(args.input.read_text(encoding="utf-8"))
                instance = AttackInstance.from_dict(data)
            except (TypeError, KeyError, ValueError) as exc:
                raise ValueError(f"invalid attack instance: {exc}") from exc
            jobs = [(instance, None, QUANTUM_ALGORITHMS)]
        reports = []
        for index, (instance, classical, quantum) in enumerate(jobs, 1):
            if args.command == "hamming" and args.progress:
                print(f"[{index}/{len(jobs)}] {instance.name}", file=sys.stderr, flush=True)
            changes = {}
            if args.doom is not None:
                existing = tuple(tag for tag in instance.tags if tag.startswith("doom:"))
                tag = f"doom:{args.doom}"
                if existing and existing != (tag,):
                    raise ValueError("--doom conflicts with the instance's DOOM tag")
                changes["tags"] = instance.tags if existing else (*instance.tags, tag)
            if args.targets is not None:
                changes["targets"] = args.targets
            if changes:
                instance = replace(instance, **changes)
            reports.append(estimate(instance, options=Options(
                classical_algorithms=classical if args.classical_algorithms is None else args.classical_algorithms,
                quantum_algorithms=quantum if args.quantum_algorithms is None else args.quantum_algorithms,
                memory_bound_log2_bits=args.memory_bound,
                quantum_matrix_profile=args.quantum_matrix_profile,
            )))
        if args.json:
            print(json.dumps([r.to_dict() for r in reports], indent=2, ensure_ascii=False, allow_nan=False))
        elif args.command == "hamming" and args.csv:
            _csv_results(reports)
        elif args.command == "hamming" and not args.details and all(not r.options.quantum_algorithms for r in reports):
            _hamming_summary(reports)
        else:
            _table(reports)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    except ImportError as exc:
        parser.error(f"backend dependency unavailable: {exc}; install with python -m pip install -e .")
    return 0


if __name__ == "__main__":
    sys.exit(main())
