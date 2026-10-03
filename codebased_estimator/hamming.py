"""Preliminary single-target SD routes from local/notes/HammingISD.md.

The parameter catalogue is a reviewed snapshot of the local submissions, so
installed packages also work without the (untracked) local/ directory.
"""

from __future__ import annotations

from copy import deepcopy

from .hamming_parameters import HAMMING_PARAMETERS
from .models import AttackInstance, Problem


HAMMING_SCHEMES = (
    "BIKE_MLThre", "TRIKE", "HARE", "NSS-HQC", "TriQ-KEM", "Mito", "QUBE",
    "QCTM", "UVW-KEM",
)
GOALS = ("key_recovery", "msg_recovery")
# Resolve all classical candidates in the appropriate upstream field backend.
DEFAULT_HAMMING_ALGORITHMS = None
MAPPING_REFERENCE = "local/notes/HammingISD.md: 各算法 ISD 实例（未考虑 DOOM/Unbalanced 等）"

_ASSUMPTIONS = (
    "Preliminary generic ISD baseline following HammingISD.md; not a whole-scheme security estimate.",
    "Single target and one designated acceptable solution (log2_solutions=0); no DOOM, QC orbit or multiple-solution speedup.",
    "Block weights are collapsed to total Hamming weight; Unbalanced ISD and other structure-specific attacks are excluded.",
    "Recovery postprocessing, candidate verification and their success probabilities are not costed.",
)
_KEY_ASSUMPTION = (
    "For this preliminary key route, ordinary SD cost is used as a proxy for finding the designated nonzero low-weight secret. "
    "This is not a dedicated homogeneous codeword-finding model or a proof that any low-weight word recovers the key."
)


def hamming_catalogue() -> list[dict]:
    """Return independent records with source parameters and local references."""
    return deepcopy(HAMMING_PARAMETERS)


class HammingScheme:
    """Adapt one submission's parameter sets to the explicitly simplified routes.

    QCTM and UVW-KEM key routes remain unsupported records, rather than being
    silently omitted or assigned their message-recovery costs.
    """

    def __init__(self, scheme: str):
        if scheme not in HAMMING_SCHEMES:
            raise ValueError(f"Unknown Hamming scheme {scheme!r}; choose from {', '.join(HAMMING_SCHEMES)}")
        self.scheme = scheme

    @property
    def parameter_sets(self) -> tuple[str, ...]:
        return tuple(row["parameter_set"] for row in HAMMING_PARAMETERS if row["scheme"] == self.scheme)

    def instances(self, parameter_set: str, goal: str) -> list[AttackInstance]:
        if goal not in GOALS:
            raise ValueError("goal must be key_recovery or msg_recovery")
        if parameter_set not in self.parameter_sets:
            raise ValueError(f"Unknown parameter set {parameter_set!r} for {self.scheme}; choose from {', '.join(self.parameter_sets)}")
        entry = next(row for row in HAMMING_PARAMETERS
                     if row["scheme"] == self.scheme and row["parameter_set"] == parameter_set)
        p = entry["parameters"]
        key = goal == "key_recovery"
        scheme = self.scheme
        assumptions = (*_ASSUMPTIONS, *entry.get("notes", ()))

        if key and scheme in ("QCTM", "UVW-KEM"):
            reason = (
                "HammingISD.md supplies no key-recovery ISD reduction for QCTM; structural key attacks are outside this baseline."
                if scheme == "QCTM" else
                "UVW-KEM key recovery requires distinguishing (u,u)D codewords and a weight-dependent codeword-count analysis; "
                "HammingISD.md supplies no single fixed SD instance."
            )
            problem = Problem("structural_key_recovery", {})
            route = reason
            assumptions = (*assumptions, reason)
        else:
            q = p.get("q", 2)
            if scheme == "BIKE_MLThre":
                n, k, w = 2 * p["r"], p["r"], p["w"] if key else p["t"]
                formula = "(2r,r,w)" if key else "(2r,r,t)"
            elif scheme == "TRIKE":
                n, k, w = 3 * p["r"], (2 if key else 1) * p["r"], p["w"] if key else p["t"]
                formula = "(3r,2r,w)" if key else "(3r,r,t)"
            elif scheme == "HARE":
                n, k, w = 2 * p["r"], p["r"], 2 * (p["w"] if key else p["wr"])
                formula = "(2r,r,2w)" if key else "(2r,r,2wr)"
            elif scheme == "NSS-HQC":
                n, k = 2 * p["r"], p["r"]
                w = 2 * p["wsk"] if key else p["wr1"] + p["wr2"]
                formula = "(2r,r,2wsk)" if key else "(2r,r,wr1+wr2)"
            elif scheme == "TriQ-KEM":
                n, k = 2 * p["r"], p["r"]
                w = p["wx"] + p["wy"] if key else 2 * p["wr"]
                formula = "(2r,r,wx+wy)" if key else "(2r,r,2wr)"
            elif scheme == "Mito":
                n, k = 2 * p["d"] * p["r"], p["d"] * p["r"]
                w = sum(p["wx"]) + sum(p["wy"]) if key else sum(p["wr"]) + sum(p["wt"])
                formula = "(2dr,dr,sum(wx_i)+sum(wy_i))" if key else "(2dr,dr,sum(wr_i)+sum(wt_i))"
            elif scheme == "QUBE":
                n, k = 3 * p["r"], (1 if key else 2) * p["r"]
                w = 2 * p["wx"] + p["wy"] if key else 2 * p["wf"] + p["wg"]
                formula = "(3r,r,2wx+wy)" if key else "(3r,2r,2wf+wg)"
            elif scheme == "QCTM":
                if p["t"] % 2 != 1:
                    raise ValueError("QCTM requires odd Goppa degree t for integral (t-1)/2")
                n, k, w = p["n"], p["n"] - p["m"] * (p["t"] - 1) - 1, (p["t"] - 1) // 2
                formula = "(n,n-m(t-1)-1,(t-1)/2)"
            else:  # UVW-KEM, message recovery over Fq.
                n, k, w = p["n"], p["k1"] + p["k2"], p["w"]
                formula = "(n,k1+k2,w) over Fq"
            problem = Problem("sd", {"n": n, "k": k, "w": w, "q": q}, log2_solutions=0)
            route = f"HammingISD.md preliminary {goal}: {formula}; source parameters={p}"
            if key:
                assumptions = (*assumptions, _KEY_ASSUMPTION)

        return [AttackInstance(
            name=f"{parameter_set}/{goal}", scheme=scheme, parameter_set=parameter_set,
            goal=goal, problem=problem, route=route, assumptions=assumptions,
            references=(MAPPING_REFERENCE, *entry["references"]),
        )]


def hamming_instances(*, schemes=None, parameter_sets=None, goal="both") -> list[AttackInstance]:
    """Select a batch; reject misspelled or incompatible filters before costing."""
    selected = tuple(HAMMING_SCHEMES if schemes is None else schemes)
    if not selected:
        raise ValueError("select at least one Hamming scheme")
    adapters = [HammingScheme(name) for name in dict.fromkeys(selected)]
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
