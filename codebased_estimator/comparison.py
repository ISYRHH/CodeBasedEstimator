"""Compare evaluated recovery routes with matching goals and cost options."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional

from .models import Estimate, Options, Report


@dataclass(frozen=True)
class RouteEstimate:
    """A winning estimate together with its replayable route identity."""

    name: str
    route: str
    route_id: Optional[str]
    estimate: Estimate


@dataclass(frozen=True)
class RouteConclusion:
    """Minimum-time route estimates within one model; retain exact ties."""

    status: str
    best: tuple[RouteEstimate, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class RouteComparison:
    """Results for routes sharing a scheme, parameter set, goal and options."""

    scheme: Optional[str]
    parameter_set: Optional[str]
    goal: str
    routes: tuple[str, ...]
    options: Options
    conclusions: dict[str, RouteConclusion]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compare_routes(reports: Iterable[Report]) -> list[RouteComparison]:
    """Select the fastest evaluated routes separately for classical and quantum.

    Reports are grouped by ``(scheme, parameter_set, goal)`` in first-seen
    order, including single-route groups. Each group must use identical
    options and unique instance names. Eligibility follows ``Report.conclusions``;
    unavailable routes do not compete, while incomparable feasible units in
    any route prevent a minimum for that model across the entire group.

    Only evaluated candidates are compared. In particular, this function does
    not assert optimality over algorithms or routes that were not evaluated.
    """
    groups: dict[tuple[Optional[str], Optional[str], str], list[Report]] = {}
    for report in reports:
        instance = report.instance
        key = (instance.scheme, instance.parameter_set, instance.goal)
        group = groups.setdefault(key, [])
        if group and report.options != group[0].options:
            raise ValueError(f"Cannot compare routes with different options for {key!r}")
        if any(existing.instance.name == instance.name for existing in group):
            raise ValueError(f"Duplicate route instance name {instance.name!r} for {key!r}")
        group.append(report)

    comparisons = []
    for (scheme, parameter_set, goal), group in groups.items():
        route_conclusions = [report.conclusions for report in group]
        conclusions = {}
        for family in ("classical", "quantum"):
            family_conclusions = [result[family] for result in route_conclusions]
            if all(result.status == "not_requested" for result in family_conclusions):
                conclusions[family] = RouteConclusion(
                    "not_requested", reason="No algorithms requested.",
                )
                continue
            if any(result.status == "incomparable_units" for result in family_conclusions):
                conclusions[family] = RouteConclusion(
                    "incomparable_units",
                    reason="Time units differ between feasible estimates within a route; "
                    "a common cost model is required to compare routes.",
                )
                continue
            candidates = [
                RouteEstimate(report.instance.name, report.instance.route,
                              report.instance.route_id, estimate)
                for report, result in zip(group, family_conclusions)
                if result.status == "computed"
                for estimate in result.best
            ]
            if not candidates:
                conclusions[family] = RouteConclusion(
                    "unavailable",
                    reason="No route has an eligible computed estimate; "
                    "see individual route conclusions.",
                )
                continue
            if len({candidate.estimate.time_unit for candidate in candidates}) != 1:
                conclusions[family] = RouteConclusion(
                    "incomparable_units",
                    reason="Time units differ between feasible route estimates; "
                    "a common cost model is required to select a minimum.",
                )
                continue
            minimum = min(candidate.estimate.time_log2 for candidate in candidates)
            eligible_routes = sum(result.status == "computed" for result in family_conclusions)
            resource_note = (
                "Time-only quantum estimates have no memory estimate, and the memory "
                "bound is not applied to them."
                if any(candidate.estimate.is_time_only_quantum for candidate in candidates) else
                "Memory feasibility is not assessed for time-only results."
                if any(candidate.estimate.is_time_only for candidate in candidates) else
                "Estimates have finite costs, declared units and feasible memory."
            )
            conclusions[family] = RouteConclusion(
                "computed",
                best=tuple(candidate for candidate in candidates
                           if candidate.estimate.time_log2 == minimum),
                reason=f"Minimum time across {eligible_routes}/{len(group)} eligible evaluated routes; "
                f"limited to this evaluation. {resource_note}",
            )
        comparisons.append(RouteComparison(
            scheme, parameter_set, goal, tuple(report.instance.name for report in group),
            group[0].options, conclusions,
        ))
    return comparisons
