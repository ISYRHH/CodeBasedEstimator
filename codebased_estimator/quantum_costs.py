"""Ka17 finite-parameter *time* budgets for QSS and QMMT+.

This is the ordered-list, average-load heuristic in
docs/quantum_model.md, not a gate count or a proven
runtime bound. All costs and probabilities in ``details`` are base-2 logs;
zero static output counts and their zero index cost are represented by None.
The evaluator is independent of CryptographicEstimators and of the optimizer.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import ceil, comb, expm1, floor, fsum, inf, isfinite, isqrt, lgamma, log, log1p, log2
from typing import Any, Optional

from .list_costs import ce_ordered_merge_cost, setup_list_sizes
from .matrix_costs import DEFAULT_MATRIX_PROFILE, matrix_budget, validate_profile
from .quantum_search import SEARCH_VERSION, refine_candidates


COST_MODEL = "ka17-ce-ordered-average-v2"
OUTER_PROBABILITY_MODEL = "independent-solution-union-v1"
_ALGORITHMS = ("QSS", "QMMT+")
_LN2 = log(2)


@dataclass(frozen=True)
class QuantumCost:
    time_log2: float
    parameters: dict[str, Any]
    details: dict[str, Optional[float]]
    search: dict[str, Any] = field(default_factory=dict)
    matrix: dict[str, Any] = field(default_factory=dict)


def _logsum(*values: float) -> float:
    largest = max(values)
    if largest == -inf:
        return -inf
    return largest + log2(fsum(2.0 ** (x - largest) for x in values))


def _logcomb(n: int, k: int) -> float:
    """Finite binomial coefficients, not entropy approximations."""
    if not 0 <= k <= n:
        return -inf
    k = min(k, n - k)
    if k <= 128 or n <= 512:
        return log2(comb(n, k))
    return (lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)) / _LN2


def _L(numerator: int, exponent: int = 0) -> int:
    """Exactly ceil(log2(2 + numerator / 2**exponent)); no float rounding.

    All lengths here are strictly positive. Tiny expected lists still have
    L=2, even if converting the expectation to float would underflow to zero.
    """
    if numerator.bit_length() <= exponent:
        return 2
    return (numerator + (1 << (exponent + 1)) - 1).bit_length() - exponent


def _integer_exp2(x: float) -> int:
    """Round 2**x to an integer without overflowing binary64."""
    if x < 52:
        return max(1, round(2.0 ** x))
    whole = floor(x)
    return round(2.0 ** (x - whole + 52)) << (whole - 52)


def _validate(n: int, k: int, w: int, algorithm: str) -> None:
    if algorithm not in _ALGORITHMS:
        raise ValueError(f"algorithm must be one of {_ALGORITHMS}")
    if any(type(x) is not int for x in (n, k, w)) or not (0 < k < n and 1 <= w <= n - k):
        raise ValueError("require integer parameters 0 < k < n and 1 <= w <= n-k")


def _validate_solutions(log2_solutions: float, codeword_finding: bool) -> None:
    try:
        valid = (not isinstance(log2_solutions, bool)
                 and isinstance(log2_solutions, (int, float))
                 and isfinite(log2_solutions) and log2_solutions >= 0)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("log2_solutions must be finite and nonnegative")
    if type(codeword_finding) is not bool:
        raise ValueError("codeword_finding must be a boolean")


def _log_solution_union(log2_q: float, log2_solutions: float) -> float:
    """Log2(1-(1-q)**M), without materializing M or an underflowing q.

    The hazard h=-log(1-q) gives union=1-exp(-M*h). Below 2**-54,
    replacing -log(1-q) by q (and 1-exp(-x) by x) loses less than a
    binary64 unit of relative precision. The exact M=1 path is retained.
    """
    if log2_solutions == 0 or log2_q in (-inf, 0.0):
        return log2_q
    if log2_q < -54:
        log2_hazard = log2_q
    else:
        q = 2.0 ** log2_q
        if q == 1.0:
            return 0.0
        log2_hazard = log2(-log1p(-q))
    log2_exponent = log2_solutions + log2_hazard
    if log2_exponent < -54:
        return log2_exponent
    if log2_exponent > 10:
        return 0.0
    return log2(-expm1(-(2.0 ** log2_exponent)))


class _Model:
    def __init__(self, n: int, k: int, w: int, algorithm: str,
                 matrix_profile: str = DEFAULT_MATRIX_PROFILE, *,
                 log2_solutions: float = 0.0, codeword_finding: bool = False):
        _validate(n, k, w, algorithm)
        _validate_solutions(log2_solutions, codeword_finding)
        self.log2_solutions = log2_solutions
        self.codeword_finding = codeword_finding
        self.matrix_profile = validate_profile(matrix_profile)
        self.n, self.k, self.w, self.algorithm = n, k, w, algorithm
        self.m = n - k
        self.log_n = log2(n)
        self.log_nw = _logcomb(n, w)
        # h(j)=log2(1-2^-j). Terms beyond 1074 underflow even in binary64;
        # the omitted tail is below its smallest representable positive value.
        end = min(n, 1074)
        tail = [0.0] * (end + 2)
        for j in range(end, 0, -1):
            tail[j] = tail[j + 1] + log1p(-2.0 ** (-j)) / _LN2
        self.rank_tail = tail
        self.shape_cache: dict[tuple[int, int, int], dict[str, Any]] = {}

    def probability(self, log2_P, log2_rho, log2_sigma=0.0):
        """Independent-solution proxy; the common rank event stays outside."""
        single = log2_P + log2_rho + log2_sigma
        q = log2_P + log2_sigma
        union = _log_solution_union(q, self.log2_solutions)
        effective = single if self.log2_solutions == 0 else log2_rho + union
        return dict(log2_solutions=self.log2_solutions,
                    log2_P_eff_single=single, log2_q_single=q,
                    log2_outer_occupancy=self.log2_solutions + q,
                    log2_q_multi=union, log2_P_eff_model=effective)

    def rho(self, ell: int) -> float:
        def tail(j):
            return self.rank_tail[j] if j < len(self.rank_tail) else 0.0
        # Cancel the overlapping products in Eq. (7) before evaluation.
        value = tail(ell + 1) - tail(self.m + 1) - tail(self.k + ell + 1) + tail(self.n + 1)
        return min(0.0, value)

    def gauss(self, ell: int) -> float:
        if self.matrix_profile != DEFAULT_MATRIX_PROFILE:
            return log2(matrix_budget(self.n, self.k, ell, self.matrix_profile).total)
        return log2(self.m * (self.m - ell) + self.m * _L(self.n) ** 2 + self.n)

    def shape(self, ell: int, p: int, d: int) -> Optional[dict[str, Any]]:
        key = (ell, p, d)
        if key in self.shape_cache:
            return self.shape_cache[key]
        K, r = self.k + ell, self.m - ell
        if not (0 <= ell <= self.m and 0 < p < K and p <= self.w and 0 <= self.w - p <= r and p % 4 == 0):
            return None
        if self.algorithm == "QSS":
            if K % 4 or d:
                return None
            q, t = K // 4, p // 4
            R = 1
        else:
            if K % 2 or d < 0 or d % 2 or d > K - p:
                return None
            q, t = K // 2, p // 4 + d // 2
            R = (comb(p // 2, p // 4) * comb(q - p // 2, d // 2)) ** 2
        V = comb(q, t)
        lv, lr = log2(V), log2(R)
        lp = (4 * lv if self.algorithm == "QSS" else 2 * _logcomb(q, p // 2)) + _logcomb(r, self.w - p) - self.log_nw
        shape = dict(V=V, R=R, log2_V=lv, log2_R=lr, log2_P=min(0.0, lp),
                     log2_rho=self.rho(ell), log2_G=self.gauss(ell),
                     log2_g_leaf=log2(1 + t + q * V.bit_length() / self.n),
                     log2_T0=log2((q + 1) ** 2 * (t + 1) + self.n * (self.m + 1)))
        self.shape_cache[key] = shape
        return shape

    def direct(self, ell: int, p: int) -> Optional[QuantumCost]:
        # With zero syndrome and a full-column-rank tail, e'=0 recovers only
        # the forbidden zero codeword. This family cannot find a nonzero word.
        if self.codeword_finding and p == 0:
            return None
        K, r = self.k + ell, self.m - ell
        if not (0 <= ell <= self.m and p in (0, K) and 0 <= self.w - p <= r):
            return None
        lp = min(0.0, _logcomb(r, self.w - p) - self.log_nw)
        lrho, lg = self.rho(ell), self.gauss(ell)
        lc, lt0 = log2(1 + p), log2(self.n * (self.m + 1))
        probability = self.probability(lp, lrho)
        time = _logsum(lt0, self.log_n - probability["log2_P_eff_model"] / 2 + _logsum(lg, lc))
        return QuantumCost(time, dict(ell=ell, p=p, d=0, u=1, a=0, b=0, branch="direct"),
                           dict(log2_P=lp, log2_rho=lrho, log2_sigma=0.0,
                                log2_G=lg, log2_Q=lc, log2_T0=lt0,
                                log2_direct_check=lc, **probability))

    def walk_budget(self, sh: dict[str, Any], ell: int, u: int, f: int) -> dict[str, Optional[float]]:
        lu = log2(u)
        d1, d2 = 2 * lu - f, 4 * lu - ell - f
        eta1, eta2 = lu - f, 2 * lu - ell
        u2 = u * u
        l_u, l_d1, l_d2 = _L(u), _L(u2, f), _L(u2 * u2, ell + f)
        # Static construction uses CE's integer proxies and ordered primitive.
        # These are separate from the mean loads used by dynamic updates below.
        setup_size, setup_outputs = setup_list_sizes(u, f, ell)
        merge1 = log2(ce_ordered_merge_cost(u, f))
        merge2 = log2(ce_ordered_merge_cost(setup_size, ell - f))
        setup_index = (log2(setup_outputs) + log2(_L(setup_outputs))
                       if setup_outputs else -inf)
        ls = _logsum(2 + lu + sh["log2_g_leaf"], 1 + merge1,
                     merge2, setup_index)
        # Generate only the new leaf; the removed support and image are cached.
        # Matched-output processing uses one aggregate operation, and ordered
        # index maintenance remains an additional, algorithm-specific cost.
        update = _logsum(sh["log2_g_leaf"], 0.0,
                         1 + log2(l_u), 1 + eta1 + log2(1 + l_d1),
                         1 + eta1 + eta2 + log2(1 + l_d2))
        if u == sh["V"]:
            lq = _logsum(ls, 0.0)
            delta = None
        else:
            # u/V <= 1/2; cancellation and overflow are both avoided.
            ratio = 2.0 ** (lu - sh["log2_V"])
            inv_sqrt_delta = (3 + lu + log1p(-ratio) / _LN2) / 2
            lq = _logsum(ls, 2 * (sh["log2_V"] - lu) + _logsum(inv_sqrt_delta + update, 0.0))
            delta = -2 * inv_sqrt_delta
        details = {key: value for key, value in sh.items() if key.startswith("log2_")}
        details.update(log2_u=lu, log2_D1=d1, log2_D2=d2,
                       log2_eta1=eta1, log2_eta2=eta2,
                       log2_S=ls, log2_U=update, log2_C=0.0, log2_Q=lq,
                       log2_setup_list_size=log2(setup_size),
                       log2_setup_output_count=log2(setup_outputs) if setup_outputs else None,
                       log2_setup_merge_first=merge1, log2_setup_merge_last=merge2,
                       log2_setup_output_index=setup_index if setup_outputs else None)
        if delta is not None:
            details.update(log2_delta=delta, log2_epsilon_lower=4 * (lu - sh["log2_V"]))
        return details

    def finish(self, sh, details, ell, p, d, u, a, b) -> QuantumCost:
        # log2(R/(R+2^b-1)); use integer counts to preserve b=0 exactly.
        logsigma = 0.0 if b == 0 else -log1p(((1 << b) - 1) / sh["R"]) / _LN2
        probability = self.probability(sh["log2_P"], sh["log2_rho"], logsigma)
        lp = probability["log2_P_eff_model"]
        time = _logsum(sh["log2_T0"], self.log_n - lp / 2 +
                       _logsum(sh["log2_G"], a / 2 + details["log2_Q"]))
        return QuantumCost(time, dict(ell=ell, p=p, d=d, u=u, a=a, b=b,
                                      branch="full_list" if u == sh["V"] else "walk"),
                           dict(details, log2_sigma=logsigma, **probability))

    def evaluate(self, *, ell: int, p: int, d: int = 0, u: int = 1,
                 a: int = 0, b: int = 0) -> Optional[QuantumCost]:
        if any(type(x) is not int for x in (ell, p, d, u, a, b)):
            return None
        if not 0 <= ell <= self.m:
            return None
        if p in (0, self.k + ell):
            return self.direct(ell, p) if (d, u, a, b) == (0, 1, 0, 0) else None
        if min(a, b) < 0 or a + b > ell:
            return None
        sh = self.shape(ell, p, d)
        if sh is None or b > sh["R"].bit_length() - 1:
            return None
        V, f = sh["V"], a + b
        if u != V:
            if not (V > 1 and 1 <= u <= V // 2):
                return None
            # Exact integer inequalities implement ceil(log2 u) and ceil(2 log2 u).
            if (u - 1).bit_length() > f or (u * u - 1).bit_length() > ell:
                return None
        details = self.walk_budget(sh, ell, u, f)
        return self.finish(sh, details, ell, p, d, u, a, b)


def evaluate_parameters(n: int, k: int, w: int, algorithm: str, *, ell: int,
                        p: int, d: int = 0, u: int = 1, a: int = 0,
                        b: int = 0,
                        matrix_profile: str = DEFAULT_MATRIX_PROFILE,
                        log2_solutions: float = 0.0,
                        codeword_finding: bool = False) -> Optional[QuantumCost]:
    """Evaluate a specified integer point; infeasible points return None.

    Direct candidates are checked before leaf divisibility constraints. This
    function performs no search and supports the full documented parameter
    domain, including complete lists and arbitrary integer sublist sizes.
    The selected matrix profile deterministically minimizes its block width;
    pass the same profile when replaying a result. The default remains v2.
    Multiple solutions modify only the outer probability through an
    independent-event union; inner walk budgets are unchanged. Codeword
    finding excludes the p=0 direct family, which yields only the zero word.
    """
    model = _Model(n, k, w, algorithm, matrix_profile,
                   log2_solutions=log2_solutions, codeword_finding=codeword_finding)
    value = model.evaluate(ell=ell, p=p, d=d, u=u, a=a, b=b)
    return _with_matrix_metadata(value, n, k, matrix_profile)


def _with_matrix_metadata(cost, n, k, matrix_profile):
    # Leave the legacy record intact. Matrix decomposition is separate from
    # the frozen list/probability details, whose only changed entry is G.
    if cost is None or matrix_profile == DEFAULT_MATRIX_PROFILE:
        return cost
    budget = matrix_budget(n, k, cost.parameters["ell"], matrix_profile)
    metadata = budget.metadata()
    metadata.update(log2_G_core=log2(budget.core) if budget.core else None,
                    log2_G_prepare=log2(budget.preparation),
                    log2_G_total=log2(budget.total),
                    cost_unit="log2 vector_operations")
    return replace(cost, matrix=metadata)


def _grid(limit: int) -> list[int]:
    """A reproducible grid with dense small values and both endpoints."""
    if limit <= 16:
        return list(range(limit + 1))
    values = {round(limit * i / 8) for i in range(9)} | set(range(5))
    step = 1
    while step <= limit:
        values.update((step, limit - step))
        step *= 2
    return sorted(x for x in values if 0 <= x <= limit)


def _optimize(n: int, k: int, w: int, algorithm: str,
              matrix_profile: str = DEFAULT_MATRIX_PROFILE, *,
              log2_solutions: float = 0.0,
              codeword_finding: bool = False) -> Optional[QuantumCost]:
    """Exhaustive for n<=16; otherwise a deterministic multistart heuristic.

    Structural coordinates are ell, p/4 and d/2. Inner searches vary log2(u)
    and f; their endpoints include full lists. For one solution the integer
    split b uses the analytic stationary point and neighboring integers. For
    multiple solutions every feasible b is evaluated because saturation
    changes that stationary equation.
    A separately versioned, bounded integer-boundary pass refines the original
    large-instance result without changing the cost model or discarding it.
    No optimum over the full large-instance domain is claimed.
    """
    model = _Model(n, k, w, algorithm, matrix_profile,
                   log2_solutions=log2_solutions, codeword_finding=codeword_finding)
    m = n - k
    evaluated = 0
    best: Optional[QuantumCost] = None
    complete = n <= 16

    def consider(cost):
        nonlocal best, evaluated
        evaluated += 1
        if cost is not None and (best is None or cost.time_log2 < best.time_log2):
            best = cost
        return cost

    # The unique-candidate family is independent of the leaf domain.
    for endpoint in (False, True):
        if codeword_finding and not endpoint:
            continue
        upper = min(m, w - k) if endpoint else m - w
        if upper < 0:
            continue
        direct_points = []
        for ell in (range(upper + 1) if complete else _grid(upper)):
            c = consider(model.direct(ell, k + ell if endpoint else 0))
            if c is not None:
                direct_points.append(c)
        if not complete:
            for seed in sorted(direct_points, key=lambda c: c.time_log2)[:3]:
                current = seed
                step = max(1, upper // 4)
                while step:
                    for _ in range(8):
                        previous = current
                        for ell in (current.parameters["ell"] - step, current.parameters["ell"] + step):
                            if 0 <= ell <= upper:
                                c = consider(model.direct(ell, k + ell if endpoint else 0))
                                if c is not None and c.time_log2 < current.time_log2:
                                    current = c
                        if current is previous:
                            break
                    step //= 2

    stride = 4 if algorithm == "QSS" else 2
    offset = (-k) % stride
    ell_count = (m - offset) // stride

    def at(sh, ell, p, d, u, f):
        nonlocal evaluated
        details = model.walk_budget(sh, ell, u, f)
        bmax = min(f, sh["R"].bit_length() - 1)
        if bmax == 0:
            choices = (0,)
        elif complete or log2_solutions > 0:
            choices = range(bmax + 1)
        else:
            # With H=2^(f/2) Q, minimize sqrt(R-1+2^b)(G+H 2^(-b/2)).
            # Its only continuous stationary point has 2^(3b/2)=H(R-1)/G.
            center = (2 / 3) * (f / 2 + details["log2_Q"] + log2(sh["R"] - 1) - sh["log2_G"])
            choices = {0, bmax, max(0, min(bmax, floor(center))), max(0, min(bmax, ceil(center)))}
        candidates = [consider(model.finish(sh, details, ell, p, d, u, f - b, b)) for b in sorted(choices)]
        return min(candidates, key=lambda c: c.time_log2)

    shape_results: dict[tuple[int, int, int], Optional[QuantumCost]] = {}

    def search_shape(ell, p, d):
        key = (ell, p, d)
        if key in shape_results:
            return shape_results[key]
        K, r = k + ell, m - ell
        if not (0 <= ell <= m and K % stride == 0 and 0 < p < K and p <= w and p % 4 == 0
                and 0 <= w - p <= r and d >= 0 and d % 2 == 0 and d <= K - p):
            return None
        if algorithm == "QSS" and d:
            return None
        # Avoid constructing enormous binomial integers at shapes that cannot
        # improve the incumbent. The margin covers log-gamma roundoff. S>=u,
        # and the walk term >=V^2/u^(3/2), so Q>=V^(4/5). Complete lists cost >=V.
        q = K // stride
        t = p // 4 + (d // 2 if algorithm == "QMMT+" else 0)
        lv = _logcomb(q, t)
        lp = min(0.0, (4 * lv if algorithm == "QSS" else 2 * _logcomb(q, p // 2))
                 + _logcomb(r, w - p) - model.log_nw)
        upper_x = min(lv - 1, ell / 2)
        qbound = min(lv, max(.8 * lv, 2 * lv - 1.5 * upper_x))
        # sigma<=1 makes union(P) an upper bound on success for every b.
        # Keeping rho outside the union also preserves its common-event cap.
        lower = model.log_n - (_log_solution_union(lp, log2_solutions) + model.rho(ell)) / 2 + qbound
        if not complete and best is not None and lower > best.time_log2 + 1e-6:
            shape_results[key] = None
            return None
        sh = model.shape(ell, p, d)
        if sh is None:
            return None
        V = sh["V"]
        winner = None

        def update(cost):
            nonlocal winner
            if winner is None or cost.time_log2 < winner.time_log2:
                winner = cost

        if complete:
            for u in [*range(1, V // 2 + 1), V]:
                fmin = 0 if u == V else (u - 1).bit_length()
                if u != V and (u * u - 1).bit_length() > ell:
                    continue
                for f in range(fmin, ell + 1):
                    update(at(sh, ell, p, d, u, f))
        else:
            # Full-list endpoints have no low-fanout restrictions.
            full_best = None
            for f in sorted({0, ell, ell // 2, min(ell, sh["R"].bit_length() - 1)}):
                c = at(sh, ell, p, d, V, f)
                update(c)
                if full_best is None or c.time_log2 < full_best.time_log2:
                    full_best = c
            step = max(1, ell // 4)
            while step:
                for _ in range(4):
                    previous = full_best
                    f0 = full_best.parameters["a"] + full_best.parameters["b"]
                    for f in (f0 - step, f0 + step):
                        if 0 <= f <= ell:
                            c = at(sh, ell, p, d, V, f)
                            update(c)
                            if c.time_log2 < full_best.time_log2:
                                full_best = c
                    if full_best is previous:
                        break
                step //= 2
            if V > 1:
                # Exact integer square-root bound for u^2<=2^ell.
                umax = V // 2
                if (umax * umax - 1).bit_length() > ell:
                    umax = isqrt(1 << ell)
                xmax = log2(umax)
                seeds = []
                for x in sorted({0.0, xmax, xmax / 2, min(xmax, .8 * sh["log2_V"])}):
                    u = min(umax, _integer_exp2(x))
                    fmin = (u - 1).bit_length()
                    for f in sorted({fmin, ell, (ell + fmin) // 2,
                                     max(fmin, min(ell, sh["R"].bit_length() - 1))}):
                        c = at(sh, ell, p, d, u, f)
                        seeds.append(c)
                        update(c)
                # Refine both exponent and filter length. Near the winner also
                # test neighboring *integer* u, not only powers of two.
                for current in sorted(seeds, key=lambda c: c.time_log2)[:2]:
                    dx, df = max(1.0, xmax / 4), max(1, ell // 4)
                    while dx >= .125 or df >= 1:
                        for _ in range(4):
                            previous = current
                            u0 = current.parameters["u"]
                            x0 = log2(u0)
                            f0 = current.parameters["a"] + current.parameters["b"]
                            us = {u0, max(1, u0 - 1), min(umax, u0 + 1)}
                            if dx >= .125:
                                us.update(min(umax, _integer_exp2(max(0.0, min(xmax, x0 + sign * dx)))) for sign in (-1, 1))
                            for u in sorted(us):
                                fmin = (u - 1).bit_length()
                                fs = {max(fmin, f0), fmin}
                                if df:
                                    fs.update((max(fmin, f0 - df), min(ell, max(fmin, f0 + df))))
                                for f in sorted(fs):
                                    c = at(sh, ell, p, d, u, f)
                                    update(c)
                                    if c.time_log2 < current.time_log2:
                                        current = c
                            if current is previous:
                                break
                        dx /= 2
                        df //= 2
        shape_results[key] = winner
        return winner

    if complete:
        for ell in range(offset, m + 1, stride):
            K = k + ell
            for p in range(4, min(w, K - 1) + 1, 4):
                for d in (range(0, K - p + 1, 2) if algorithm == "QMMT+" else (0,)):
                    search_shape(ell, p, d)
    elif ell_count >= 0 and w >= 4:
        # Coarse structure seeds cover the entire domain; direct branches and
        # d=0 are always included. All refinement stays in the stated family.
        for ei in _grid(ell_count):
            ell = offset + stride * ei
            for pi in _grid(w // 4):
                p = 4 * pi
                if p == 0:
                    continue
                ds = (2 * di for di in _grid(max(0, (k + ell - p) // 2))) if algorithm == "QMMT+" else (0,)
                for d in ds:
                    search_shape(ell, p, d)
        seeds = sorted((c for c in shape_results.values() if c is not None), key=lambda c: c.time_log2)[:4]
        for current in seeds:
            scales = [max(1, ell_count // 4), max(1, w // 16), max(1, n // 8)]
            while any(scales):
                for _ in range(4):
                    previous = current
                    par = current.parameters
                    coords = [(par["ell"] - offset) // stride, par["p"] // 4, par["d"] // 2]
                    for axis in range(2 if algorithm == "QSS" else 3):
                        if not scales[axis]:
                            continue
                        for sign in (-1, 1):
                            trial = list(coords)
                            trial[axis] += sign * scales[axis]
                            c = search_shape(offset + stride * trial[0], 4 * trial[1], 2 * trial[2])
                            if c is not None and c.time_log2 < current.time_log2:
                                current = c
                    if current is previous:
                        break
                scales = [step // 2 for step in scales]
    if best is None:
        return None
    refinement = None
    if not complete:
        before = evaluated
        best, refinement = refine_candidates(
            model, [c for c in shape_results.values() if c is not None], best, at)
        refinement["cost_evaluations"] = evaluated - before
    search = dict(method="exhaustive_integer_domain" if complete else "deterministic_multistart",
                  version=SEARCH_VERSION, refinement=refinement,
                  global_optimum=complete, evaluated_points=evaluated,
                  baseline_structural_points=len(shape_results),
                  structural_points=len(set(shape_results) | set(model.shape_cache)),
                  parameter_domain="balanced Ka17 family with direct and full-list branches",
                  ell_range=[0, m], p_range=[0, min(w, n)],
                  inner_search="integer u and f" if complete else "baseline log2(u)/f search, then bounded integer-boundary refinement",
                  filter_split="enumerated" if complete or log2_solutions > 0 else "analytic stationary point and adjacent integers",
                  structural_seed_grid="all integers" if complete else "small values, dyadic offsets from both endpoints, and eighths of each structural axis",
                  refinement_starts=0 if complete else 4,
                  evaluations_include_revisits=True,
                  numeric_binomials="exact integer counts; log-gamma for large support probabilities and pruning",
                  memory_constraint_applied=False)
    return replace(best, search=search)


def _search_with_solution_retention(n, k, w, algorithm, matrix_profile,
                                    log2_solutions, codeword_finding):
    # Omit default kwargs to preserve the legacy callable/search contract.
    options = {"codeword_finding": True} if codeword_finding else {}
    if log2_solutions:
        options["log2_solutions"] = log2_solutions
    candidate = _optimize(n, k, w, algorithm, matrix_profile, **options)
    if log2_solutions == 0:
        return candidate
    single = _optimize(n, k, w, algorithm, matrix_profile,
                       **({"codeword_finding": True} if codeword_finding else {}))
    retained = None
    replay_evaluations = 0
    if single is not None:
        model = _Model(n, k, w, algorithm, matrix_profile,
                       log2_solutions=log2_solutions, codeword_finding=codeword_finding)
        par = single.parameters
        if par["branch"] == "direct":
            retained = model.direct(par["ell"], par["p"])
            replay_evaluations = 1
        else:
            ell, p, d, u = (par[key] for key in ("ell", "p", "d", "u"))
            f = par["a"] + par["b"]
            sh = model.shape(ell, p, d)
            details = model.walk_budget(sh, ell, u, f)
            # The single-solution stationary b need not minimize the union
            # model. Retain the original point and optimize its entire split.
            replay_evaluations = min(f, sh["R"].bit_length() - 1) + 1
            retained = min((model.finish(sh, details, ell, p, d, u, f - b, b)
                            for b in range(replay_evaluations)), key=lambda c: c.time_log2)
        retained = _with_matrix_metadata(retained, n, k, matrix_profile)
    available = [value for value in (retained, candidate) if value is not None]
    if not available:
        return None
    selected = min(available, key=lambda value: value.time_log2)
    search = dict(candidate.search if candidate is not None else single.search)
    single_evaluations = single.search["evaluated_points"] if single is not None else 0
    search.update(
        evaluated_points=(candidate.search["evaluated_points"] if candidate else 0)
                         + single_evaluations + replay_evaluations,
        single_solution_retention=dict(
            applied=retained is not None,
            single_time_log2=single.time_log2 if single is not None else None,
            single_parameters=dict(single.parameters) if single is not None else None,
            replayed_parameters=dict(retained.parameters) if retained is not None else None,
            replayed_time_log2=retained.time_log2 if retained is not None else None,
            multi_search_time_log2=candidate.time_log2 if candidate is not None else None,
            selected_from="single_replay" if selected is retained else "multi_search",
            single_search_evaluated_points=single_evaluations,
            replay_cost_evaluations=replay_evaluations,
        ),
    )
    if candidate is None:
        search["global_optimum"] = False
    return replace(selected, search=search)


def optimize(n: int, k: int, w: int, algorithm: str, *,
             matrix_profile: str = DEFAULT_MATRIX_PROFILE,
             log2_solutions: float = 0.0,
             codeword_finding: bool = False) -> Optional[QuantumCost]:
    """Optimize a versioned profile/probability model and retain baselines.

    The default follows the original v2 search unchanged. An opt-in profile
    reruns the same search with its new G, then replays the v2 winner under
    that profile. Keeping both candidates prevents changed heuristic paths
    from worsening the legacy result. Block-width optimization is complete;
    the large ISD parameter search remains the accepted heuristic.
    Multi-solution searches also retain the single-solution winner after
    replaying its cost and reoptimizing its filter split under the union model.
    """
    validate_profile(matrix_profile)
    _validate_solutions(log2_solutions, codeword_finding)
    candidate = _search_with_solution_retention(
        n, k, w, algorithm, matrix_profile, log2_solutions, codeword_finding)
    if matrix_profile == DEFAULT_MATRIX_PROFILE:
        return candidate
    legacy = _search_with_solution_retention(
        n, k, w, algorithm, DEFAULT_MATRIX_PROFILE, log2_solutions, codeword_finding)
    retained = None
    if legacy is not None:
        retained = evaluate_parameters(
            n, k, w, algorithm, matrix_profile=matrix_profile,
            log2_solutions=log2_solutions, codeword_finding=codeword_finding,
            **{key: value for key, value in legacy.parameters.items() if key != "branch"},
        )
    available = [value for value in (retained, candidate) if value is not None]
    if not available:
        return None
    selected = min(available, key=lambda value: value.time_log2)
    search = dict(candidate.search if candidate is not None else legacy.search)
    profile_evaluations = candidate.search["evaluated_points"] if candidate is not None else 0
    legacy_evaluations = legacy.search["evaluated_points"] if legacy is not None else 0
    search.update(matrix_profile=matrix_profile,
                  profile_search_evaluated_points=profile_evaluations,
                  evaluated_points=profile_evaluations + legacy_evaluations + int(retained is not None),
                  legacy_retention=dict(
                      applied=retained is not None,
                      legacy_cost_model=COST_MODEL,
                      legacy_time_log2=legacy.time_log2 if legacy is not None else None,
                      legacy_parameters=dict(legacy.parameters) if legacy is not None else None,
                      replayed_time_log2=retained.time_log2 if retained is not None else None,
                      profile_search_time_log2=candidate.time_log2 if candidate is not None else None,
                      selected_from="legacy_replay" if selected is retained else "profile_search",
                      legacy_search_evaluated_points=legacy_evaluations,
                      legacy_search=dict(legacy.search) if legacy is not None else None,
                      replay_cost_evaluations=int(retained is not None),
                  ))
    if candidate is None:
        search["global_optimum"] = False
    return _with_matrix_metadata(replace(selected, search=search), n, k, matrix_profile)
