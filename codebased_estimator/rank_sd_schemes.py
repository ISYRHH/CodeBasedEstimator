#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rank_sd_schemes.py — 五个秩度量候选算法的攻击复杂度评估（v3）

覆盖：BAG-Loong / BAG-Piglet / BRA / BRQC / C-Multi-UR-AG。
公式来源：各方案 "Algorithm specifications"；E 公式取自 ePrint 2025/668（定理 11）。
口径：Loong/Piglet ω=2.8；BRA/BRQC/C-Multi ω=2（各规范声明）。
"""
from math import comb, log2, ceil, floor, inf
from itertools import product
from functools import lru_cache

# ============================================================
# 基础工具
# ============================================================

def lg(x):
    return log2(x)

def lcomb(n, k):
    if n < 0 or k < 0 or k > n:
        return -inf
    v = comb(n, k)
    return log2(v) if v > 0 else -inf

def lcombv(n, k):
    if n < 0 or k < 0 or k > n:
        return 0
    return comb(n, k)

def log2_sum(terms):
    if not terms:
        return -inf
    mx = max(terms)
    return mx + log2(sum(2.0 ** (t - mx) for t in terms))

# ============================================================
# E：块状 MM 独立方程上界（ePrint 2025/668, Theorem 11）
# ============================================================

def E_minors(m, nvec, k, rvec):
    l = len(nvec)
    if len(rvec) != l:
        return None
    z = [0.0] * (l + 1)
    z[0] = -(k + 1)
    for i in range(1, l + 1):
        z[i] = sum(nvec[:i]) - (k + 1)
    for j in range(1, l + 1):
        base = l - j
        nA = sum(nvec[:base])
        if nA < k + 1 <= nA + rvec[base]:
            T = int(sum(rvec[:base]) - z[base])
            if T < 0:
                continue
            terms = []
            def recA(idx, remaining, acc):
                if idx == l:
                    if remaining == 0:
                        terms.append(acc)
                    return
                for nu in range(0, remaining + 1):
                    a, b = ((rvec[idx] + z[idx] + nu, z[idx + 1]) if idx == base
                            else (rvec[idx] + nu, nvec[idx]))
                    lv = lcomb(b, a)
                    if lv == -inf:
                        continue
                    recA(idx + 1, remaining - nu, acc + lv)
            recA(base, T, 0.0)
            if terms:
                mx = log2_sum(terms)
                if mx > -inf:
                    return lg(m) + mx, mx
        if nA + rvec[base] < k + 1 <= nA + nvec[base]:
            T = int(sum(rvec[:base + 1]))
            if T < 0:
                continue
            terms = []
            def recB(idx, remaining, acc):
                if idx == l:
                    if remaining == 0:
                        terms.append(acc)
                    return
                for nu in range(0, remaining + 1):
                    a, b = ((nu, z[idx + 1]) if idx == base
                            else (rvec[idx] + nu, nvec[idx]))
                    lv = lcomb(b, a)
                    if lv == -inf:
                        continue
                    recB(idx + 1, remaining - nu, acc + lv)
            recB(base, T, 0.0)
            if terms:
                mx = log2_sum(terms)
                if mx > -inf:
                    return lg(m) + mx, mx
    return None

# ============================================================
# C-Multi-UR-AG（RSL；ω=2）
# ============================================================

def cmulti_mm(m, n, k, r, omega=2.0):
    """单块 MM：T = q^{ar} · m·C(n-k-1,r) · C(n-a,r)^(ω-1)，可行性门槻 E >= U-1。

    2026-11-02 修复：原实现把成本写为 guess+logE+logU，漏乘 (ω-1)；
    ω=2 时两者一致，ω≠2 时会低估成本（外部审计项 B3）。
    """
    nn = n - k - 1
    if nn < r or n < r:
        return inf, None
    lhs = lg(m) + lcomb(nn, r)
    best, ba = inf, None
    for a in range(0, k + 1):
        if n - a < r:
            break
        if lhs < lcomb(n - a, r) - 1e-9:
            continue
        c = a * r * lg(2) + lg(m) + lcomb(nn, r) + (omega - 1) * lcomb(n - a, r)
        if c < best:
            best, ba = c, a
    return best, ba

def cmulti_sm(m, n, k, r, b, omega=2.0, amax=80, pmax=2):
    """SM-Fqm+（C-Multi §7.2）；给定 b，对 (a,p) 搜索。"""
    best, ba, bp = inf, None, None
    for p in range(0, pmax + 1):
        for a in range(0, amax + 1):
            nn, kk = n - a - p, k - a
            if kk <= 0 or nn - kk - 1 < r:
                continue
            terms = []
            for i1 in range(1, kk + 1):
                c1 = lcomb(kk - i1 + b - 1, b - 1)
                if c1 == -inf:
                    continue
                for i2 in range(i1 + 1, kk + 2):
                    c2 = lcomb(nn - i2, r - 1)
                    if c2 == -inf:
                        continue
                    terms.append(c1 + c2)
            if not terms:
                continue
            Ep = log2_sum(terms)
            sv = []
            for i in range(1, b + 1):
                v1 = lcomb(kk + b - i - 1, b - i)
                v2 = lcomb(nn - kk - 1, r + i)
                if v1 <= -inf / 2 or v2 <= -inf / 2:
                    continue
                sv.append(((-1) ** (i + 1), v1 + v2))
            pos = [v for s, v in sv if s > 0]
            neg = [v for s, v in sv if s < 0]
            Sp = log2_sum(pos) if pos else -inf
            Sn = log2_sum(neg) if neg else -inf
            Epv = 2.0 ** Ep
            if Sp > -inf:
                Epv -= (m - 1) * 2.0 ** Sp
            if Sn > -inf:
                Epv += (m - 1) * 2.0 ** Sn
            if Epv <= 0:
                continue
            Ev = log2(Epv)
            Uv = lcombv(kk + b - 1, b) * (lcombv(nn, r) - m * lcombv(nn - kk - 1, r))
            if Uv <= 0:
                continue
            U = log2(Uv)
            if Ev < U - 1e-9:
                continue
            c = a * r * lg(2) + 2 * lg(m) + Ev + (omega - 1) * U
            if c < best:
                best, ba, bp = c, a, p
    if best == inf:
        return None, None, None
    return best, ba, bp

def cmulti_sm_best(m, n, k, r, bmax=3, omega=2.0):
    best, bb, ba, bp = inf, None, None, None
    for b in range(1, bmax + 1):
        c, a, p = cmulti_sm(m, n, k, r, b, omega)
        if c is not None and c < best:
            best, bb, ba, bp = c, b, a, p
    return best, bb, ba, bp

# ============================================================
# BAG-Loong（ω=2.8）
# ============================================================

def loong_oj(n, n1, t1, t2, g, m, instance, omega=2.8):
    t = t1 + t2 - g
    pairs = [(n, t1, n, t2)] if instance == 1 else [(n, t1, n + n1, t2)]
    best = inf
    for (da, ta, db, tb) in pairs:
        for (d1, tA, d2, tB) in [(da, ta, db, tb), (db, tb, da, ta)]:
            expo = (d1 - tA) * (tA - 1) + tB
            poly = m * (t - 1) + (d1 - tA)
            best = min(best, omega * lg(poly) + expo * lg(2))
    return best

def loong_prr(n, n1, t1, t2, g, m, instance, omega=2.8):
    if instance == 1:
        d1, d2 = n, n
        N = d1 + d2
        best = inf
        if n >= m:
            for r1 in range(t1, m + 1):
                for r2 in range(t2, m + 1):
                    if r1 + r2 - g > m:
                        continue
                    if d1 * (r1 - g) + d2 * (r2 - g) > m * (N - 1):
                        continue
                    expo = t1 * (m - r1) + t2 * (m - r2) - m
                    best = min(best, omega * lg(m * (N - 1)) + expo * lg(2))
        else:
            S = N - (n + 1)
            for r1 in range(t1, d1 + 1):
                for r2 in range(t2, d2 + 1):
                    if (r1 - g) + (r2 - g) > S:
                        continue
                    if d1 * r1 + d2 * (r2 - g) > m * (S + g):
                        continue
                    expo = t1 * (d1 - r1) + t2 * (d2 - r2)
                    best = min(best, omega * lg(m * m * S) + expo * lg(2))
        return best
    else:
        d1, d2 = n, n + n1
        N = d1 + d2
        col1, col2 = d1 > m, d2 > m
        best = inf
        S = N - (n + 1)
        if col1 and col2:
            for r1 in range(t1, m + 1):
                for r2 in range(t2, m + 1):
                    if r1 + r2 - g > m:
                        continue
                    if d1 * (r1 - g) + d2 * (r2 - g) > m * (N - 1):
                        continue
                    expo = t1 * (m - r1) + t2 * (m - r2) - m
                    best = min(best, omega * lg(m * (N - 1)) + expo * lg(2))
        else:
            for r1 in range(t1, (m if col1 else d1) + 1):
                for r2 in range(t2, (m if col2 else d2) + 1):
                    if (r1 - g) + (r2 - g) > S:
                        continue
                    if d1 * r1 + d2 * (r2 - g) > m * S:
                        continue
                    expo = t1 * ((m - r1) if col1 else (d1 - r1)) \
                         + t2 * ((m - r2) if col2 else (d2 - r2))
                    if col1 or col2:
                        expo -= m
                    best = min(best, omega * lg(m * m * S) + expo * lg(2))
        return best

def loong_mm(n, n1, t1, t2, g, m, instance, omega=2.8):
    """BAG-Loong 定理 3.4 的块状 MM（混合块；ω=2.8）。

    2026-11-05 修复（外部审计项 B1）：方程计数 N2 的列数恢复为 Ncol = d2 - 1，
    即使用原码维数 k = d1（规范 Model 1 中增广码 C_y = C + <y> 的校验矩阵
    已扣除一维，本地旧版先写成 d1+1 又减 1，得到 d2-2，与定理 3.4 的
    N2 = C(d2-1, t) 相比多扣了一维）。修复后 8 个 Key/Message 值见
    schemes_final_output.txt 与 tex/audit2.tex。
    """
    if instance == 1:
        d1, d2 = n, n
    else:
        d1, d2 = n, n + n1
    t = t1 + t2 - g
    T2v = 0
    for i in range(t1 - g, t1 + 1):
        T2v += lcombv(d1, i) * lcombv(d2, t - i)
    if T2v <= 0:
        return None
    T2 = lg(T2v)
    Ncol = d2 - 1                     # B1：原码维数；增广已计入 -1，不再重复扣除
    if Ncol < t:
        return None
    N2 = lcomb(Ncol, t)
    mN2 = lg(m) + N2
    if mN2 >= T2 - 1e-9:
        return lg(m) + N2 + (omega - 1) * T2
    best = inf
    for a1 in range(0, d1 - t1 + 1):
        for a2 in range(0, d2 - t2 + 1):
            T2v2 = 0
            for i in range(t1 - g, t1 + 1):
                v = lcombv(d1 - a1, i) * lcombv(d2 - a2, t - i)
                T2v2 += v
            if T2v2 <= 0:
                continue
            T2a = lg(T2v2)
            if mN2 < T2a - 1e-9:
                continue
            gexp = a1 * t1 + a2 * t2
            c = gexp * lg(2) + lg(m) + N2 + (omega - 1) * T2a
            best = min(best, c)
    return best

def bra_mm_local_search(m, nvec, k, rvec, a0, p0, omega=2.0, pmax=40,
                        steps=(1, 2, 4, 8, 16)):
    """BRA/BRQC 块状 MM 的显式局部搜索模式（2026-11-05 外部审计项 C3 后新增）。

    从起点 (a0, p0) 做坐标下降：每轮沿一个猜零或穿刺坐标尝试 ±steps 的移动，
    接受通过 E >= U-1 门槛且降低成本的点，直到无改进为止。记录的搜索范围：
    0 <= a_i（Σa_i <= k），0 <= p_i <= pmax，h = 0，原始块序。这是有限
    启发式搜索，不声称全局最优；固定点复现模式（不搜索）仍由调用方保留。

    返回 (cost, a, p)；若起点与零元组均不可行，返回 (None, 0向量, 0向量)。
    """
    l = len(nvec)

    def cost(a, pp):
        r = bra_mm_at(m, nvec, k, rvec, a, pp, [0] * l)
        return None if r is None else r[0]

    cur_a, cur_p = [x for x in a0], [x for x in p0]
    best = cost(cur_a, cur_p)
    if best is None:
        cur_a, cur_p = [0] * l, [0] * l
        best = cost(cur_a, cur_p)
        if best is None:
            return None, cur_a, cur_p
    improved = True
    while improved:
        improved = False
        for i in range(l):
            for st in steps:
                for sgn in (1, -1):
                    a2 = list(cur_a)
                    a2[i] += sgn * st
                    if a2[i] < 0 or sum(a2) > k:
                        continue
                    c = cost(a2, cur_p)
                    if c is not None and c < best - 1e-9:
                        best, cur_a, improved = c, a2, True
            for st in steps:
                for sgn in (1, -1):
                    p2 = list(cur_p)
                    p2[i] += sgn * st
                    if p2[i] < 0 or p2[i] > pmax:
                        continue
                    c = cost(cur_a, p2)
                    if c is not None and c < best - 1e-9:
                        best, cur_p, improved = c, p2, True
    return best, cur_a, cur_p

# ============================================================
# BAG-Piglet（ω=2.8）
# ============================================================

def piglet_oj_31(n, t, m, omega=2.8):
    t1, t2, t3 = t
    tt = sum(t)
    expo = (n - t1) * (t1 - 1) + t3
    poly = m * (tt - 1) + (n - t1)
    return omega * lg(poly) + expo * lg(2)

def piglet_oj_42(n, t, m, omega=2.8):
    t1, t2, t3, t4 = t
    tt = sum(t)
    expo = (n - t1) * (t1 - 1) + (n - t2) * (t2 - 1) + t4
    poly = m * (tt - 1) + (n - t1) + (n - t2)
    return omega * lg(poly) + expo * lg(2)

def piglet_prr(n, t, m, ell, s, omega=2.8):
    l = len(t)
    best = inf
    if n >= m:
        # Case 1（列）：Σr ≤ m；ℳ = n·Σr ≤ m(ℓ-s-1)n
        rng = [range(t[i], m + 1) for i in range(l - 1)]
        for rp in product(*rng):
            rem = min(m - sum(rp), (m * (ell - s - 1) * n - n * sum(rp)) // n)
            if rem < t[l - 1]:
                continue
            r = rp + (rem,)
            expo = sum(t[i] * (m - r[i]) for i in range(l)) - m
            c = omega * lg(m * (ell - s - 1) * n) + expo * lg(2)
            best = min(best, c)
    if n <= m:
        # Case 2（行）
        rng = [range(t[i], n + 1) for i in range(l - 1)]
        for rp in product(*rng):
            rem = min(n - sum(rp), (ell - s - 1) * n - sum(rp))
            if rem < t[l - 1]:
                continue
            r = rp + (rem,)
            expo = sum(t[i] * (n - r[i]) for i in range(l))
            c = 2 * lg(m) + omega * lg((ell - s - 1) * n) + expo * lg(2)
            best = min(best, c)
    return best

def _mm_hybrid(prefix_caps, cost_at, N_expr, mN, omega, tvec):
    """通用：枚举前 l-1 个 a（上限 caps），最后一个取最小可行；返回最优。"""
    l = len(tvec)
    best = inf
    for ap in product(*[range(0, c + 1) for c in prefix_caps]):
        # 最小可行 a_last：扫描
        for al in range(0, prefix_caps[-1] + 1):
            a = list(ap) + [al]
            v = cost_at(a)
            if v is None:
                continue
            T_a = v
            if mN >= T_a - 1e-9:
                gexp = sum(a[i] * tvec[i] for i in range(l))
                c = gexp * lg(2) + lg(mN) - 0 + (omega - 1) * (T_a)  # placeholder
                best = min(best, c)
                break
    return best

def _piglet_mm_fast(n, t, m, omega=2.8):
    """Piglet MM 混合搜索：前缀枚举 + 末维最小可行（二分）。返回 (log2 cost, a)。"""
    l = len(t)
    tt = sum(t)
    if l == 3:
        Nv = 0
        for j in range(t[1] - 1, t[0] + t[1] + 1):
            Nv += lcombv(n - 1, j) * lcombv(n, tt - j)
    else:
        Nv = 0
        for j in range(t[2] - 1, t[0] + t[1] + t[2] + 1):
            Nv += lcombv(n - 1, j) * lcombv(n, tt - j)
    if Nv <= 0:
        return None, None
    N = lg(Nv)
    mN = lg(m) + N
    Tfull = sum(lcomb(n, ti) for ti in t)
    if mN >= Tfull - 1e-9:
        return lg(m) + N + (omega - 1) * Tfull, ()
    best, bt = inf, None
    def T_of(a):
        return sum(lcomb(n - a[i], t[i]) for i in range(l))
    prefix_ranges = [range(0, n - t[i] + 1) for i in range(l - 1)]
    for ap in product(*prefix_ranges):
        lo, hi = 0, n - t[l - 1]
        ok = None
        while lo <= hi:
            mid = (lo + hi) // 2
            a = list(ap) + [mid]
            if mN >= T_of(a) - 1e-9:
                ok = mid
                hi = mid - 1
            else:
                lo = mid + 1
        if ok is None:
            continue
        a = list(ap) + [ok]
        gexp = sum(a[i] * t[i] for i in range(l))
        c = gexp * lg(2) + lg(m) + N + (omega - 1) * T_of(a)
        if c < best:
            best, bt = c, tuple(a)
    return (best, bt) if best < inf else (None, None)

def piglet_mm_31(n, t, m, omega=2.8, cap=48):
    c, _ = _piglet_mm_fast(n, t, m, omega)
    return c

def piglet_mm_42(n, t, m, omega=2.8, cap=44):
    c, _ = _piglet_mm_fast(n, t, m, omega)
    return c



# ============================================================
# BRA / BRQC（块状；ω=2）
# ============================================================

def bra_aght(nvec, k, rvec, m, omega=2.0):
    n = sum(nvec); r = sum(rvec)
    t1 = omega * lg((n - k - 1) * m) + (r * ceil((k + 1) * m / n) - m) * lg(2)
    t2 = omega * lg(n - k) + 2 * lg(m) + (r * k) * lg(2)
    return min(t1, t2)

def bra_prr(nvec, k, rvec, m, omega=2.0):
    n = sum(nvec); l = len(nvec)
    M = m * (n - k - 1)
    best = inf
    if l == 1:
        # 单块：只有一个枚举维度，不再附加“末块”（2026-11-02 修复外部审计项 B4：
        # 原实现把单块元组当前缀后又饱和一个末块，多计一个不存在的块，
        # 例如 bra_prr([30],10,[3],20,2) 曾返回 30.14，正确值为 21.14）。
        n0, r0 = nvec[0], rvec[0]
        u_s = min(m, M // n0) if n0 > 0 else -1
        if u_s >= r0:
            best = min(best, omega * lg(M) + (r0 * (m - u_s) - m) * lg(2))
        u_c = min(n0, n - k)
        if u_c >= r0:
            best = min(best, 2 * lg(m) + omega * lg(n - k) + (r0 * (n0 - u_c)) * lg(2))
        return best
    # PRR-S：t_i ∈ [r_i, m]；Σt ≤ m；Σ n_i t_i ≤ M；末维饱和
    if l == 1:
        cand = [range(rvec[0], m + 1)]
    else:
        cand = [range(rvec[i], m + 1) for i in range(l - 1)]
    for tp in product(*cand):
        base_sum = sum(tp)
        base_w = sum(nvec[i] * tp[i] for i in range(len(tp)))
        rem = min(m - base_sum, (M - base_w) // nvec[l - 1])
        if rem < rvec[l - 1]:
            continue
        t = tp + (rem,)
        expo = sum(rvec[i] * (m - t[i]) for i in range(l)) - m
        c = omega * lg(M) + expo * lg(2)
        best = min(best, c)
    # PRR-C：t'_i ∈ [r_i, n_i]；Σt' ≤ n-k；末维饱和
    if l == 1:
        cand = [range(rvec[0], nvec[0] + 1)]
    else:
        cand = [range(rvec[i], nvec[i] + 1) for i in range(l - 1)]
    for tp in product(*cand):
        rem = min(nvec[l - 1], (n - k) - sum(tp))
        if rem < rvec[l - 1]:
            continue
        t = tp + (rem,)
        expo = sum(rvec[i] * (nvec[i] - t[i]) for i in range(l))
        c = omega * lg(n - k) + 2 * lg(m) + expo * lg(2)
        best = min(best, c)
    return best

def bra_oj_c(nvec, k, rvec, m, omega=2.0):
    n = sum(nvec); r = sum(rvec); l = len(nvec)
    N = ceil((m * (r - 1) + nvec[0] - rvec[0]) / m)
    if N > n - k - 1:
        return inf, N
    if l == 1:
        # 单块（RD）：坐标枚举紧式 (r-1)(N+k+1-r)
        return omega * lg(m * N) + (r - 1) * (N + k + 1 - r) * lg(2), N
    gamma = min(rvec)
    base = omega * lg(m * N)
    k1 = k + 1
    out = inf
    def cost(expo):
        return base + expo * lg(2)
    if 0 < k1 <= rvec[0]:
        out = min(out, cost((N - r + k1) * gamma))
    if rvec[0] < k1 <= nvec[0]:
        out = min(out, cost((rvec[0] - 1) * (k1 - rvec[0]) + (N - sum(rvec[1:])) * gamma))
    for j in range(1, l):
        s_n = sum(nvec[:j]); s_r = sum(rvec[:j])
        if s_n < k1 <= s_n + rvec[j]:
            out = min(out, cost(sum(rvec[i] * (nvec[i] - rvec[i]) for i in range(j)) - (nvec[0] - rvec[0])
                                + (N - sum(nvec[:j]) - sum(rvec[j:]) + k1) * gamma))
        if s_n + rvec[j] < k1 <= sum(nvec[:j + 1]):
            out = min(out, cost(sum(rvec[i] * (nvec[i] - rvec[i]) for i in range(j)) - (nvec[0] - rvec[0])
                                + (k1 - sum(nvec[:j]) - rvec[j]) * rvec[j]
                                + (N - sum(rvec[j + 1:])) * gamma))
    return out, N

def bra_oj_s(nvec, k, rvec, m, omega=2.0):
    n = sum(nvec); r = sum(rvec)
    if m <= r:
        return inf, None
    N = ceil(k * r / (m - r))
    if N > n - k - 1:
        return inf, N
    return omega * lg(m * N) + (m - r) * (r - 1) * lg(2), N

def bra_mm_at(m, nvec, k, rvec, a, p, h, omega=2.0):
    """块状 MM：T = q^(Σa_i(r_i-h_i)+Σh_i(n_i-h_i)) · E · U^(ω-1)，

    其中 U = ∏_i C(n_i-a_i-p_i-h_i, r_i-h_i)（各块子式数之积，对数域求和），
    E 为块状扩展系统的独立方程计数上界（E_minors）。

    2026-11-02 修复（外部审计项 B1）：加入方程数门槛 E >= U-1；
    不满足时返回 None。此前函数不做该检查而调用方也未检查，四条不满足
    门槛的预置参数（BRA-128/256 与 BRQC-128/256 的 3n 实例）曾被当作
    正常攻击成本写入表格。
    """
    l = len(nvec)
    nred = [nvec[i] - a[i] - p[i] - h[i] for i in range(l)]
    rred = [rvec[i] - h[i] for i in range(l)]
    kred = k - sum(a)
    if any(x < 0 for x in nred) or any(x <= 0 for x in rred):
        return None
    if any(nred[i] < rred[i] for i in range(l)):
        return None
    res = E_minors(m, nred, kred, rred)
    if res is None:
        return None
    logE, _ = res
    U = sum(lcomb(nred[i], rred[i]) for i in range(l))
    if logE < U - 1e-9:          # E >= U-1（对数域；U 极大时 log2(U-1)=U）
        return None
    guess = sum(a[i] * (rvec[i] - h[i]) + h[i] * (nvec[i] - h[i]) for i in range(l))
    cost = guess * lg(2) + logE + (omega - 1) * U
    return cost, logE, U

def bra_mm_search(m, nvec, k, rvec, omega=2.0, pmax=2, acap=48):
    """受限搜索：a 每维 [0..acap]，p 每维 [0..pmax]，h=0。"""
    l = len(nvec)
    best, bt = inf, None
    for p in product(*[range(0, pmax + 1)] * l):
        for a in product(*[range(0, acap + 1)] * l):
            if sum(a) > k:
                continue
            r = bra_mm_at(m, nvec, k, rvec, list(a), list(p), [0] * l, omega)
            if r is None:
                continue
            c, logE, U = r
            if logE < U - 1e-9:
                continue
            if c < best:
                best, bt = c, (tuple(a), tuple(p))
    return best, bt

# ============================================================
# 自检
# ============================================================

def selftest():
    tests = [
        ((9, [6, 6], 1, [2, 2]), 185), ((9, [6, 6], 2, [2, 2]), 120),
        ((9, [6, 6], 3, [2, 2]), 70), ((9, [8, 4], 4, [2, 2]), 31),
        ((9, [5, 5, 5], 1, [2, 2, 2]), 1100), ((9, [5, 5, 5], 2, [2, 2, 2]), 700),
        ((9, [8, 4], 3, [2, 2]), 53), ((9, [5, 5, 5], 3, [2, 2, 2]), 400),
    ]
    ok = bad = 0
    for (m, nvec, k, rvec), want in tests:
        res = E_minors(m, nvec, k, rvec)
        got = round(2 ** res[1]) if res else None
        good = got is not None and abs(got - want) <= max(2, want * 0.02)
        ok += good; bad += (not good)
        print(f"  [{'PASS' if good else 'FAIL'}] E m={m} n={nvec} k={k} r={rvec}: got {got} want {want}")
    print(f"E checks: {ok} pass, {bad} fail")

    # ------------------------------------------------------------------
    # 回归检查（2026-11-02 外部审计后新增；覆盖审计项 B1/B3/B4/S2）
    # ------------------------------------------------------------------
    print("audit regression checks:")
    npass = nfail = 0

    def acheck(name, cond, extra=""):
        nonlocal npass, nfail
        npass += bool(cond); nfail += (not cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name} {extra}")

    infeasible = [
        (67, [121, 121, 121], 121, [5, 8, 5], (0, 0, 0), (1, 1, 2)),
        (83, [161, 161, 161], 161, [6, 8, 6], (5, 5, 5), (0, 0, 0)),
        (127, [119, 119, 119], 119, [5, 8, 5], (0, 0, 0), (0, 0, 32)),
        (163, [161, 161, 161], 161, [6, 8, 7], (7, 1, 2), (0, 0, 0)),
    ]
    for (m, nvec, k, rvec, a, pp) in infeasible:
        r = bra_mm_at(m, nvec, k, rvec, list(a), list(pp), [0] * len(nvec))
        acheck(f"B1: 不可行 MM 预置被拒绝 r={rvec} p={pp}", r is None)
    feasible = [
        (67, [121, 121, 121], 121, [8, 5, 5], (0, 0, 0), (1, 1, 2), 189.145156),
        (83, [161, 161, 161], 161, [8, 6, 6], (5, 5, 5), (0, 0, 0), 321.764517),
        (127, [119, 119, 119], 119, [5, 8, 5], (0, 0, 0), (0, 32, 0), 181.734078),
        (163, [161, 161, 161], 161, [8, 6, 7], (1, 7, 2), (0, 0, 0), 295.370985),
    ]
    for (m, nvec, k, rvec, a, pp, want) in feasible:
        r = bra_mm_at(m, nvec, k, rvec, list(a), list(pp), [0] * len(nvec))
        got = None if r is None else r[0]
        acheck(f"B1: 可行替代参数成本 r={rvec}",
               r is not None and abs(got - want) < 1e-4,
               f"(got {None if got is None else round(got, 6)}, want {want})")
    c28 = cmulti_mm(79, 70, 35, 8, omega=2.8)[0]
    acheck("B3: cmulti_mm 成本含 (ω-1) 因子", abs(c28 - 197.144482) < 1e-3,
           f"(omega=2.8 -> {c28:.6f}，修复前 172.821486)")
    c20 = cmulti_mm(79, 70, 35, 8, omega=2.0)[0]
    acheck("B3: omega=2 结果不变", abs(c20 - 172.821486) < 1e-5, f"({c20:.6f})")
    got = bra_prr([30], 10, [3], 20, 2.0)
    acheck("B4: 单块 PRR 满足自身约束", abs(got - 21.139711) < 1e-5,
           f"(got {got:.6f}，修复前 30.139711)")
    acheck("S2: Piglet 早期返回反例（保留启发式，已复核 8 组预置）",
           abs(piglet_mm_31(4, (1, 1, 1), 5) - 18.209391) < 1e-5,
           "(n=4,m=5 反例：可行 (a)=(3,3,0) 更低；预置不受影响)")
    # 2026-11-05 审计回归（B1：Ncol=d2-1；B3：ω=2.81 验收值）
    loong_fixed = [
        (128, 42, 47, 10, (5, 5), 4, 1, 122.225024),
        (128, 42, 47, 10, (5, 5), 3, 2, 120.522407),
        (256, 65, 67, 12, (5, 6), 3, 1, 221.547030),
        (256, 65, 67, 12, (6, 6), 3, 2, 234.680243),
        (384, 83, 83, 14, (6, 6), 3, 1, 310.346288),
        (384, 83, 83, 14, (7, 7), 4, 2, 349.086593),
        (512, 104, 97, 15, (7, 7), 4, 1, 450.843747),
        (512, 104, 97, 15, (7, 7), 4, 2, 393.534519),
    ]
    for (lvl, n, m, n1, tt, g, inst, want) in loong_fixed:
        got = loong_mm(n, n1, tt[0], tt[1], g, m, inst)
        acheck(f"B1: BAG-Loong MM L{lvl} inst{inst}", abs(got - want) < 1e-4,
               f"(got {got:.6f}, want {want})")
    c281 = cmulti_mm(79, 70, 35, 8, omega=2.81)[0]
    acheck("B3: cmulti_mm omega=2.81 验收值", abs(c281 - 197.448520) < 1e-3,
           f"(got {c281:.6f}, want 197.448520)")
    print(f"audit regression: {npass} pass, {nfail} fail")
    return 1 if (nfail or bad) else 0

if __name__ == "__main__":
    selftest()
