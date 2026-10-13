"""Problem, recovery route and cost contracts; all costs are base-2 logarithms."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from math import isfinite
from numbers import Real
from typing import Any, Optional, Protocol

from .matrix_costs import DEFAULT_MATRIX_PROFILE, validate_profile


QUANTUM_ALGORITHMS = ("QPrange", "QSS", "QMMT+")


def _nonnegative(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite nonnegative number")
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")


def _strings(values, name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(v, str) or not v.strip() for v in values
    ):
        raise ValueError(f"{name} must be a list/tuple of nonempty strings")
    return tuple(values)


@dataclass(frozen=True)
class Problem:
    """sd: (n,k,w,q); rank_sd: (q,m,n,k,r).

    cfp/qccf support tagged classical and quantum solution-count proxies; other routes
    for these problem kinds, and other kinds, require custom models.

    log2_solutions describes solutions of ONE syndrome, never distinct syndrome
    targets. None preserves the classical SD backend's default and means one
    solution for quantum models; 0 means one solution.
    Tagged QCCF instead supplies its codeword count through AttackInstance.targets.
    """

    kind: str
    parameters: dict[str, int]
    log2_solutions: Optional[float] = None

    def __post_init__(self):
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("problem kind must be a nonempty string")
        if not isinstance(self.parameters, dict):
            raise ValueError("problem parameters must be an object")
        p = dict(self.parameters)
        if self.kind == "sd":
            p.setdefault("q", 2)
        object.__setattr__(self, "parameters", p)
        if self.log2_solutions is not None:
            _nonnegative(self.log2_solutions, "log2_solutions")
        required = {"sd": {"n", "k", "w", "q"},
                    "rank_sd": {"q", "m", "n", "k", "r"}}.get(self.kind)
        if required is None:
            return  # A future model owns the validation of its problem kind.
        if set(p) != required:
            raise ValueError(f"{self.kind} requires exactly {sorted(required)}")
        if any(type(v) is not int or v < 1 for v in p.values()):
            raise ValueError("decoding parameters must be positive integers")
        if not 0 < p["k"] < p["n"] or p["q"] < 2:
            raise ValueError("require 0 < k < n and q >= 2")
        if self.kind == "sd" and p["w"] > p["n"] - p["k"]:
            raise ValueError("the SD backend requires 1 <= w <= n-k")
        if self.kind == "rank_sd":
            if p["r"] >= p["m"] or p["r"] > p["n"]:
                raise ValueError("the RankSD backend requires r < m and r <= n")
            if self.log2_solutions is not None:
                raise ValueError("RankSD does not implement log2_solutions")


@dataclass(frozen=True)
class AttackInstance:
    """One explicit route towards a recovery goal, not whole-scheme security.

    structure lists constraints needing a specialized model (block weights,
    compression, shared support, etc.). The generic backend must not ignore it.
    tags are passed to algorithms BEFORE parameter optimization. DOOM tags:
      doom:qccf -- targets counts usable nonzero codeword/orbit candidates;
      doom:qcsd -- targets counts usable syndrome targets under one matrix.
    Neither tag implies independence or a universal speedup. The built-in
    classical QCCF proxy maps its total usable codeword count to CE nsolutions;
    the quantum QCCF proxy uses it in the outer success probability and excludes
    the direct zero-codeword branch.
    QCSD targets remain separate from each syndrome's log2_solutions.
    cost_proxy is JSON provenance for an explicitly chosen approximate input
    problem, not executable constraints or permission to ignore structure.
    """

    name: str
    goal: str
    problem: Problem
    scheme: Optional[str] = None
    parameter_set: Optional[str] = None
    route: str = "generic decoding"
    targets: int = 1
    tags: tuple[str, ...] = ()
    structure: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    route_id: Optional[str] = None
    cost_proxy: Optional[dict[str, Any]] = None

    def __post_init__(self):
        if self.goal not in ("key_recovery", "msg_recovery"):
            raise ValueError("goal must be key_recovery or msg_recovery")
        if not isinstance(self.problem, Problem):
            raise ValueError("problem must be a Problem")
        if type(self.targets) is not int or self.targets < 1:
            raise ValueError("targets must be a positive integer")
        for name in ("name", "route"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a nonempty string")
        for name in ("scheme", "parameter_set", "route_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a nonempty string or null")
        for name in ("tags", "structure", "assumptions", "references"):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        if self.cost_proxy is not None:
            if not isinstance(self.cost_proxy, dict):
                raise ValueError("cost_proxy must be a JSON object or null")
            if "name" in self.cost_proxy and (
                not isinstance(self.cost_proxy["name"], str) or not self.cost_proxy["name"].strip()
            ):
                raise ValueError("cost_proxy name must be a nonempty string")
            try:
                # Copy nested data and normalize it for replayable JSON output.
                proxy = json.loads(json.dumps(self.cost_proxy, allow_nan=False))
            except (TypeError, ValueError) as exc:
                raise ValueError("cost_proxy must contain finite JSON data") from exc
            object.__setattr__(self, "cost_proxy", proxy)
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must contain no duplicates")
        doom_tags = [tag for tag in self.tags if tag == "doom" or tag.startswith("doom:")]
        if any(tag not in ("doom:qccf", "doom:qcsd") for tag in doom_tags):
            raise ValueError("use doom:qccf or doom:qcsd to specify the DOOM mechanism")
        if len(doom_tags) > 1:
            raise ValueError("doom:qccf and doom:qcsd describe different target semantics; choose one")
        if "doom:qccf" in self.tags and self.problem.kind not in ("cfp", "qccf"):
            raise ValueError("doom:qccf requires a cfp or qccf problem (nonzero codeword finding)")
        if "doom:qccf" in self.tags and self.problem.log2_solutions is not None:
            raise ValueError("doom:qccf uses targets for codeword candidates; omit log2_solutions to avoid double counting")
        if "doom:qcsd" in self.tags and self.problem.kind not in ("sd", "qcsd"):
            raise ValueError("doom:qcsd requires an sd or qcsd problem")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AttackInstance:
        data = dict(data)
        data["problem"] = Problem(**data["problem"])
        return cls(**data)


@dataclass(frozen=True)
class Options:
    """Default to all upstream classical and registered quantum candidates.

    None selects each problem family's upstream classical defaults; an empty
    tuple explicitly disables either family.
    """

    classical_algorithms: Optional[tuple[str, ...]] = None
    quantum_algorithms: tuple[str, ...] = QUANTUM_ALGORITHMS
    memory_bound_log2_bits: Optional[float] = None
    quantum_matrix_profile: str = DEFAULT_MATRIX_PROFILE

    def __post_init__(self):
        for field_name in ("classical_algorithms", "quantum_algorithms"):
            values = getattr(self, field_name)
            if field_name == "classical_algorithms" and values is None:
                continue
            names = _strings(values, field_name)
            if len(set(names)) != len(names):
                raise ValueError(f"{field_name} must contain no duplicates")
            object.__setattr__(self, field_name, names)
        if self.memory_bound_log2_bits is not None:
            _nonnegative(self.memory_bound_log2_bits, "memory_bound_log2_bits")
        validate_profile(self.quantum_matrix_profile)


@dataclass(frozen=True)
class Estimate:
    """One cost record; model is the comparison family (classical or quantum)."""

    algorithm: str
    model: str
    status: str
    time_log2: Optional[float] = None
    memory_log2: Optional[float] = None
    time_unit: str = "bit_operations"
    memory_unit: str = "bits"
    parameters: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    assumptions: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_time_only_quantum(self) -> bool:
        """Recognize the explicit exception to memory-feasibility comparisons."""
        return (self.model == "quantum"
                and self.metadata.get("resource_scope") == "time_only"
                and self.memory_log2 is None
                and self.memory_unit == "not_estimated")


class AttackModel(Protocol):
    """A classical or quantum backend, owning algorithm-specific optimization.

    Read the corresponding Options selection and pass instance.tags/targets
    into each algorithm's cost and parameter search. DOOM is not a third model.
    """

    name: str

    def estimate(self, instance: AttackInstance, options: Options) -> list[Estimate]: ...


@dataclass(frozen=True)
class Conclusion:
    """Minimum-time eligible estimates within one model; retain exact ties."""

    status: str
    best: tuple[Estimate, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class Report:
    instance: AttackInstance
    options: Options
    backends: dict[str, Any]
    results: list[Estimate]

    @property
    def conclusions(self) -> dict[str, Conclusion]:
        """Compare finite costs within each family's declared resource scope.

        These are minima of the evaluated results, not global optimality claims.
        In particular, quantum and classical units are never compared.
        """
        conclusions = {}
        bound = self.options.memory_bound_log2_bits
        for family in ("classical", "quantum"):
            if getattr(self.options, f"{family}_algorithms") == ():
                conclusions[family] = Conclusion("not_requested", reason="No algorithms requested.")
                continue
            rows = [row for row in self.results if row.model == family]
            eligible = [
                row for row in rows
                if row.status == "computed"
                and isinstance(row.time_log2, Real) and not isinstance(row.time_log2, bool)
                and isfinite(row.time_log2)
                and isinstance(row.time_unit, str) and row.time_unit.strip()
                and row.time_unit != "unspecified"
                and (row.is_time_only_quantum or (
                    isinstance(row.memory_log2, Real) and not isinstance(row.memory_log2, bool)
                    and isfinite(row.memory_log2)
                    and isinstance(row.memory_unit, str) and row.memory_unit.strip()
                    and row.memory_unit != "unspecified"
                    and (bound is None or (row.memory_unit == "bits" and row.memory_log2 <= bound))
                ))
            ]
            if not eligible:
                reason = (
                    "No computed finite time estimate is available in declared units; "
                    "time-only quantum estimates do not assess memory feasibility."
                    if any(row.is_time_only_quantum for row in rows) else
                    "No computed finite estimate in declared units satisfies "
                    "the memory constraint; see individual algorithm results."
                )
                conclusions[family] = Conclusion(
                    "unavailable", reason=reason,
                )
                continue
            if len({row.time_unit for row in eligible}) != 1:
                conclusions[family] = Conclusion(
                    "incomparable_units", reason="Time units differ between feasible estimates; "
                    "a common cost model is required to select a minimum.",
                )
                continue
            minimum = min(row.time_log2 for row in eligible)
            resource_note = (
                "finite times and declared units; time-only quantum estimates have no memory "
                "estimate, and the memory bound is not applied to them; limited to this evaluation."
                if any(row.is_time_only_quantum for row in eligible) else
                "finite costs, declared units and feasible memory; limited to this evaluation."
            )
            conclusions[family] = Conclusion(
                "computed", best=tuple(row for row in eligible if row.time_log2 == minimum),
                reason=f"Minimum time among {len(eligible)}/{len(rows)} returned estimates with "
                + resource_note,
            )
        return conclusions

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self),
                "conclusions": {family: asdict(result) for family, result in self.conclusions.items()}}
