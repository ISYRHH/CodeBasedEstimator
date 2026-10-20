# Hamming 参数确认

## TRIKE v1.6

参数采用 TRIKE 规范 v1.6，内置于 [hamming_parameters.py](../codebased_estimator/hamming_parameters.py)。

| 参数集 | `r` | `w` | `t` | `d = w/3` |
|---|---:|---:|---:|---:|
| TRIKE-1 | 9437 | 81 | 201 | 27 |
| TRIKE-3 | 19181 | 123 | 319 | 41 |
| TRIKE-5 | 32987 | 165 | 429 | 55 |
| TRIKE-7 | 62981 | 249 | 659 | 83 |
| TRIKE-9 | 103043 | 333 | 877 | 111 |

总密钥重量 `w=3d`，三个密钥块各重 `d`，`t` 为三个误差块的总重量。估计器采用密钥恢复 `(n,k,w)=(3r,2r,w)`、消息恢复 `(3r,r,t)` 和 `M=r` 的 DOOM 目标数。

v1.6 不再包含 TRIKE-2，旧调用需选择 v1.6 参数集。TRIKE-3 属于 NIST level 3 参数集；v1.6 的 ICCS 实例为 TRIKE-1/5/7/9。

## Mito 和 QUBE

Mito 的 9 组参数、QUBE 的 5 组参数（含 QUBE-192）均按提交规范和参考实现核对。采用值见 [hamming_parameters.py](../codebased_estimator/hamming_parameters.py)。

| 字段 | 含义 |
|---|---|
| `r` | 基础循环环长度，bits |
| `d` | Mito 环坐标数 `2^ℓ` |
| `n1`、`n2` | 外层 RS 码长（GF(256) 符号数）、内层重复 RM 码长（bits） |
| `code_length` | `n1*n2`，即 Mito 的 `n′`、QUBE 的 `L`，bits |
| `message_bits` | 消息长度，bits |
| `we` | 在完整长度 `r` 上采样的附加误差重量 |
| Mito `wx,wy,wr,wt` | 长度为 `d` 的逐块重量数组；同一数组各块支撑不交，不要求不同数组之间不交 |
| QUBE `wx,wy,wf,wg` | 标量块重量；两块 `x` 共用 `wx`，两块 `f` 共用 `wf` |

全部 14 组满足 `code_length=n1*n2` 和 `0 < message_bits < code_length < r`。

Mito-1-E-256 的基础环长为 `32261`、编码长度为 `32256`。规范的安全估计部分混用了编码长度；目录按基础参数和参考实现采用 `r=32261`。

QUBE 统一采用提交规范和参考实现的五组配置，排除编码长度超过环长的旧优化配置及其他参数变体。
