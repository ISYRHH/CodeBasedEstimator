# -*- coding: utf-8 -*-
"""brqc_fix_check.py — BRQC-256-3n 权向量转录修正的前后对照（快速版）。

背景：本文此前把 3n 实例权向量 (wr1, we, wr2) 误录为 (6,8,6)；
规范表 2 的 BRQC-256 应为 (6,8,7)（BRA-256 才是 (6,8,6)，两表相邻导致串行）。
预期（对照规范声明）：AGHT=1023、PRR=1003、MM=295。
"""
import sys, os
_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.dirname(_here)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import rank_sd_schemes as R

m, n0, k = 163, 161, 161
nB = [n0, n0, n0]

print("BRQC-256 3n（声明：AGHT 1023 / PRR 1003 / MM 295）")
for tag, rv3 in (("修正前 (6,8,6)", [6, 8, 6]), ("修正后 (6,8,7)", [6, 8, 7])):
    g = R.bra_aght(nB, k, list(rv3), m)
    p = R.bra_prr(nB, k, list(rv3), m)
    print(f"  [{tag}] AGHT={g:.2f}  PRR={p:.2f}")

res = R.bra_mm_at(m, nB, k, [6, 8, 7], [7, 1, 2], [0, 0, 0], [0, 0, 0])
print(f"  MM（表 6 参数 a=(1,2,7) 按坐标对齐取 (7,1,2)，p=0, h=0）：{res[0]:.2f}")
res = R.bra_mm_at(m, nB, k, [6, 8, 6], [7, 1, 2], [0, 0, 0], [0, 0, 0])
print(f"  MM（修正前参数下同元组，仅供参考）：{res[0]:.2f}")
