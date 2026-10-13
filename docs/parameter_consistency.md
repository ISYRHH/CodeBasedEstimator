# Mito 和 QUBE 参数确认

2026-10-14 核对结果：Mito 的 9 组参数与 Spec 表 3.5–3.7（PDF p.33／印刷 p.32）及 36 份实现参数头文件一致；QUBE 的 5 组参数（含 QUBE-192）与 Spec 表 1–2（PDF pp.10–11）及 5 份 Reference 实现一致。采用值及逐项来源见 [hamming_parameters.py](../codebased_estimator/hamming_parameters.py)。

| 字段 | 含义 |
|---|---|
| `r` | 基础循环环长度，bits |
| `d` | Mito 环坐标数 `2^ℓ`，对应 `PARAM_L` |
| `n1`、`n2` | 外层 RS 码长（GF(256) 符号数）、内层重复 RM 码长（bits） |
| `code_length` | `n1*n2`，即 Mito 的 `n′`、QUBE 的 `L`，bits |
| `message_bits` | Mito 为 `8*PARAM_K_BYTES`，QUBE 为 `8*PARAM_K` |
| `we` | 在完整长度 `r` 上采样的附加误差重量 |
| Mito `wx,wy,wr,wt` | 长度为 `d` 的逐块重量数组；同一数组各块支撑不交，不要求不同数组之间不交 |
| QUBE `wx,wy,wf,wg` | 标量块重量；两块 `x` 共用 `wx`，两块 `f` 共用 `wf` |

全部 14 组满足 `code_length=n1*n2` 和 `0 < message_bits < code_length < r`。

Mito-1-E-256 的基础环长为 `32261`、编码长度为 `32256`。Spec 表 4.5 混用了编码长度；目录按基础参数表和实现采用 `r=32261`。

QUBE 统一采用 Spec/Reference 的五组配置。Optimized 的 `qube-3/4/5` 编码长度超过各自环长，`qube-6/7/8` 属于未纳入目录的其他参数变体，不混作来源。
