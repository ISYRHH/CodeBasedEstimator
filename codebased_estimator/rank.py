"""Rank estimators for generic problems and built-in scheme profiles."""

from __future__ import annotations

from copy import deepcopy
import json
from math import isfinite

from . import rank_sd_estimator as generic
from . import rank_sd_schemes as specialized
from .models import AttackInstance, Estimate, Options, Problem
from .schemes_final import LOONG, PIGLET, BRA_DATA, BRQC_DATA, CM


RANK_SCHEMES = ("BAG-Loong", "BAG-Piglet", "BRA", "BRQC", "C-Multi-UR-AG")
GOALS = ("key_recovery", "msg_recovery")
_TABLES = dict(zip(RANK_SCHEMES, (LOONG, PIGLET, BRA_DATA, BRQC_DATA, CM)))
_GENERIC = {
    "Rank-BE": generic.be, "Rank-OJ1": generic.oj1_estimator,
    "Rank-OJ2": generic.oj2_estimator, "Rank-OJ": generic.oj_coeff_classic,
    "Rank-OJ-S": generic.oj_support_tight, "Rank-GRS": generic.grs,
    "Rank-AGHT": generic.aght, "Rank-GRS-GE": generic.grs_ge,
    "Rank-AP": generic.ap, "Rank-MM": generic.mm, "Rank-SM": generic.sm,
    "Rank-CWW": generic.cww_new_hybrid,
}
_SCHEME_ALGORITHMS = {
    "BAG-Loong": ("Rank-OJ", "Rank-PRR", "Rank-MM", "Rank-ZD-MM"),
    "BAG-Piglet": ("Rank-OJ", "Rank-PRR", "Rank-MM", "Rank-ZD-MM"),
    "BRA": ("Rank-MM", "Rank-ZD-MM", "Rank-AGHT", "Rank-PRR", "Rank-OJ"),
    "BRQC": ("Rank-MM", "Rank-ZD-MM", "Rank-AGHT", "Rank-PRR", "Rank-OJ"),
    "C-Multi-UR-AG": ("Rank-MM", "Rank-ZD-MM", "Rank-SM", "Rank-AGHT", "Rank-OJ",
                      "Rank-RSL-AGHT", "Rank-RSL-OJ"),
}
RANK_GENERIC_ALGORITHMS = tuple(_GENERIC)
RANK_SCHEME_ALGORITHMS = tuple(dict.fromkeys(
    name for names in _SCHEME_ALGORITHMS.values() for name in names
))
RANK_CLASSICAL_ALGORITHMS = tuple(dict.fromkeys(
    (*RANK_GENERIC_ALGORITHMS, *RANK_SCHEME_ALGORITHMS)
))
RANK_QUANTUM_ALGORITHMS = ("Rank-WT23",)
_SOURCE = "Existing local Rank scripts: schemes_final.py and rank_sd_schemes.py"


def rank_catalogue() -> list[dict]:
    """Return independent catalogue records from the existing parameter tables."""
    return [
        {"scheme": scheme, "parameter_set": f"{scheme}-{level}",
         "algorithm_family": "rank_scheme",
         "parameters": deepcopy({k: v for k, v in data.items() if not k.startswith("c_")}),
         "references": [_SOURCE],
         "notes": ["Existing script instance A is key recovery; instance B is message recovery."]}
        for scheme, table in _TABLES.items() for level, data in table.items()
    ]


def _route_parameters(scheme, data, goal):
    key = goal == "key_recovery"
    omega = 2.8 if scheme in ("BAG-Loong", "BAG-Piglet") else 2.0
    common = {"m": data["m"], "omega": omega}
    if scheme == "BAG-Loong":
        t, g = data["A" if key else "B"]
        return {**common, "n": data["n"], "n1": data["n1"],
                "t1": t[0], "t2": t[1], "g": g, "instance": 1 if key else 2}
    if scheme == "BAG-Piglet":
        return {**common, "n": data["n"], "t": list(data["A" if key else "B"]),
                "ell": 3 if key else 4, "s": 1 if key else 2}
    if scheme in ("BRA", "BRQC"):
        nvec, rvec = data["A" if key else "B"]
        a, p = data["mm2" if key else "mm3"]
        return {**common, "k": data["k"], "nvec": list(nvec), "rvec": list(rvec),
                "a": list(a), "p": list(p), "h": [0] * len(nvec)}
    return {**common, "n": 2 * data["n"] + (0 if key else data["N1"]),
            "k": data["n"], "r": data["w1" if key else "w2"],
            "N": data["N1" if key else "N2"]}


class RankScheme:
    """Expose the two existing script instances through the scheme contract."""

    def __init__(self, scheme: str):
        if scheme not in RANK_SCHEMES:
            raise ValueError(f"Unknown Rank scheme {scheme!r}; choose from {', '.join(RANK_SCHEMES)}")
        self.scheme = scheme

    @property
    def parameter_sets(self) -> tuple[str, ...]:
        return tuple(f"{self.scheme}-{level}" for level in _TABLES[self.scheme])

    def instances(self, parameter_set: str, goal: str) -> list[AttackInstance]:
        if goal not in GOALS:
            raise ValueError("goal must be key_recovery or msg_recovery")
        if parameter_set not in self.parameter_sets:
            raise ValueError(f"Unknown parameter set {parameter_set!r} for {self.scheme}")
        level = int(parameter_set.rsplit("-", 1)[1])
        parameters = _route_parameters(self.scheme, _TABLES[self.scheme][level], goal)
        route_id = "instance_a" if goal == "key_recovery" else "instance_b"
        return [AttackInstance(
            name=f"{parameter_set}/{goal}", scheme=self.scheme, parameter_set=parameter_set,
            goal=goal, problem=Problem("rank_scheme", parameters), route_id=route_id,
            route=f"{self.scheme}: {'key' if goal == 'key_recovery' else 'message'} recovery",
            assumptions=("Costs use the scheme's matrix multiplication exponent and report time only.",),
            references=(_SOURCE,),
        )]


def rank_instances(*, schemes=None, parameter_sets=None, goal="both") -> list[AttackInstance]:
    selected = tuple(RANK_SCHEMES if schemes is None else schemes)
    if not selected:
        raise ValueError("select at least one Rank scheme")
    adapters = [RankScheme(name) for name in dict.fromkeys(selected)]
    available = {name for adapter in adapters for name in adapter.parameter_sets}
    wanted = available if parameter_sets is None else set(parameter_sets)
    if not wanted:
        raise ValueError("select at least one parameter set")
    if wanted - available:
        raise ValueError(f"Unknown parameter sets for selected schemes: {', '.join(sorted(wanted - available))}")
    if goal not in (*GOALS, "both"):
        raise ValueError("goal must be key_recovery, msg_recovery or both")
    goals = GOALS if goal == "both" else (goal,)
    return [instance for adapter in adapters for name in adapter.parameter_sets if name in wanted
            for selected_goal in goals for instance in adapter.instances(name, selected_goal)]


def rank_algorithms(instance: AttackInstance, model="classical") -> tuple[str, ...]:
    if model == "quantum":
        return RANK_QUANTUM_ALGORITHMS if instance.problem.kind == "rank_sd" else ()
    if instance.problem.kind == "rank_sd":
        return tuple(_GENERIC)
    if instance.problem.kind == "rank_scheme":
        return _SCHEME_ALGORITHMS.get(instance.scheme, ())
    return ()


def _scheme_cost(name, instance):
    """Call the same functions with the same arguments as schemes_final.py."""
    p, scheme = instance.problem.parameters, instance.scheme
    attack = name.removeprefix("Rank-")
    optimal = {}
    if scheme == "BAG-Loong":
        fn = {"OJ": specialized.loong_oj, "PRR": specialized.loong_prr,
              "MM": specialized.loong_mm}[attack]
        cost = fn(p["n"], p["n1"], p["t1"], p["t2"], p["g"], p["m"], p["instance"], p["omega"])
    elif scheme == "BAG-Piglet":
        if attack == "PRR":
            cost = specialized.piglet_prr(p["n"], p["t"], p["m"], p["ell"], p["s"], p["omega"])
        else:
            functions = {
                ("OJ", 3): specialized.piglet_oj_31, ("OJ", 4): specialized.piglet_oj_42,
                ("MM", 3): specialized.piglet_mm_31, ("MM", 4): specialized.piglet_mm_42,
            }
            cost = functions[attack, p["ell"]](p["n"], p["t"], p["m"], p["omega"])
    elif scheme in ("BRA", "BRQC"):
        if attack == "MM":
            result = specialized.bra_mm_at(p["m"], p["nvec"], p["k"], p["rvec"],
                                           p["a"], p["p"], p["h"], p["omega"])
            cost = result[0] if result is not None else None
            optimal = {key: p[key] for key in ("a", "p", "h")}
        elif attack == "OJ":
            cost, N = specialized.bra_oj_c(p["nvec"], p["k"], p["rvec"], p["m"], p["omega"])
            optimal = {"N": N}
        else:
            fn = specialized.bra_aght if attack == "AGHT" else specialized.bra_prr
            cost = fn(p["nvec"], p["k"], p["rvec"], p["m"], p["omega"])
    elif attack == "MM":
        cost, a = specialized.cmulti_mm(p["m"], p["n"], p["k"], p["r"], p["omega"])
        optimal = {"a": a}
    elif attack == "SM":
        cost, b, a, puncture = specialized.cmulti_sm_best(
            p["m"], p["n"], p["k"], p["r"], bmax=3, omega=p["omega"])
        optimal = {"b": b, "a": a, "p": puncture}
    else:
        if attack in ("AGHT", "RSL-AGHT"):
            cost = specialized.bra_aght([p["n"]], p["k"], [p["r"]], p["m"], p["omega"])
        else:
            cost, N = specialized.bra_oj_c([p["n"]], p["k"], [p["r"]], p["m"], p["omega"])
            optimal = {"N": N}
        if attack.startswith("RSL-"):
            cost -= p["N"]
    return cost, optimal


class RankModel:
    name = "local Rank estimators"

    @staticmethod
    def applicability(name: str, instance: AttackInstance):
        model = "quantum" if name in RANK_QUANTUM_ALGORITHMS else "classical"
        if name not in rank_algorithms(instance, model):
            return "This local Rank algorithm does not support this problem or scheme."
        if instance.targets != 1 or instance.tags or instance.structure or instance.block_profile is not None:
            return "Local Rank scripts do not accept additional targets, tags or structural constraints."
        if instance.problem.log2_solutions is not None:
            return "Local Rank scripts do not implement a solution-count adjustment."
        if instance.problem.kind == "rank_sd":
            from cryptographic_estimators.helper import is_prime_power

            if not is_prime_power(instance.problem.parameters["q"]):
                return "q must be a prime power to define a finite field"
        if instance.problem.kind == "rank_scheme":
            try:
                expected = RankScheme(instance.scheme).instances(instance.parameter_set, instance.goal)[0]
                # JSON comparison also distinguishes integer inputs from floats/bools,
                # which compare equal in Python but cannot be passed to script ranges.
                supplied = json.dumps(instance.problem.parameters, sort_keys=True, allow_nan=False)
                canonical = json.dumps(expected.problem.parameters, sort_keys=True, allow_nan=False)
            except (TypeError, ValueError) as exc:
                return str(exc)
            if supplied != canonical:
                return "Rank scheme inputs must match the selected built-in script instance."
        return None

    def estimate_algorithm(self, name: str, instance: AttackInstance, options: Options) -> Estimate:
        model = "quantum" if name in RANK_QUANTUM_ALGORITHMS else "classical"
        base = {"algorithm": name, "model": model, "memory_unit": "not_estimated",
                "time_unit": "quantum_bit_operations" if model == "quantum" else "bit_operations",
                "assumptions": instance.assumptions, "references": instance.references}
        metadata = {"resource_scope": "time_only", "implementation": self.name}
        reason = self.applicability(name, instance)
        if reason:
            return Estimate(**base, status="not_implemented", reason=reason, metadata=metadata)
        try:
            if name == "Rank-ZD-MM":
                from .zd_mm import evaluate
                from .zd_mm_profiles import PROFILES

                profile = PROFILES[(instance.parameter_set, instance.goal)]
                omega = instance.problem.parameters["omega"]
                cost, details = evaluate(profile, omega)
                metadata.update(implementation="zd_mm.py", omega=omega,
                                stage_log2=details.pop("stage_log2"),
                                success_neglog2=details.pop("success_neglog2"))
                base["references"] = (*instance.references, "ZD-MM work-factor model (docs/zd_mm.md)")
                return Estimate(**base, status="computed", time_log2=cost,
                                parameters=details, metadata=metadata)
            if instance.problem.kind == "rank_scheme":
                cost, optimal = _scheme_cost(name, instance)
                finite = cost is not None and isfinite(cost)
                return Estimate(**base, status="computed" if finite else "not_applicable",
                                time_log2=cost if finite else None, parameters=optimal,
                                reason="" if finite else "The existing Rank script returned no finite cost.",
                                metadata={**metadata, "omega": instance.problem.parameters["omega"]})
            parameters = generic.Params(**instance.problem.parameters)
            fn = generic.wt23_quantum_grs if model == "quantum" else _GENERIC[name]
            row = fn(parameters)
            finite = row.log2_bits is not None and isfinite(row.log2_bits)
            base["references"] = (*instance.references, *((row.source,) if row.source else ()))
            return Estimate(**base, status=row.status if finite else (
                row.status if row.status != "computed" else "not_applicable"),
                time_log2=row.log2_bits if finite else None, parameters=row.optimal,
                reason=row.notes or row.conditions,
                metadata={**metadata, "omega": parameters.omega, "theta": parameters.theta,
                          "domain": row.domain, "source_attack": row.attack,
                          "log2_ops": row.log2_ops if row.log2_ops is not None and isfinite(row.log2_ops) else None,
                          "reported_bits": row.bits, "conditions": row.conditions})
        except (ArithmeticError, ValueError) as exc:
            return Estimate(**base, status="not_applicable", reason=str(exc), metadata=metadata)

    def estimate(self, instance: AttackInstance, options: Options) -> list[Estimate]:
        classical = (rank_algorithms(instance) if options.classical_algorithms is None
                     else options.classical_algorithms)
        return [self.estimate_algorithm(name, instance, options)
                for name in (*classical, *options.quantum_algorithms) if name.startswith("Rank-")]
