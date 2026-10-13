# Mito 和 QUBE 参数一致性

2026-10-14 核对：Mito 采用 Spec 表 3.5–3.7（印刷 p.32）与对应实现一致的 9 组参数；QUBE 采用 Spec 表 1–2（pp.10–11）与 Reference 一致的 5 组参数，包括 QUBE-192。完整数值见 [hamming_parameters.py](../codebased_estimator/hamming_parameters.py)。

| 字段 | 含义 |
|---|---|
| `r` | 基础循环环长度，bits；不同于编码长度和 SD 总长度 |
| `d` | Mito 环坐标数 `2^ℓ`（`PARAM_L`），不是指数 `ℓ` |
| `n1`、`n2` | 外层 RS 码长度（GF(256) 符号数）、内层重复 RM 码长度（bits） |
| `code_length` | `n1*n2`，即 Mito 的 `n′`、QUBE 的 `L`，bits |
| `message_bits` | 消息位数；Mito 为 `8*PARAM_K_BYTES`，QUBE 为 `8*PARAM_K` |
| `we` | 在整个长度 `r` 上采样的附加误差重量，不是截断后重量 |
| Mito `wx,wy,wr,wt` | 长度为 `d` 的逐环坐标重量数组；每个数组对应的各坐标支撑不交 |
| QUBE `wx,wy,wf,wg` | 标量块重量；两块 `x` 共用 `wx`，两块 `f` 共用 `wf` |

全部 14 组满足 `0 < message_bits < code_length < r`。现有消息恢复路线只使用完整 `u`，其 SD 重量不包含 `we`。

Mito-1-E-256 的 `r=32261`、`code_length=32256`。Spec 表 4.5（印刷 p.49）误用编码长度计算 SD 维数；现有 key 路线按正确环长得到 `(N,K,W)=(129044,64522,269)`。

QUBE Optimized 不作为上述五组的参数来源：`qube-3/4/5` 的编码长度超过各自环长，`qube-6/7/8` 是未纳入目录的历史变体；统一以 Spec 与 Reference 为准。
