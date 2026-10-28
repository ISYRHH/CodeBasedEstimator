#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""schemes_final.py — 五方案攻击复杂度评估与声明对照（最终版）

运行：python schemes_final.py
输出：控制台对照表（同时写入 schemes_final_output.txt 供报告引用）

口径：Loong/Piglet ω=2.8；BRA/BRQC/C-Multi ω=2；
      "复算最优" 为本次实现的受限搜索/参数复现结果（log2，1 位小数）。
"""
import sys, math, io, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from math import log2, ceil, inf
import rank_sd_schemes as R

lg = log2
buf = io.StringIO()

def out(s=""):
    print(s)
    buf.write(s + "\n")

def fmt(x, nd=1):
    if x is None or x == inf:
        return "--"
    return f"{x:.{nd}f}"

def d2(c, claim):
    if c is None or c == inf:
        return "--"
    return f"{c-claim:+.1f}"

# ============================================================
# 1) BAG-Loong
# ============================================================
LOONG = {
    128: dict(n=42, m=47, n1=10, A=((5,5),4), B=((5,5),3)),
    256: dict(n=65, m=67, n1=12, A=((5,6),3), B=((6,6),3)),
    384: dict(n=83, m=83, n1=14, A=((6,6),3), B=((7,7),4)),
    512: dict(n=104, m=97, n1=15, A=((7,7),4), B=((7,7),4)),
}
LOONG_CLAIM = {
    128: dict(OJ=(176,176), PRR=(221,160), MM=(158,139)),
    256: dict(OJ=(271,327), PRR=(351,303), MM=(286,292)),
    384: dict(OJ=(418,490), PRR=(433,447), MM=(403,469)),
    512: dict(OJ=(617,617), PRR=(591,592), MM=(626,534)),
}

def run_loong():
    out("=" * 96)
    out("BAG-Loong（混合块 + 增强 Gabidulin；ω=2.8；实例1=密钥生成，实例2=加密）")
    out("=" * 96)
    out(f"{'级别':<6}{'攻击':<6}{'声明(a,b)':<16}{'复算(a,b)':<20}{'Δ(a,b)':<16}")
    for lvl, d in LOONG.items():
        n, m, n1 = d['n'], d['m'], d['n1']
        cl = LOONG_CLAIM[lvl]
        for atk in ("OJ", "PRR", "MM"):
            v1 = v2 = None
            if atk == "OJ":
                t, g = d['A']; v1 = R.loong_oj(n, n1, t[0], t[1], g, m, 1)
                t, g = d['B']; v2 = R.loong_oj(n, n1, t[0], t[1], g, m, 2)
            elif atk == "PRR":
                t, g = d['A']; v1 = R.loong_prr(n, n1, t[0], t[1], g, m, 1)
                t, g = d['B']; v2 = R.loong_prr(n, n1, t[0], t[1], g, m, 2)
            else:
                t, g = d['A']; v1 = R.loong_mm(n, n1, t[0], t[1], g, m, 1)
                t, g = d['B']; v2 = R.loong_mm(n, n1, t[0], t[1], g, m, 2)
            ca, cb = cl[atk]
            out(f"L{lvl:<5}{atk:<6}{str((ca,cb)):<16}"
                f"({fmt(v1)},{fmt(v2)})".ljust(20)
                + f"({d2(v1,ca)},{d2(v2,cb)})")
    out()

# ============================================================
# 2) BAG-Piglet
# ============================================================
PIGLET = {
    128: dict(n=47, m=43, A=(4,4,4), B=(2,3,3,3)),
    256: dict(n=78, m=79, A=(6,6,6), B=(3,3,4,4)),
    384: dict(n=106, m=103, A=(7,7,7), B=(4,4,4,4)),
    512: dict(n=125, m=131, A=(8,8,8), B=(4,4,5,5)),
}
PIGLET_CLAIM = {
    128: dict(OJ=(158,162), MM=(148,167), PRR=(334,210)),
    256: dict(OJ=(395,332), MM=(269,298), PRR=(530,534)),
    384: dict(OJ=(632,646), MM=(397,442), PRR=(1379,765)),
    512: dict(OJ=(859,763), MM=(552,563), PRR=(1070,1075)),
}

def run_piglet():
    out("=" * 96)
    out("BAG-Piglet（不相交块 + 增强 Gabidulin；ω=2.8；实例1=(3,1)，实例2=(4,2)）")
    out("=" * 96)
    out(f"{'级别':<6}{'攻击':<6}{'声明(a,b)':<16}{'复算(a,b)':<20}{'Δ(a,b)':<16}")
    for lvl, d in PIGLET.items():
        n, m = d['n'], d['m']
        cl = PIGLET_CLAIM[lvl]
        for atk in ("OJ", "MM", "PRR"):
            if atk == "OJ":
                v1 = R.piglet_oj_31(n, d['A'], m); v2 = R.piglet_oj_42(n, d['B'], m)
            elif atk == "MM":
                v1 = R.piglet_mm_31(n, d['A'], m); v2 = R.piglet_mm_42(n, d['B'], m)
            else:
                v1 = R.piglet_prr(n, d['A'], m, 3, 1); v2 = R.piglet_prr(n, d['B'], m, 4, 2)
            ca, cb = cl[atk]
            out(f"L{lvl:<5}{atk:<6}{str((ca,cb)):<16}"
                f"({fmt(v1)},{fmt(v2)})".ljust(20)
                + f"({d2(v1,ca)},{d2(v2,cb)})")
    out()

# ============================================================
# 3) BRA / BRQC
# ============================================================
BRA = {
    128: dict(m=67, n=121, A=([121,121],[4,5]), B=([121,121,121],[5,8,5]),
              mm=[((24,0),(0,0),194), ((0,0,0),(1,1,2),189),
                  ((0,38),(0,0),304), ((5,5,5),(0,0,0),321),
                  ((0,69),(0,0),556), ((43,0,0),(4,2,2),567)]),
}
BRA_ALL = {
    128: dict(m=67, n=121, k=121, A=([121,121],[4,5]), B=([121,121,121],[5,8,5]),
              mm=[((24,0),(0,0),(0,0),194), ((0,0,0),(1,1,2),(0,0,0),189),
                  ((0,38),(0,0),None,304), ((5,5,5),(0,0,0),None,321),
                  ((0,69),(0,0),None,556), ((43,0,0),(4,2,2),None,567)]),
}
# 用统一结构 {lvl: dict(...)} 记录 BRA/BRQC
BRA_DATA = {
    128: dict(m=67, k=121, A=([121,121],[4,5]), B=([121,121,121],[5,8,5]),
              c_mm=(194,189), c_aght=(264,374), c_prr=(235,632), c_oj=(393,519),
              mm2=((24,0),(0,0)), mm3=((0,0,0),(1,1,2))),
    256: dict(m=83, k=161, A=([161,161],[5,5]), B=([161,161,161],[6,8,6]),
              c_mm=(304,321), c_aght=(364,506), c_prr=(364,966), c_oj=(678,844),
              mm2=((0,38),(0,0)), mm3=((5,5,5),(0,0,0))),
    512: dict(m=127, k=221, A=([221,221],[6,6]), B=([221,221,221],[7,8,8]),
              c_mm=(556,567), c_aght=(670,893), c_prr=(670,1585), c_oj=(1144,1370),
              mm2=((0,69),(0,0)), mm3=((43,0,0),(4,2,2))),
}
BRQC_DATA = {
    128: dict(m=127, k=119, A=([119,119],[5,5]), B=([119,119,119],[5,8,5]),
              c_mm=(216,181), c_aght=(550,676), c_prr=(545,624), c_oj=(506,508),
              mm2=((0,22),(0,0)), mm3=((0,0,0),(0,0,32))),
    256: dict(m=163, k=161, A=([161,161],[5,6]), B=([161,161,161],[6,8,7]),
              c_mm=(309,295), c_aght=(779,1023), c_prr=(698,1003), c_oj=(675,840),
              mm2=((37,0),(0,0)), mm3=((7,1,2),(0,0,0))),
    512: dict(m=229, k=227, A=([227,227],[6,7]), B=([227,227,227],[8,8,8]),
              c_mm=(584,566), c_aght=(1310,1652), c_prr=(1196,1849), c_oj=(1170,1629),
              mm2=((72,0),(1,1)), mm3=((0,0,36),(0,0,0))),
}

def run_block(tag, DATA):
    out("=" * 96)
    out(f"{tag}（块状 + 理想码；ω=2；实例1=2n，实例2=3n）")
    out("=" * 96)
    out(f"{'级别':<6}{'攻击':<8}{'声明(a,b)':<16}{'复算(a,b)':<20}{'Δ(a,b)':<16}")
    for lvl, d in DATA.items():
        m, k = d['m'], d['k']
        nA, rA = d['A']; nB, rB = d['B']
        (a2, p2), (a3, p3) = d['mm2'], d['mm3']
        v1 = R.bra_mm_at(m, nA, k, rA, list(a2), list(p2), [0]*len(nA))[0]
        v2 = R.bra_mm_at(m, nB, k, rB, list(a3), list(p3), [0]*len(nB))[0]
        ca, cb = d['c_mm']
        out(f"L{lvl:<5}{'MM':<8}{str((ca,cb)):<16}"
            f"({fmt(v1)},{fmt(v2)})".ljust(20) + f"({d2(v1,ca)},{d2(v2,cb)})")
        g1 = R.bra_aght(nA, k, rA, m); g2 = R.bra_aght(nB, k, rB, m)
        ca, cb = d['c_aght']
        out(f"{'':<11}{'AGHT':<8}{str((ca,cb)):<16}"
            f"({fmt(g1)},{fmt(g2)})".ljust(20) + f"({d2(g1,ca)},{d2(g2,cb)})")
        p1 = R.bra_prr(nA, k, rA, m); p2_ = R.bra_prr(nB, k, rB, m)
        ca, cb = d['c_prr']
        out(f"{'':<11}{'PRR':<8}{str((ca,cb)):<16}"
            f"({fmt(p1)},{fmt(p2_)})".ljust(20) + f"({d2(p1,ca)},{d2(p2_,cb)})")
        o1 = R.bra_oj_c(nA, k, rA, m)[0]; o2 = R.bra_oj_c(nB, k, rB, m)[0]
        ca, cb = d['c_oj']
        out(f"{'':<11}{'OJ-C':<8}{str((ca,cb)):<16}"
            f"({fmt(o1)},{fmt(o2)})".ljust(20) + f"({d2(o1,ca)},{d2(o2,cb)})")
    out()

# ============================================================
# 4) C-Multi-UR-AG
# ============================================================
CM = {
    128: dict(n=35, m=79, N1=11, N2=16, w1=8, w2=9,
              c_mm=(172,170), c_sm=(187,176), c_aght=(271,268), c_oj=(270,306),
              c_r_aght=(260,256), c_r_oj=(259,290)),
    256: dict(n=45, m=127, N1=15, N2=16, w1=10, w2=11,
              c_mm=(296,276), c_sm=(302,280), c_aght=(474,514), c_oj=(434,480),
              c_r_aght=(459,498), c_r_oj=(415,464)),
    512: dict(n=67, m=181, N1=19, N2=21, w1=12, w2=14,
              c_mm=(530,580), c_sm=(535,593), c_aght=(831,965), c_oj=(770,906),
              c_r_aght=(812,944), c_r_oj=(751,885)),
}

def run_cmulti():
    out("=" * 96)
    out("C-Multi-UR-AG（RSL；ω=2；实例w1=[2n,n]，实例w2=[2n+N1,n]）")
    out("=" * 96)
    out(f"{'级别':<6}{'攻击':<10}{'声明(a,b)':<16}{'复算(a,b)':<20}{'Δ(a,b)':<16}")
    for lvl, d in CM.items():
        n0, m = d['n'], d['m']
        nA, kA, rA = 2*n0, n0, d['w1']
        nB, kB, rB = 2*n0 + d['N1'], n0, d['w2']
        v1 = R.cmulti_mm(m, nA, kA, rA)[0]; v2 = R.cmulti_mm(m, nB, kB, rB)[0]
        ca, cb = d['c_mm']
        out(f"L{lvl:<5}{'MM':<10}{str((ca,cb)):<16}({fmt(v1)},{fmt(v2)})".ljust(36) + f"({d2(v1,ca)},{d2(v2,cb)})")
        s1 = R.cmulti_sm_best(m, nA, kA, rA, bmax=3)[0]; s2 = R.cmulti_sm_best(m, nB, kB, rB, bmax=3)[0]
        ca, cb = d['c_sm']
        out(f"{'':<11}{'SM':<10}{str((ca,cb)):<16}({fmt(s1)},{fmt(s2)})".ljust(36) + f"({d2(s1,ca)},{d2(s2,cb)})")
        g1 = R.bra_aght([nA], kA, [rA], m); g2 = R.bra_aght([nB], kB, [rB], m)
        ca, cb = d['c_aght']
        out(f"{'':<11}{'AGHT':<10}{str((ca,cb)):<16}({fmt(g1)},{fmt(g2)})".ljust(36) + f"({d2(g1,ca)},{d2(g2,cb)})")
        o1 = R.bra_oj_c([nA], kA, [rA], m)[0]; o2 = R.bra_oj_c([nB], kB, [rB], m)[0]
        ca, cb = d['c_oj']
        out(f"{'':<11}{'OJ':<10}{str((ca,cb)):<16}({fmt(o1)},{fmt(o2)})".ljust(36) + f"({d2(o1,ca)},{d2(o2,cb)})")
        ra1, ra2 = g1 - d['N1'], g2 - d['N2']
        ca, cb = d['c_r_aght']
        out(f"{'':<11}{'RSL-AGHT':<10}{str((ca,cb)):<16}({fmt(ra1)},{fmt(ra2)})".ljust(36) + f"({d2(ra1,ca)},{d2(ra2,cb)})")
        ro1, ro2 = o1 - d['N1'], o2 - d['N2']
        ca, cb = d['c_r_oj']
        out(f"{'':<11}{'RSL-OJ':<10}{str((ca,cb)):<16}({fmt(ro1)},{fmt(ro2)})".ljust(36) + f"({d2(ro1,ca)},{d2(ro2,cb)})")
    out()

if __name__ == "__main__":
    run_loong()
    run_piglet()
    run_block("BRA", BRA_DATA)
    run_block("BRQC", BRQC_DATA)
    run_cmulti()
    with open("schemes_final_output.txt", "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    print("[saved] schemes_final_output.txt")
