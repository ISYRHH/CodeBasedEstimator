"""Scheme decoding routes with scheme-specific DOOM target semantics.

The parameter catalogue contains a self-contained, reviewed parameter snapshot.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from .assumptions import SINGLE_SYNDROME
from .hamming_parameters import HAMMING_PARAMETERS
from .models import AttackInstance, Problem
from .mito_parity import MitoKeyParity
from .unbalanced import BlockProfile


HAMMING_SCHEMES = (
    "BIKE_MLThre", "TRIKE", "HARE", "HEP-QC", "NSS-HQC", "TriQ-KEM", "Mito", "QUBE",
    "QCTM", "UVW-KEM", "HQC",
)
GOALS = ("key_recovery", "msg_recovery")
# Resolve all classical candidates in the appropriate upstream field backend.
DEFAULT_HAMMING_ALGORITHMS = None
DOOM_MODES = ("auto", "none")
UNBALANCED_MODES = ("auto", "none")
COMPOSITE_MSG_SCHEMES = ("HARE", "HEP-QC", "NSS-HQC", "TriQ-KEM", "Mito", "QUBE", "HQC")

_ASSUMPTIONS = (
    "Decoding cost only; scheme-level recovery, validation and support correlations are not modeled.",
)
_KEY_ASSUMPTION = (
    "Single-target SD proxy for the designated nonzero secret; homogeneous codeword search is not modeled."
)
_COMPOSITE_MSG_ASSUMPTIONS = (
    "Assumes v-Encode(m) is available at no cost; this is not a full unknown-message recovery reduction.",
    "Uses the uncompressed core; truncation and compression residuals are not modeled.",
)
_SYNDROME_ORBIT = (
    "The supplied orbit is assumed to give distinct syndromes of one matrix, "
    "with solutions mapping back to the original decoding instance."
)


def _block_profile(entry, goal, *, composite=False, doom="auto"):
    scheme, p = entry["scheme"], entry["parameters"]
    key = goal == "key_recovery"
    if scheme in ("QCTM", "UVW-KEM"):
        return None
    if scheme in ("BIKE_MLThre", "TRIKE"):
        if not key:
            return None  # The message error has only a prescribed total weight.
        weights = [p["dv"]]*2 if scheme == "BIKE_MLThre" else [p["d"]]*3
    elif scheme == "Mito":
        weights = list(p["wx"]+p["wy"] if key else p["wr"]+p["wt"])
    elif scheme == "QUBE":
        weights = [p["wx"], p["wx"], p["wy"]] if key else [p["wf"], p["wf"], p["wg"]]
    elif key:
        weights = [p["wx"], p["wy"]] if scheme == "TriQ-KEM" else [p.get("w", p.get("wsk"))]*2
    else:
        weights = [p["wr1"], p["wr2"]] if scheme == "NSS-HQC" else [p["wr"]]*2
    if composite:
        weights.append(p["we"])
    permutations = ()
    if scheme == "Mito" and not composite and doom == "auto":
        d = p["d"]
        permutations = tuple(tuple(i ^ shift for i in range(d))
                             + tuple(d+(i ^ shift) for i in range(d)) for shift in range(d))
    return BlockProfile((p["r"],)*len(weights), tuple(weights), permutations)


def _mito_parity_key(entry: dict, baseline: AttackInstance) -> AttackInstance:
    """Cost the exact augmented rank using an explicitly random SD proxy.

    The public matrix is not random: its added rows are block parity checks.
    The generic backend receives only the declared cost proxy, while the
    source equations and approximation remain part of the exported instance.
    """
    p = entry["parameters"]
    parity = MitoKeyParity(p["r"], p["d"], p["wx"], p["wy"])
    proxy = {
        "name": "mito-key-parity-rank-v1", "heuristic": True,
        "source_model": "Mito P fixed-weight key with public block parities",
        "effective_model": "random full-rank binary SD",
        "baseline_parameters": dict(baseline.problem.parameters),
        "effective_parameters": {"n": parity.n, "k": parity.k, "w": parity.w, "q": 2},
        "constraints": parity.to_dict(),
        "source_targets": baseline.targets,
        "target_action": "(s, parity_y) -> (P_g s, D_g parity_y)",
        "scope": "Exact augmented matrix rank; heuristic random-SD cost, not a dedicated structured P attack.",
    }
    assumptions = (*baseline.assumptions,
        "Uses the augmented rank in a random-code model; sparse parity rows and exact block weights are not modeled.",
        "Added rank need not provide independent information under fixed-weight constraints.",
    )
    if baseline.tags == ("doom:qcsd",):
        assumptions += (
            "The target orbit must transform the full augmented syndrome, including its parity labels.",
        )
    return replace(
        baseline, name=f"{entry['parameter_set']}/key_recovery/parity", route_id="parity",
        problem=Problem("sd", proxy["effective_parameters"], log2_solutions=0),
        route="Mito P parity rank model: (n,k,w)=(2dr,dr-d,sum(wx_i)+sum(wy_i))",
        cost_proxy=proxy, block_profile=None,
        assumptions=assumptions,
    )


def _composite_message(entry: dict, *, doom: str) -> AttackInstance:
    """Full-length joint core; message masking is free by explicit convention.

    Mito retains its single-component Pr map: e and v have r coordinates,
    whereas its two ephemeral vectors each have d*r coordinates.
    """
    scheme, parameter_set, p = entry["scheme"], entry["parameter_set"], entry["parameters"]
    r = p["r"]
    if scheme == "Mito":
        n, k = (2 * p["d"] + 1) * r, p["d"] * r
        w = sum(p["wr"]) + sum(p["wt"]) + p["we"]
        formula = "((2d+1)r,dr,sum(wr_i)+sum(wt_i)+we)"
    elif scheme == "QUBE":
        n, k, w = 4 * r, 2 * r, 2 * p["wf"] + p["wg"] + p["we"]
        formula = "(4r,2r,2wf+wg+we)"
    else:
        n, k = 3 * r, r
        w = (p["wr1"] + p["wr2"] if scheme == "NSS-HQC" else 2 * p["wr"]) + p["we"]
        formula = "(3r,r,wr1+wr2+we)" if scheme == "NSS-HQC" else "(3r,r,2wr+we)"
    assumptions = (*_ASSUMPTIONS, *_COMPOSITE_MSG_ASSUMPTIONS)
    targets, tags = (r, ("doom:qcsd",)) if doom == "auto" else (1, ())
    if doom == "auto":
        assumptions += (_SYNDROME_ORBIT,)
        if scheme == "Mito":
            assumptions += (
                "Only simultaneous cyclic shifts are used; dyadic shifts do not preserve the published component.",
            )
    else:
        assumptions += (SINGLE_SYNDROME,)
    return AttackInstance(
        name=f"{parameter_set}/msg_recovery/composite", route_id="composite",
        scheme=scheme, parameter_set=parameter_set, goal="msg_recovery",
        problem=Problem("sd", {"n": n, "k": k, "w": w, "q": 2}, log2_solutions=0),
        route=f"Composite message core: (n,k,w)={formula}",
        targets=targets, tags=tags, assumptions=assumptions,
        block_profile=_block_profile(entry, "msg_recovery", composite=True, doom=doom),
        references=tuple(entry["references"]),
    )


def hamming_catalogue() -> list[dict]:
    """Return independent records with source parameters and provenance."""
    return deepcopy(HAMMING_PARAMETERS)


class HammingScheme:
    """Adapt one submission's parameter sets to the explicitly simplified routes.

    Composite-capable message sets return u_only followed by composite; estimate
    each route and use compare_routes for independent per-family selections.
    Mito key sets return baseline followed by the explicit parity rank proxy.
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

    def instances(self, parameter_set: str, goal: str, *, doom: str = "auto",
                  unbalanced: str = "auto") -> list[AttackInstance]:
        if doom not in DOOM_MODES:
            raise ValueError("doom must be auto or none")
        if unbalanced not in UNBALANCED_MODES:
            raise ValueError("unbalanced must be auto or none")
        if goal not in GOALS:
            raise ValueError("goal must be key_recovery or msg_recovery")
        if parameter_set not in self.parameter_sets:
            raise ValueError(f"Unknown parameter set {parameter_set!r} for {self.scheme}; choose from {', '.join(self.parameter_sets)}")
        entry = next(row for row in HAMMING_PARAMETERS
                     if row["scheme"] == self.scheme and row["parameter_set"] == parameter_set)
        p = entry["parameters"]
        key = goal == "key_recovery"
        scheme = self.scheme
        assumptions = _ASSUMPTIONS
        targets, tags = 1, ()
        references = tuple(entry["references"])

        if key and scheme in ("QCTM", "UVW-KEM"):
            reason = (
                "No supported key-recovery ISD reduction for QCTM; structural key attacks are outside this model."
                if scheme == "QCTM" else
                "UVW-KEM key recovery requires distinguishing (u,u)D codewords and a weight-dependent codeword-count analysis; "
                "no single fixed SD instance is modeled."
            )
            problem = Problem("structural_key_recovery", {})
            route = reason
            assumptions = ()
        else:
            q = p.get("q", 2)
            if scheme == "BIKE_MLThre":
                n, k, w = 2 * p["r"], p["r"], p["w"] if key else p["t"]
                formula = "(2r,r,w)" if key else "(2r,r,t)"
            elif scheme == "TRIKE":
                n, k, w = 3 * p["r"], (2 if key else 1) * p["r"], p["w"] if key else p["t"]
                formula = "(3r,2r,w)" if key else "(3r,r,t)"
            elif scheme in ("HARE", "HEP-QC", "HQC"):
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
            label = "Key recovery" if key else (
                "Message recovery from u" if scheme in COMPOSITE_MSG_SCHEMES else "Message recovery"
            )
            route = f"{label}: (n,k,w)={formula}"
            if doom == "auto" and scheme != "UVW-KEM":
                codewords = key and scheme in ("BIKE_MLThre", "TRIKE")
                if scheme == "Mito":
                    targets = p["d"] * p["r"]
                elif scheme == "QCTM":
                    targets = p["ell"]
                else:
                    targets = p["r"]
                tags = ("doom:qccf" if codewords else "doom:qcsd",)
                if codewords:
                    problem = Problem("cfp", dict(problem.parameters))
                    if scheme == "BIKE_MLThre":
                        orbit = "Invertible h0 gives distinct nonzero cyclic shifts yielding equivalent keys"
                    else:
                        orbit = "The supplied orbit is assumed to give distinct nonzero codewords yielding equivalent keys"
                    assumptions += (orbit + "; other low-weight codewords may not recover a key.",)
                else:
                    assumptions += (_SYNDROME_ORBIT,)
                if scheme == "QCTM":
                    assumptions += (
                        "The target orbit must preserve the full hybrid parity-check space, "
                        "including non-circulant tail rows.",
                    )
            else:
                assumptions += (SINGLE_SYNDROME,)
            if key and not tags and scheme in ("BIKE_MLThre", "TRIKE"):
                assumptions = (*assumptions, _KEY_ASSUMPTION)
            if not key and scheme in COMPOSITE_MSG_SCHEMES:
                assumptions += (
                    "Uses the complete u equation to recover ephemeral randomness; v and the unknown message are not inputs.",
                )

        composite = not key and scheme in COMPOSITE_MSG_SCHEMES
        mito_key = key and scheme == "Mito"
        route_id = "u_only" if composite else "baseline" if mito_key else None
        instances = [AttackInstance(
            name=f"{parameter_set}/{goal}" + (f"/{route_id}" if route_id else ""),
            route_id=route_id,
            scheme=scheme, parameter_set=parameter_set,
            goal=goal, problem=problem, route=route, targets=targets, tags=tags,
            assumptions=assumptions, references=references,
            block_profile=_block_profile(entry, goal, doom=doom),
        )]
        if composite:
            instances.append(_composite_message(entry, doom=doom))
        if mito_key:
            instances.append(_mito_parity_key(entry, instances[0]))
        configured = []
        for instance in instances:
            profile = instance.block_profile if unbalanced == "auto" else None
            notes = instance.assumptions
            if scheme == "HQC":
                notes += (
                    "Estimator example using HQC specification 2026-10-12; these are decoding subproblem costs, not claimed HQC security levels.",
                    "The public fixed-weight parities are not used to reduce the generic SD dimensions.",
                )
                if key:
                    notes += (
                        "Recovers a sparse pair (x,y) from s=x+h*y; recovery of the compressed seedKEM is not modeled.",
                    )
                elif instance.route_id == "u_only":
                    notes += (
                        "After recovering r2, message recovery still requires public concatenated-code decoding of v-Truncate(s*r2) and candidate validation; this postprocessing cost is not included.",
                    )
                else:
                    notes += (
                        "HQC transmits only L=code_length coordinates of v; the missing r-L tail and the message mask Encode(m) are supplied for free in this conditional full-length core.",
                        "The r cyclic targets belong only to that supplied core; they are not a DOOM orbit of the actual truncated unknown-message ciphertext.",
                    )
                    instance = replace(instance, route="Conditional full-length known-mask core: (n,k,w)=(3r,r,2wr+we)")
            if scheme == "HEP-QC":
                if key:
                    notes += (
                        "Recovers only the sparse secret pair (x,y) from s=x+h*y; the secret scrambler T and permutation P are not recovered.",
                        "This sparse-key subproblem is not a complete HEP-QC private-key or decryption recovery estimate.",
                    )
                    instance = replace(instance, route="Sparse-key subproblem: (n,k,w)=(2r,r,2w); excludes T and P")
                elif instance.route_id == "u_only":
                    notes += (
                        "After recovering r2, message recovery still requires decoding v-Truncate(s*r2) under the public masked generator G'_L and validating the candidate; this residual low-rate decoding cost is not included.",
                    )
                else:
                    notes += (
                        "HEP-QC transmits only L=code_length coordinates of v; the missing r-L tail and the full message mask m*G' are supplied for free in this conditional full-length core.",
                        "The r cyclic targets belong only to that supplied core; they are not a DOOM orbit of the actual truncated unknown-message ciphertext or its projection through G'_L.",
                    )
                    instance = replace(instance, route="Conditional full-length known-mask core: (n,k,w)=(3r,r,2wr+we)")
            if scheme == "TriQ-KEM" and not key:
                notes += (
                    "TriQ-KEM's bounded-density sampler is approximated by fixed-weight sampling; window constraints and retry limits are not modeled.",
                )
            configured.append(replace(instance, block_profile=profile, assumptions=notes))
        return configured


def hamming_instances(*, schemes=None, parameter_sets=None, goal="both", doom="auto",
                      unbalanced="auto") -> list[AttackInstance]:
    """Select all candidate routes; reject incompatible filters before costing."""
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
            for selected_goal in goals for instance in adapter.instances(
                name, selected_goal, doom=doom, unbalanced=unbalanced)]
