"""Submission decoding routes with scheme-specific DOOM target semantics.

The parameter catalogue contains a self-contained, reviewed parameter snapshot.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from .hamming_parameters import HAMMING_PARAMETERS
from .models import AttackInstance, Problem
from .mito_parity import MitoKeyParity
from .unbalanced import BlockProfile


HAMMING_SCHEMES = (
    "BIKE_MLThre", "TRIKE", "HARE", "NSS-HQC", "TriQ-KEM", "Mito", "QUBE",
    "QCTM", "UVW-KEM",
)
GOALS = ("key_recovery", "msg_recovery")
# Resolve all classical candidates in the appropriate upstream field backend.
DEFAULT_HAMMING_ALGORITHMS = None
DOOM_MODES = ("auto", "none")
UNBALANCED_MODES = ("auto", "none")
COMPOSITE_MSG_SCHEMES = ("HARE", "NSS-HQC", "TriQ-KEM", "Mito", "QUBE")

_ASSUMPTIONS = (
    "Generic ISD cost proxy for the documented recovery route; not a whole-scheme security estimate.",
    "Unbalanced outer selection uses known block weights where supported; inner structured lists, "
    "cross-block support relations and structure-dependent rank probabilities are not modeled.",
    "Recovery postprocessing, candidate verification and their success probabilities are not costed.",
)
_KEY_ASSUMPTION = (
    "For this preliminary key route, ordinary SD cost is used as a proxy for finding the designated nonzero low-weight secret. "
    "This is not a dedicated homogeneous codeword-finding model or a proof that any low-weight word recovers the key."
)
_MSG_ASSUMPTIONS = (
    "Message-route comparison ignores ciphertext truncation and unknown-message costs: "
    "no message guessing, message-code dimension penalty or message-elimination cost is charged.",
    "Composite estimates use the full uncompressed core and treat v-Encode(m) as available for free. "
    "Compression/quantization residuals are not modeled; this is a simplified cost proxy, "
    "not a reduction from the actual unknown-message ciphertext.",
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
    return replace(
        baseline, name=f"{entry['parameter_set']}/key_recovery/parity", route_id="parity",
        problem=Problem("sd", proxy["effective_parameters"], log2_solutions=0),
        route="Mito P parity rank model: (n,k,w)=(2dr,dr-d,sum(wx_i)+sum(wy_i))",
        cost_proxy=proxy, block_profile=None,
        assumptions=(*baseline.assumptions,
            "The augmented binary matrix has exact rank d*r+d. Generic ISD costs approximate it by "
            "a random full-rank SD matrix; sparse parity-row effects on pivots and lists are not modeled.",
            "x and y are independently sampled with their exact block weights and pairwise disjoint "
            "supports within each tuple (S^D), not uniformly from a parity slice R[b]. "
            "Block parities are retained in the source system; exact weights and disjointness are relaxed in the cost proxy.",
            "E*A_h=B_h*E with (B_h)_{ij}=E(h)_{i xor j}; E*x=wx mod 2 follows from "
            "the public syndrome and E*y=wy mod 2, so appending x parity adds no further rank.",
            "All 2*d*r binary coordinates and total weight are preserved. There is no extra d-bit, "
            "collapse or CombGap discount; ambient rank gain need not equal independent information on a fixed-weight domain.",
            "DOOM transforms the entire syndrome (s,parity_y) to (P_g*s,D_g*parity_y); "
            "dyadic shifts permute parity labels. The full d*r orbit is a proxy assumption, not guaranteed distinct targets.",
            "This generic cost model of P supplies neither a search/decision reduction "
            "nor an optimality proof for generic ISD and excludes square/folding/lifting attacks.",
            "Unbalanced outer selection is not combined with this parity-rank proxy: "
            "the additional parity rows and exact block weights require a joint rank-conditioned model.",
        ),
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
        equation = "u=a+A_h*t; v-Encode(m)=B_s*t+e, B_s=[Cir(s_0)...Cir(s_(d-1))]"
    elif scheme == "QUBE":
        n, k, w = 4 * r, 2 * r, 2 * p["wf"] + p["wg"] + p["we"]
        formula = "(4r,2r,2wf+wg+we)"
        equation = "u=g+h1*f1+h2*f2; v-Encode(m)=s1*f1+s2*f2+e"
    else:
        n, k = 3 * r, r
        w = (p["wr1"] + p["wr2"] if scheme == "NSS-HQC" else 2 * p["wr"]) + p["we"]
        formula = "(3r,r,wr1+wr2+we)" if scheme == "NSS-HQC" else "(3r,r,2wr+we)"
        equation = "u=r1+h*r2; v-Encode(m)=s*r2+e"
    assumptions = (*_ASSUMPTIONS, *entry.get("notes", ()), *_MSG_ASSUMPTIONS,
                   f"Joint core equations: {equation}.",
                   "Identity blocks for the first ephemeral vector and e give full row rank; "
                   "one designated acceptable solution per syndrome (log2_solutions=0). "
                   "Fixed block weights enter supported outer probabilities; parity and disjoint supports "
                   "receive no additional discount.")
    if scheme == "Mito":
        assumptions += (
            "Only truncation is removed: Pr still publishes one ring component, with one r-bit e. "
            "The joint matrix has (d+1)r rows and (2d+1)r columns. Dyadic shifts do not preserve "
            "the published second component, so only the cyclic orbit of size r is used, not d*r.",
        )
    targets, tags = (r, ("doom:qcsd",)) if doom == "auto" else (1, ())
    if doom == "auto":
        assumptions += (
            f"QCSD joint-core proxy: simultaneous cyclic shifts of every r-bit block preserve the "
            f"same public matrix and total weight. Full usable orbit assumed: M={r}; duplicate "
            "syndromes and orbit correlations are not modeled. Inverse shifts recover the original candidate.",
        )
    else:
        assumptions += ("Single target; no DOOM or multiple-solution speedup.",)
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
        assumptions = (*_ASSUMPTIONS, *entry.get("notes", ()))
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
                    assumptions += (
                        "QCCF cost proxy: targets counts distinct acceptable nonzero cyclic shifts of the secret "
                        "under one zero syndrome, not distinct syndromes; no extra target discount is applied.",
                        "An orbit member is assumed to yield a usable equivalent key after recovery/verification; "
                        "arbitrary low-weight codewords need not do so.",
                    )
                else:
                    assumptions += (
                        "QCSD cost proxy: targets counts distinct syndromes under one public matrix; "
                        "log2_solutions=0 designates one acceptable solution per syndrome. "
                        "Inverse automorphism maps a recovered target solution back to the original equation.",
                    )
                if scheme == "BIKE_MLThre" and key:
                    assumptions += (
                        f"The planted secret has exactly r={targets} distinct cyclic shifts: h0 is invertible "
                        "in F2[X]/(X^r-1). Their public ratio and block weights are preserved; "
                        "orbit correlations are not modeled.",
                    )
                else:
                    assumptions += (
                        f"Full usable orbit assumed: M={targets}; parameter snapshots do not contain concrete "
                        "syndromes/keys to check stabilizers or duplicate targets. Shorter orbits require a smaller "
                        "targets value in an explicit AttackInstance. Orbit correlations are not modeled.",
                    )
                if scheme == "Mito":
                    assumptions += (
                        "Mito uses the full C_r x (C_2)^ell action of size d*r, d=2^ell; "
                        "dyadic shifts permute block-weight labels and preserve total weight. "
                        "The QCSD backend is a syndrome-target proxy for this QDSD orbit, not a folded attack.",
                    )
                elif scheme == "QCTM":
                    assumptions += (
                        "QCTM uses automorphism order ell=19, not n or n/ell; syndrome transforms must retain "
                        "the entire hybrid parity-check space, including the non-circulant tail rows.",
                    )
                elif scheme == "NSS-HQC":
                    assumptions += (
                        "The target orbit is derived from the full public QC equations; "
                        "the NSS-HQC specification does not explicitly apply a DOOM discount.",
                    )
            else:
                assumptions += (
                    "Single target and one designated acceptable solution (log2_solutions=0); "
                    "no DOOM, QC orbit or multiple-solution speedup.",
                )
                if scheme == "UVW-KEM":
                    assumptions += (
                        "UVW-KEM has no documented public QC automorphism supplying free targets; "
                        "the hidden monomial transformation does not supply a DOOM orbit.",
                    )
            if key and not tags and scheme in ("BIKE_MLThre", "TRIKE"):
                assumptions = (*assumptions, _KEY_ASSUMPTION)
            if not key and scheme in COMPOSITE_MSG_SCHEMES:
                assumptions += _MSG_ASSUMPTIONS
                assumptions += (
                    "This message route uses only the complete u equation to recover ephemeral randomness; "
                    "public decoding/decompression and candidate verification remain necessary. "
                    "The orbit count is not asserted for the truncated/compressed joint ciphertext problem.",
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
        if unbalanced == "none":
            instances = [replace(i, block_profile=None, assumptions=(*i.assumptions,
                         "Unbalanced outer selection disabled; only total weight enters the estimator."))
                         for i in instances]
        return instances


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
