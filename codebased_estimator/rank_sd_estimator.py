#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rank_sd_estimator.py —— 秩度量（Rank SD）攻击复杂度评估脚本  v2.0
================================================================
对应计划文档「五 同学 B 的 Rank SD 路线任务」交付项②：复杂度评估脚本
（Python；无第三方依赖，标准库即可运行）。

设计口径（与《秩度量数学公式与评估模型》文档一致）
----------------------------------------------------------------
* 输入实例：RSD/RD 参数 (q, m, n, k, r) + 线性代数常数 ω + 换算指数 θ；
* 输出统一字段：log2(T)、报告 bits(=floor)、单位域（Fq / Fqm）、状态、
  最优内部参数、适用条件、文献出处；
* 换算约定（与 CryptographicEstimators 生态一致）：
    - 先按“基础域运算次数”的对数计算（Fq 或 Fqm 运算）；
    - 再换算为二进制代价：bits = log2_ops + θ·log2(log2(q_eff))，
      其中 q_eff = q（Fq 运算）或 q^m（Fqm 运算）；q=2 时 Fq 运算不再加项。
* 全部组合数使用精确整数（math.comb），对数用 math.log2；
  报告值 = floor(bits)，与文献报告口径一致（±1 比特视为一致）。

已实现（v2.0；2026-10 对齐 CryptographicEstimators v2.1.1（main）的
RankSDEstimator 全部十个算法口径，并通过其 doctest/文献表值校验）：
  - BE / CS96 基枚举
  - OJ1、OJ2（EVV26 估计器口径）
  - OJ 系数侧经典/紧式（GRS16/CWW26/SCHZL26 口径）
  - OJ 支撑侧紧式（SCHZL26 定理 2）
  - GRS（GRS16 攻击一，估计器口径）
  - AGHT/GRS_im（改进 GRS）
  - GRS_ge（DEGS24 猜测增强）
  - AP（annulator polynomial）
  - MM（MaxMinors；含穿刺 p 与 hybrid a）
  - SM（Support-Minors / SM-Fq^m+；含 hybrid a 与 b）
  - CWW26 联合新混合 MM（subsupport + zero-reduction + MM；2026 新结果）
  - WT23 量子 GRS（可选，量级口径）

未含（后续扩展，公式见文档）：分块 RSD(BRD)/非均匀(NHRD) 的 OJ 紧式分段、
PRR-S/C 块状指数、RSL 攻击模型、EVV26 渐近指数导出模块。

用法
----------------------------------------------------------------
  python rank_sd_estimator.py --q 2 --m 53 --n 53 --k 45 --r 4
  python rank_sd_estimator.py --q 2 --m 61 --n 57 --k 44 --r 7 --omega 2 --json out.json
  python rank_sd_estimator.py --q 2 --m 53 --n 53 --k 45 --r 4 --quantum
  python rank_sd_estimator.py --selftest
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field, asdict
from math import ceil, floor, comb as binomial, inf, log2
from typing import Dict, List, Optional, Tuple

INF = float("inf")

if __name__ == "__main__":
    try:  # 控制台兼容：避免个别符号在 GBK 终端崩溃
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass


def _w(s: str) -> int:
    """显示宽度（CJK 字符按 2 列计）。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def _pad(s: str, width: int, align: str = "<" ) -> str:
    d = width - _w(s)
    if d <= 0:
        return s
    return s + " " * d if align == "<" else " " * d + s


# ============================================================================
# 基础工具
# ============================================================================

def conv_bits(raw_ops_log2: float, q: int, m: int, on_base_field: bool, theta: float = 2.0) -> float:
    """把“基础运算次数”的对数换算为二进制代价（bits）。

    约定（同 CryptographicEstimators）：bits = log2_ops + theta*log2(log2(q_eff))，
    q_eff = q 或 q^m；q=2 时 Fq 运算不加项（log2(log2(2)) = 0）。
    """
    if raw_ops_log2 == INF or raw_ops_log2 is None:
        return raw_ops_log2
    q_eff = q if on_base_field else q ** m
    lq = log2(q_eff) if q_eff > 1 else 1.0
    lq = max(lq, 1.0)
    return raw_ops_log2 + theta * log2(lq)


@dataclass
class Params:
    """RSD/RD 实例参数。"""
    q: int
    m: int
    n: int
    k: int
    r: int
    omega: float = 2.0   # 线性代数常数（文献表值常用 2；官方代码默认 3）
    theta: float = 2.0   # 换算指数（默认 2）

    def log2q(self) -> float:
        return log2(self.q)

    def check(self) -> List[str]:
        errs = []
        if self.q < 2:
            errs.append("q 必须 >= 2")
        if not (1 <= self.k < self.n):
            errs.append("要求 1 <= k < n")
        if not (1 <= self.r < self.m):
            errs.append("要求 1 <= r < m")
        if self.omega < 2.0 or self.omega > 3.0:
            errs.append("omega 须在 [2, 3]")
        if not (0.0 <= self.theta <= 2.0):
            errs.append("theta 须在 [0, 2]")
        return errs


@dataclass
class Estimate:
    """单条攻击的评估结果（对齐平台统一字段）。"""
    attack: str
    family: str                         # combinatorial / algebraic / hybrid / quantum
    status: str = "computed"            # computed / conditional / not_applicable
    log2_bits: Optional[float] = None   # 换算后二进制代价 log2（报告口径）
    bits: Optional[int] = None          # floor(log2_bits)
    log2_ops: Optional[float] = None    # 换算前：基础域运算次数的 log2
    domain: str = "Fq"                  # 计算所属域（换算前）
    optimal: Dict[str, object] = field(default_factory=dict)
    conditions: str = ""
    source: str = ""
    notes: str = ""

    def finalize(self):
        if self.log2_bits is not None and self.log2_bits != INF:
            self.bits = int(floor(self.log2_bits))
        return self


# ============================================================================
# 计数函数（EVV26 / CryptographicEstimators 口径；v2.1.1 main 分支）
# ============================================================================

def _nb_fqm(m: int, n: int, k: int, r: int, b: int) -> Optional[int]:
    """SM-Fq^m 行数（未减 syzygy 项）。"""
    if (1 > k) or (k > n) or (b < 1) or (r < 1) or (m < 1) or (r > n - k - 1):
        return None
    nn = 0
    for i in range(1, k + 1):
        nn += binomial(n - i, r) * binomial(k + b - 1 - i, b - 1)
    nn -= binomial(n - k - 1, r) * binomial(k + b - 1, b)
    return nn


def _nb_syz(m: int, n: int, k: int, r: int, b: int) -> Optional[int]:
    """syzygy 修正项 (m-1)*Σ(-1)^{i+1} C(k+b-i-1,b-i) C(n-k-1,r+i)。"""
    if (1 > k) or (k > n) or (b < 1) or (r < 1) or (m < 1) or (r > n - k - 1):
        return None
    nn = 0
    for i in range(1, b + 1):
        nn += (-1) ** (i + 1) * binomial(k + b - i - 1, b - i) * binomial(n - k - 1, r + i)
    return (m - 1) * nn


def compute_nb(m: int, n: int, k: int, r: int, b: int) -> Optional[int]:
    """SM 独立方程数 N_b；b=0 时退化为 MM 行数 m*C(n-k-1, r)。"""
    if b == 0:
        return m * binomial(n - k - 1, r) if (n - k - 1) >= r else None
    x = _nb_fqm(m, n, k, r, b)
    if x is None:
        return None
    return x - _nb_syz(m, n, k, r, b)


def compute_mb(m: int, n: int, k: int, r: int, b: int) -> Optional[int]:
    """SM 变量数 M_b；b=0 时退化为 C(n, r)。"""
    if (1 > k) or (k > n) or (b < 0) or (r < 1) or (m < 1) or (r > n - k - 1) or (n < r):
        return None
    if b == 0:
        return binomial(n, r)
    return binomial(k + b - 1, b) * (binomial(n, r) - m * binomial(n - k - 1, r))


def _find_p_sm(m: int, n: int, k: int, r: int, b: int, p_min: int, p_max: int) -> Optional[int]:
    """选择最大可行穿刺数 p（逐 p 扫描，保留最后一个可行者）。"""
    p_sel = None
    for p in range(p_min, min(n - 1, p_max + 1)):
        nb = compute_nb(m, n - p, k, r, b)
        mb = compute_mb(m, n - p, k, r, b)
        if nb is not None and mb is not None and nb >= mb - 1:
            p_sel = p
    return p_sel


def _mm_choice(m: int, n: int, k: int, r: int) -> Dict[str, Optional[int]]:
    """MM/SM 共用的 (a0, p0)：a0 = 首个使 MM 系统超定的猜零数（b=0）。"""
    a_sel = None
    for a in range(0, k + 1):
        nb = compute_nb(m, n - a, k - a, r, 0)
        mb = compute_mb(m, n - a, k - a, r, 0)
        if nb is not None and mb is not None and nb >= mb - 1:
            a_sel = a
            break
    if a_sel is None or a_sel >= k:
        return {}
    p_sel = _find_p_sm(m, n - a_sel, k - a_sel, r, 0, 0, n)
    return {"a": a_sel, "p": p_sel}


def _find_b_sm(m: int, n: int, k: int, r: int, b_min: int = 1, b_max: int = 100):
    """SM 最小可行 b；无则返回 inf。"""
    for b in range(b_min, b_max + 1):
        nb = compute_nb(m, n, k, r, b)
        mb = compute_mb(m, n, k, r, b)
        if nb is not None and mb is not None and nb >= mb - 1:
            return b
    return inf


def _sm_choices(m: int, n: int, k: int, r: int) -> List[Tuple[int, int, int]]:
    """SM 可行参数表：a 从 a0-1 递减到 0，每个 a 取最小可行 b 与最大可行 p。"""
    values = _mm_choice(m, n, k, r)
    out: List[Tuple[int, int, int]] = []
    if not values or values.get("a") == 0:
        return out
    a0 = values["a"]
    for a in range(a0 - 1, -1, -1):
        b = _find_b_sm(m, n - a, k - a, r)
        if b == inf:
            break
        p = _find_p_sm(m, n - a, k - a, r, b, 0, n)
        out.append((a, b, p))
    return out


# ============================================================================
# 各攻击（EVV26 估计器口径为主，标注处为文献口径）
# ============================================================================

def be(p: Params) -> Estimate:
    e = Estimate("BE/CS96 基枚举", "combinatorial", source="CS96；EVV26（估计器口径）")
    raw = p.omega * log2(p.n * p.r + p.m) + (p.m - p.r) * (p.r - 1) * p.log2q()
    e.log2_ops = raw
    e.log2_bits = conv_bits(raw, p.q, p.m, True, p.theta)
    e.conditions = "基枚举；指数不含 n"
    return e.finalize()


def oj1_estimator(p: Params) -> Estimate:
    e = Estimate("OJ1 (估计器口径)", "combinatorial", source="EVV26 §3.1；CryptographicEstimators v2.1.1")
    if p.m <= 1:
        e.status = "not_applicable"; return e
    N = ceil(((p.r - 1) * p.m + (p.k + 1)) / (p.m - 1))
    raw = (p.omega * log2((p.r - 1) * p.m + p.k + N + 1)
           + (p.r - 1) * (p.k + N + 2 - p.r) * p.log2q())
    e.log2_ops = raw
    e.log2_bits = conv_bits(raw, p.q, p.m, True, p.theta)
    e.optimal = {"N": N}
    e.conditions = f"N = {N}；系数侧（行支撑）枚举"
    e.notes = ("注意：EVV26 论文表 2 的 'OJ1' 列与当前代码口径存在数比特差异（论文表近似经典式）——"
               "本脚本另给“OJ 系数侧(经典/紧式)”行以供交叉核对")
    return e.finalize()


def oj2_estimator(p: Params) -> Estimate:
    e = Estimate("OJ2 (估计器口径)", "combinatorial", source="EVV26 §3.1；CryptographicEstimators v2.1.1")
    if p.m - p.r <= 0:
        e.status = "not_applicable"; e.notes = "需 m > r"; return e
    nn = ceil(((p.k + 1) * p.r) / (p.m - p.r))
    raw = (p.omega * (log2(p.m * nn) + log2(p.k + 1 + nn) + log2(p.r))
           + (p.r - 1) * (p.m - p.r) * p.log2q())
    e.log2_ops = raw
    e.log2_bits = conv_bits(raw, p.q, p.m, True, p.theta)
    e.optimal = {"N": nn}
    e.conditions = f"N = {nn}；支撑侧（列支撑）枚举"
    return e.finalize()


def oj_coeff_classic(p: Params) -> Estimate:
    e = Estimate("OJ 系数侧(经典/紧式)", "combinatorial", source="GRS16；CWW26 表2；SCHZL26 §5.2")
    if p.m <= 1:
        e.status = "not_applicable"; return e
    if p.k <= p.m - 1:
        N = p.r
        expo = (p.r - 1) * (p.k + 1)
        cond = "k <= m-1（经典式）"
    else:
        beta = p.k // (p.m - 1)
        N = p.r + beta
        expo = (p.r - 1) * (N + p.k + 1 - p.r)
        cond = f"k > m-1：β = {beta}，N = r+β"
    raw = p.omega * log2(p.m * N) + expo * p.log2q()
    e.log2_ops = raw
    e.log2_bits = conv_bits(raw, p.q, p.m, True, p.theta)
    e.optimal = {"N": N}
    e.conditions = cond
    e.notes = "CWW26 表 2 记法 q^{(r-1)(k+ceil((k+1)/(m-1)))}；用于复现 CWW26/EVV26 论文表中的 OJ1 列"
    return e.finalize()


def oj_support_tight(p: Params) -> Estimate:
    e = Estimate("OJ 支撑侧(SCHZL26 紧式)", "combinatorial", source="SCHZL26 定理 2")
    if p.m <= p.r:
        e.status = "not_applicable"; e.notes = "需 m > r"; return e
    N = ceil(p.k * p.r / (p.m - p.r))
    raw = p.omega * log2(p.m * N) + (p.m - p.r) * (p.r - 1) * p.log2q()
    e.log2_ops = raw
    e.log2_bits = conv_bits(raw, p.q, p.m, True, p.theta)
    e.optimal = {"N": N}
    ok = N <= p.n - p.k - 1
    e.conditions = f"N = {N}；要求 N <= n-k-1（当前 {'满足' if ok else '不满足'}）"
    if not ok:
        e.status = "conditional"
    e.notes = "结构无关（RD/NHRD/BRD 同式）；与误差结构无关"
    return e.finalize()


def grs(p: Params) -> Estimate:
    e = Estimate("GRS (GRS16 攻击一)", "combinatorial", source="GRS16 Prop.1；EVV26（估计器口径）")
    t1 = p.omega * log2((p.n - p.k) * p.m)
    best = INF
    r1a = p.m - ceil(p.k * p.m / p.n)
    if r1a > 0:
        best = min(best, t1 + p.r * (p.m - r1a) * p.log2q())
    r1b = p.m - ceil((p.k + 1) * p.m / p.n)
    if r1b > 0:
        best = min(best, t1 + (p.r - 1) * (p.m - r1b) * p.log2q())
    if best == INF:
        e.status = "not_applicable"; e.notes = "r' <= 0，不适用"; return e
    e.log2_ops = best
    e.log2_bits = conv_bits(best, p.q, p.m, True, p.theta)
    e.conditions = "首次把码长 n 带入指数（ceil 取整为估计器口径）"
    return e.finalize()


def aght(p: Params) -> Estimate:
    e = Estimate("AGHT/GRS_im", "combinatorial", source="AGH18 Thm III.2；EVV26（ImprovedGRS）")
    r1 = p.m - ceil((p.k + 1) * p.m / p.n)
    if r1 <= 0:
        e.status = "not_applicable"; e.notes = "r' <= 0，不适用"; return e
    raw = (p.omega * log2((p.n - p.k) * p.m)
           + max(0.0, (p.r * (p.m - r1) - p.m) * p.log2q()))
    e.log2_ops = raw
    e.log2_bits = conv_bits(raw, p.q, p.m, True, p.theta)
    e.optimal = {"r'": r1}
    e.conditions = "m <= n 区域最优（2018--2022 基准）"
    return e.finalize()


def grs_ge(p: Params) -> Estimate:
    e = Estimate("GRS_ge (猜测增强)", "combinatorial", source="DEGS24；EVV26（估计器口径）")
    best, best_t = INF, None
    for t in range(0, p.n * p.m + 1):
        r1 = floor(((p.n - p.k - 1) * p.m + t) / p.n)
        if r1 <= 0:
            continue
        t1 = p.omega * log2((p.n - p.k) * p.m + t)
        mu = p.r * (p.m - r1) - p.m + t
        c = t1 + max(0.0, mu * p.log2q())
        if c < best:
            best, best_t = c, t
    if best == INF:
        e.status = "not_applicable"; return e
    e.log2_ops = best
    e.log2_bits = conv_bits(best, p.q, p.m, True, p.theta)
    e.optimal = {"t": best_t}
    e.conditions = "t>0 才有增益时不劣于 AGHT（t=0 情形与 AGHT 同族）"
    e.notes = "对 RYDE 系列至多再降 9 比特（无泄漏；DEGS24）"
    return e.finalize()


def ap(p: Params) -> Estimate:
    e = Estimate("AP (annulator 多项式)", "algebraic", domain="Fqm",
                 source="GRS16 攻击二；EVV26（估计器口径）")
    best, best_t = INF, None
    for t in range(1, p.k + 1):
        if (p.n - t) < ((p.r + 1) * (p.k + 1 - t) - 1):
            continue
        c = p.omega * (log2(p.r) + log2(p.k)) + p.r * t * p.log2q()
        if c < best:
            best, best_t = c, t
    if best == INF:
        e.status = "conditional"
        e.notes = "无满足线性化条件的 t（需启发式/Gröbner 口径）"
        return e
    e.log2_ops = best
    e.log2_bits = conv_bits(best, p.q, p.m, False, p.theta)
    e.optimal = {"t": best_t}
    e.conditions = "t 需满足 n-t >= (r+1)(k+1-t)-1（多项式化条件）"
    return e.finalize()


def mm(p: Params) -> Estimate:
    e = Estimate("MM (MaxMinors)", "algebraic", source="EC20/AC20；CWW26 (3.4)-(3.6)；EVV26（估计器口径）")
    values = _mm_choice(p.m, p.n, p.k, p.r)
    if not values or values.get("p") is None:
        e.status = "not_applicable"
        e.notes = "在 a<=k 内未找到可行 (a,p)"
        return e
    a, pp = values["a"], values["p"]
    raw = (a * p.r * p.log2q()
           + log2(compute_nb(p.m, p.n - a - pp, p.k - a, p.r, 0))
           + (p.omega - 1) * log2(compute_mb(p.m, p.n - a - pp, p.k - a, p.r, 0)))
    e.log2_ops = raw
    e.log2_bits = conv_bits(raw, p.q, p.m, True, p.theta)
    e.optimal = {"a": a, "p": pp}
    e.conditions = "m·C(n-k-1,r) >= C(n,r)-1（超定）；否则 a = 首个可行猜零数（含穿刺 p）"
    e.notes = "q 小者尤其强；渐近 hybrid a~k（EVV26 §4.2）"
    return e.finalize()


def sm(p: Params) -> Estimate:
    e = Estimate("SM (Support-Minors)", "algebraic", domain="Fq→Fqm",
                 source="AC20；DCC23（修正）；CWW26 (3.7)；EVV26（估计器口径）")
    choices = _sm_choices(p.m, p.n, p.k, p.r)
    if not choices:
        e.status = "not_applicable"
        e.notes = "无可行 (a,b)（a0=0 时 MM 已超定、SM 一般不单独使用）"
        return e
    best, best_desc = INF, None
    for (a, b, pp) in choices:
        raw = (a * p.r * p.log2q()
               + log2(compute_nb(p.m, p.n - a - pp, p.k - a, p.r, b))
               + (p.omega - 1) * log2(compute_mb(p.m, p.n - a - pp, p.k - a, p.r, b)))
        c = conv_bits(raw, p.q, p.m, False, p.theta)
        if c < best:
            best, best_desc = c, {"a": a, "b": b, "p": pp}
    e.log2_ops = best - p.theta * log2(max(log2(p.q ** p.m), 1.0))
    e.log2_bits = best
    e.optimal = best_desc
    e.conditions = "N_b >= M_b-1；ω 可乐观取 2（文献惯例）"
    e.notes = "SM-Fq^m+ 已剔除线性依赖（DCC23）；略慢于 MM"
    return e.finalize()


def cww_new_hybrid(p: Params) -> Estimate:
    e = Estimate("CWW26 新混合 MM", "hybrid", source="CWW26 式 (4.2)-(4.3)（2026）")
    best, best_desc = INF, None
    for h in range(0, p.r):
        rh = p.r - h
        if rh <= 0:
            continue
        for a in range(0, p.k + 1):
            if p.n - h - p.k - 1 < rh or p.n - h - a < rh:
                continue
            if p.m * binomial(p.n - h - p.k - 1, rh) < binomial(p.n - h - a, rh) - 1:
                continue
            raw = (log2(p.m)
                   + (h * (p.n - p.r) + a * (p.r - h)) * p.log2q()
                   + log2(binomial(p.n - h - p.k - 1, rh))
                   + (p.omega - 1) * log2(binomial(p.n - h - a, rh)))
            if raw < best:
                best, best_desc = raw, {"h": h, "a": a}
    if best == INF:
        e.status = "conditional"
        e.notes = "未找到可行 (a,h)（增益集中于高码率区域）"
        return e
    e.log2_ops = best
    e.log2_bits = conv_bits(best, p.q, p.m, True, p.theta)
    e.optimal = best_desc
    e.conditions = "增益集中于高码率（大 k、小 r）区域，如 RYDE"
    e.notes = "RYDE Cat.5: 301 -> 272 bits（ω=2）；h=0 即经典混合 MM"
    return e.finalize()


def wt23_quantum_grs(p: Params) -> Estimate:
    e = Estimate("WT23 量子 GRS（量级）", "quantum", source="WT23（ePrint 2023/994）")
    w = p.r
    rp = p.m - ceil((p.k + 1) * p.m / p.n)
    if rp < w or rp <= 0:
        e.status = "conditional"; e.notes = "r' < w，口径待复核"; return e

    def log2_gauss(q, n, k):
        if k < 0 or k > n:
            return -INF
        if k == 0 or k == n:
            return 0.0
        s = 0.0
        for i in range(k):
            s += log2(q ** (n - i) - 1) - log2(q ** (k - i) - 1)
        return s

    top = log2_gauss(p.q, p.m if p.n >= p.m else p.n, w)
    bot = log2_gauss(p.q, rp, w)
    raw = 3.0 * log2(p.n * p.k) + 3.0 * log2(p.m) + 0.5 * max(0.0, top - bot)
    e.log2_ops = raw
    e.log2_bits = raw
    e.optimal = {"r'": rp}
    e.conditions = "量级口径（不含电路级常数）；迭代数 = sqrt(经典比值)，r' 取 GRS 惯例值"
    e.notes = "与原文电路级评估口径不同，禁止直接用于判定安全等级；对 RQC 某实例有效（原文）"
    return e.finalize()


ALL_ATTACKS = [
    be, oj1_estimator, oj2_estimator, oj_coeff_classic, oj_support_tight,
    grs, aght, grs_ge, ap, mm, sm, cww_new_hybrid,
]


# ============================================================================
# 统一评估 / 输出
# ============================================================================

def evaluate(p: Params, include_quantum: bool = False) -> List[Estimate]:
    errs = p.check()
    if errs:
        raise ValueError("; ".join(errs))
    results = [fn(p) for fn in ALL_ATTACKS]
    if include_quantum:
        results.append(wt23_quantum_grs(p))
    results.sort(key=lambda e: (e.log2_bits if e.log2_bits is not None else INF))
    return results


def print_report(p: Params, results: List[Estimate]):
    print("=" * 118)
    print(f"Rank SD 攻击复杂度评估  |  q={p.q}, m={p.m}, n={p.n}, k={p.k}, r={p.r}, "
          f"omega={p.omega}, theta={p.theta}")
    print("=" * 118)
    print(_pad("攻击", 30) + _pad("家族", 15) + _pad("log2(T)", 10) + _pad("bits", 6)
          + _pad("域", 8) + _pad("状态", 15) + "最优参数")
    print("-" * 118)
    for e in results:
        lg = f"{e.log2_bits:.2f}" if e.log2_bits not in (None, INF) else "--"
        bits = f"{e.bits}" if e.bits is not None else "--"
        opt = ", ".join(f"{k}={v}" for k, v in e.optimal.items()) if e.optimal else "-"
        print(_pad(e.attack, 30) + _pad(e.family, 15) + _pad(lg, 10, ">") + _pad(bits, 6, ">")
              + _pad(e.domain, 8) + _pad(e.status, 15) + opt)
    print("-" * 118)
    usable = [e for e in results if e.bits is not None and e.family != "quantum"]
    if usable:
        b = usable[0]
        print(f"[结论] 当前口径下最强攻击: {b.attack} @ {b.bits} bits "
              f"(log2={b.log2_bits:.2f}, 域={b.domain})")
        for e in results:
            if e.notes:
                print(f"  * {e.attack}: {e.notes}")
    else:
        print("[结论] 无可计算条目")
    print("说明: log2(T) 为换算后二进制代价（θ 换算）；bits = floor(log2 T)。")


def to_json(p: Params, results: List[Estimate]) -> dict:
    usable = [e for e in results if e.bits is not None]
    best = usable[0] if usable else None
    return {
        "instance": asdict(p),
        "assumptions": {
            "omega": p.omega, "theta": p.theta,
            "accounting": "先算基础域运算次数(log2)，再 θ 换算为二进制代价；bits = floor",
            "calibration": "口径与 CryptographicEstimators RankSDEstimator v2.1.1 对齐并按其 doctest 校验",
        },
        "results": [asdict(e) for e in results],
        "best": ({"attack": best.attack, "bits": best.bits, "log2": best.log2_bits,
                  "domain": best.domain, "optimal": best.optimal} if best else None),
    }


# ============================================================================
# 自检：A) 与官方估计器 doctest 完全一致（容差 0.01 / 参数一致）
#        B) 与公开发表表格一致（floor 后容差 ±1 bit）
# ============================================================================

def _result_of(fn, p: Params) -> Estimate:
    return fn(p)


def selftest() -> int:
    npass = nfail = 0

    def ok(name, cond, extra=""):
        nonlocal npass, nfail
        if cond:
            npass += 1
            print(f"  [PASS] {name} {extra}")
        else:
            nfail += 1
            print(f"  [FAIL] {name} {extra}")

    print("=" * 118)
    print("Rank SD Estimator 自检")
    print("  A) 官方估计器 doctest 精确值（容差 0.01）")
    print("  B) 公开发表表格值（ω=2；floor 后容差 ±1 bit）")
    print("=" * 118)

    # ---------- A ----------
    P = lambda **kw: Params(**kw)
    exact = [
        ("BE",            be,            dict(q=2, m=127, n=118, k=48, r=7, omega=3), 749.6889972117298, None),
        ("OJ1(估计器)",    oj1_estimator, dict(q=2, m=127, n=118, k=48, r=7, omega=3), 329.02787109882524, None),
        ("OJ2(估计器)",    oj2_estimator, dict(q=2, m=127, n=118, k=48, r=7, omega=3), 771.2443254830761, None),
        ("GRS",           grs,           dict(q=2, m=127, n=118, k=48, r=7, omega=3), 357.3539031111514, None),
        ("AGHT/IGRS",     aght,          dict(q=2, m=127, n=118, k=48, r=7, omega=3), 283.3539031111514, None),
        ("MM",            mm,            dict(q=2, m=31,  n=33,  k=15, r=10, omega=2), 153.00164676141634, {"a": 12, "p": 2}),
        ("SM",            sm,            dict(q=2, m=31,  n=33,  k=15, r=10, omega=2), 155.10223904640839, {"a": 11, "b": 1, "p": 0}),
        ("GRS_ge",        grs_ge,        dict(q=2, m=31,  n=33,  k=15, r=10, omega=2), 138.25340894568637, {"t": 1}),
        ("AP",            ap,            dict(q=2, m=127, n=118, k=48, r=7, omega=3), 312.1543216418806, {"t": 39}),
    ]
    for name, fn, kws, want, opt in exact:
        e = fn(P(**kws))
        got = e.log2_bits
        good = got is not None and abs(got - want) <= 0.01
        extra = f"got {got:.6f}, want {want}" if got is not None else "got None"
        if opt:
            good = good and all(e.optimal.get(kk) == vv for kk, vv in opt.items())
            extra += f"; optimal={e.optimal} (want {opt})"
        ok(f"A:{name}", good, f"({extra})")
    # 参数选择核对（第二组 doctest 参数）
    e = mm(P(q=2, m=37, n=41, k=18, r=13, omega=2)); ok("A:MM 参数 a=15", e.optimal.get("a") == 15, f"optimal={e.optimal} (p=2)")
    e = sm(P(q=2, m=37, n=41, k=18, r=13, omega=2)); ok("A:SM 参数 (14,2,0)", (e.optimal.get("a"), e.optimal.get("b"), e.optimal.get("p")) == (14, 2, 0), f"optimal={e.optimal}")
    e = grs_ge(P(q=2, m=37, n=41, k=18, r=13, omega=3)); ok("A:GRS_ge t=6", e.optimal.get("t") == 6)
    e = ap(P(q=2, m=31, n=33, k=15, r=10, omega=3)); ok("A:AP t=15", e.optimal.get("t") == 15)
    e = ap(P(q=2, m=37, n=41, k=18, r=13, omega=3)); ok("A:AP t=18", e.optimal.get("t") == 18)

    # ---------- B ----------
    print("-" * 118)
    W2 = dict(omega=2.0)

    def chk_b(name, fn, kws, want):
        e = fn(P(**kws))
        got = e.bits
        good = got is not None and abs(got - want) <= 1
        ok(f"B:{name}", good, f"got {got} (raw {None if e.log2_bits is None else round(e.log2_bits, 2)}), want {want}")

    # CWW26 表 1（RYDE v2.1.0）：AGHT / OJ经典 / MM / 新混合
    ryde = [(2, 53, 53, 45, 4, (148, 153, 169, 152)),
            (2, 61, 61, 51, 5, (217, 224, 245, 217)),
            (2, 61, 57, 44, 7, (301, 287, 301, 272))]
    for (q, m, n, k, r, wants) in ryde:
        chk_b(f"RYDE({m},{n},{k},{r}) AGHT", aght, dict(q=q, m=m, n=n, k=k, r=r, **W2), wants[0])
        chk_b(f"RYDE({m},{n},{k},{r}) OJ经典", oj_coeff_classic, dict(q=q, m=m, n=n, k=k, r=r, **W2), wants[1])
        chk_b(f"RYDE({m},{n},{k},{r}) MM", mm, dict(q=q, m=m, n=n, k=k, r=r, **W2), wants[2])
        chk_b(f"RYDE({m},{n},{k},{r}) 新混合", cww_new_hybrid, dict(q=q, m=m, n=n, k=k, r=r, **W2), wants[3])

    # EVV26 表 2 抽样
    evv = [
        ("ROLLO-I-128 MM", mm, dict(q=2, m=79, n=94, k=47, r=5, **W2), 50),
        ("dRANKula-256 MM", mm, dict(q=2, m=127, n=118, k=48, r=7, **W2), 68),
        ("RVDC-96 MM", mm, dict(q=2, m=29, n=22, k=11, r=7, **W2), 79),
        ("RQC-I MM", mm, dict(q=2, m=97, n=134, k=67, r=5, **W2), 54),
        ("RQC-II MM", mm, dict(q=2, m=107, n=202, k=101, r=6, **W2), 71),
        ("RQC-III MM", mm, dict(q=2, m=137, n=262, k=131, r=7, **W2), 108),
        ("RQC-I GRS_im", aght, dict(q=2, m=97, n=134, k=67, r=5, **W2), 178),
        ("RQC-II GRS_im", aght, dict(q=2, m=107, n=202, k=101, r=6, **W2), 249),
        ("ROLLO-II-256 GRS_im", aght, dict(q=2, m=127, n=314, k=157, r=7, **W2), 349),
        ("ROLLO-III-256 GRS_im", aght, dict(q=2, m=131, n=134, k=67, r=7, **W2), 364),
        ("ROLLO-I-256 GRS_im", aght, dict(q=2, m=113, n=134, k=67, r=7, **W2), 318),
        ("ROLLO-I-256 SM", sm, dict(q=2, m=113, n=134, k=67, r=7, **W2), 127),
        ("ROLLO-II-256 SM", sm, dict(q=2, m=127, n=314, k=157, r=7, **W2), 113),
        ("ROLLO-III-256 SM", sm, dict(q=2, m=131, n=134, k=67, r=7, **W2), 107),
        ("RVDC-96 OJ经典(表值)", oj_coeff_classic, dict(q=2, m=29, n=22, k=11, r=7, **W2), 87),
        ("RVDC-125 OJ经典", oj_coeff_classic, dict(q=2, m=31, n=26, k=13, r=8, **W2), 113),
        ("RVDC-196 OJ经典", oj_coeff_classic, dict(q=2, m=41, n=34, k=17, r=10, **W2), 179),
        ("RVDC-252 OJ经典", oj_coeff_classic, dict(q=2, m=47, n=38, k=19, r=12, **W2), 238),
    ]
    for (name, fn, kws, want) in evv:
        chk_b(name, fn, kws, want)

    print("-" * 118)
    print(f"总计: {npass} 通过, {nfail} 失败")
    return 1 if nfail else 0


# ============================================================================
# CLI
# ============================================================================

def main(argv=None) -> int:
    ap_ = argparse.ArgumentParser(
        description="Rank SD 攻击复杂度评估（同学 B 路线 · 交付项②；口径与 CryptographicEstimators 对齐）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap_.add_argument("--q", type=int, help="基域大小")
    ap_.add_argument("--m", type=int, help="扩域次数")
    ap_.add_argument("--n", type=int, help="码长")
    ap_.add_argument("--k", type=int, help="维数")
    ap_.add_argument("--r", type=int, help="误差秩（目标秩）")
    ap_.add_argument("--omega", type=float, default=2.0, help="线性代数常数（文献表值常用 2；官方默认 3）")
    ap_.add_argument("--theta", type=float, default=2.0, help="域运算换算指数（默认 2）")
    ap_.add_argument("--quantum", action="store_true", help="附加输出 WT23 量子 GRS（量级口径）")
    ap_.add_argument("--json", type=str, default=None, help="结果导出到 JSON 文件")
    ap_.add_argument("--selftest", action="store_true", help="运行自检（官方 doctest + 文献表值）")
    args = ap_.parse_args(argv)

    if args.selftest:
        return selftest()
    if not all(v is not None for v in (args.q, args.m, args.n, args.k, args.r)):
        ap_.print_help()
        return 2
    p = Params(q=args.q, m=args.m, n=args.n, k=args.k, r=args.r,
               omega=args.omega, theta=args.theta)
    try:
        results = evaluate(p, include_quantum=args.quantum)
    except ValueError as ex:
        print(f"参数错误: {ex}")
        return 2
    print_report(p, results)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(to_json(p, results), f, ensure_ascii=False, indent=2)
        print(f"\n[已导出] {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
