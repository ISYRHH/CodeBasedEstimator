# Hamming 参数说明

参数值、版本及兼容配置备注统一保存在 [hamming_parameters.py](../codebased_estimator/hamming_parameters.py)。网页 **Parameters** 或 `python -m codebased_estimator hamming --list` 可查看完整目录；恢复路线见[模型说明](model.md#内置-hamming-方案的-doom-映射)。

## TRIKE v1.6

采用规范 v1.6 的 TRIKE-1/3/5/7/9，不包含 TRIKE-2。总密钥重量 `w=3d`，三个密钥块各重 `d`，`t` 为误差总重量。TRIKE-3 为 NIST level 3 参数集；v1.6 的 ICCS 实例提供 TRIKE-1/5/7/9。

## Mito 和 QUBE

目录包含 Mito 的 9 组参数和 QUBE 的 5 组参数（含 QUBE-192），按提交规范和参考实现核对。

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
