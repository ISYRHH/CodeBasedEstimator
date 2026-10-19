# 成本模型

本项目估计指定恢复路线的成本，经典与量子分别择优，不代表方案安全下界。用法见 [README](../README.md)，参数来源见[参数确认](parameter_consistency.md)。

## 输入与计量

| 后端 | 支持范围 | 时间／内存单位 |
|---|---|---|
| 经典 | CE 2.1.1 的二元 SD、多元 SD、Rank SD，以及本地 MAGE-Stern | `bit_operations`／`bits` |
| 量子 | 二元 SD 的 QSS、QMMT+；QPrange 尚未实现 | `quantum_bit_operations`／未估计 |

输出均为 $\log_2$。经典采用有限参数、位复杂度和常数内存访问计价；`--memory-bound` 仅约束经典。量子采用抽象相干访问预算，不是完整电路门数或设备运行时间。未知标签及额外 `structure` 不会被通用后端忽略；`cost_proxy` 只记录路线近似的来源。

| 问题 | `problem.kind` / `tags` | `targets=M` | `log2_solutions=s` |
|---|---|---|---|
| 普通 SD | `sd` / 无 | `1` | 每综合征有 $L=2^s$ 个可接受解 |
| QCSD | `sd` / `doom:qcsd` | 同一矩阵下可用的不同综合征数 | 与综合征数分开计数 |
| QCCF | `cfp` 或 `qccf` / `doom:qccf` | 可用的不同非零重量 $w$ 码字数 | 必须省略，由 $M$ 提供 |

SD 参数为 $(n,k,w,q)$，要求 $0<k<n$、$1\le w\le n-k$；Rank SD 使用 $(q,m,n,k,r)$，不接受显式解数。`s=0` 表示单解；省略时经典使用 CE 默认解数，量子使用单解。目标数量、轨道可用性及独立性是输入和模型假设，不由后端自动证明。

## 算法与多目标

下表区分**多个综合征**与**同一零综合征下的多个码字**；二者不叠加计数。

| 算法 | QCSD | QCCF |
|---|---|---|
| CE Prange、Stern、Dumer、BJMM | 联合优化参数和实际综合征数 $1\le u\le M$，计共享与逐目标成本 | 优化前设置 `nsolutions=log2(M)`，替换 CE 默认解数 |
| 其余 CE 二元算法 | $\log_2$ 时间减去 $\tfrac12\log_2M$，最低为 0；参数、内存不变 | 同上 |
| MAGE-Stern | 以 $1-(1-S)^u$ 计整树成功率，并计逐综合征成本 | 以 $1-(1-S_{\rm cw})^M$ 计整树成功率，固定参数的内层成本不变 |
| QSS、QMMT+ | 回退至单目标，不计 DOOM 加速 | 将 $M$ 作为解数，仅改变外层概率，并排除 $p=0$ 直接分支 |

经典非二元 QCSD 也回退为单目标，保留每综合征解数及适用配置。非二元 QCCF、量子非二元／Rank SD 不支持；额外标签或结构不适用上述回退。QCCF 各路径均不再附加目标数折扣。

CE 与量子 QCCF 均是通用 SD 多解代理，尚未完整处理零综合征的自身碰撞及排除费用；CE Prange 的 $p=0$ 分支尤其会退化为零码字。

显式 CE QCSD 模型令 $m=n-k$、$P_0$ 为单解命中概率，采用

$$
P_{\rm succ}=\min(1,uLP_0),\qquad
T=\frac{n(G+W_{\rm shared}+uW_{\rm target})+(u-1)m^2}{P_{\rm succ}}.
$$

$G$ 为 CE 消元预算，$W$ 为共享／逐目标列表工作；额外综合征各计 $m^2$ 位操作和 $m$ bits。Stern/Dumer 展开一侧列表，BJMM 仅第四张底层列表附带目标；$M=1$ 返回原 CE 结果。有限列表与内存公式见 [classical_doom.py](../codebased_estimator/classical_doom.py)、[doom_bjmm.py](../codebased_estimator/doom_bjmm.py)，构造依据为 [Sendrier §5](https://eprint.iacr.org/2011/367) 和 [Esser–May–Zweydinger §5.1](https://eprint.iacr.org/2021/1634)。

### MAGE-Stern

二元 SD、QCSD 和 QCCF 的默认经典候选。SD/QCSD 要求每综合征单解；省略解数字段时，也须满足 CE 默认解数为单解。分支存活递推采用 [Carrier–Hatey–Luzzi–Tillich §5](https://eprint.iacr.org/2026/1498)，按完整树执行计费，不考虑提前返回。

令 $S$ 为单目标整树成功率，$u$ 为物化综合征数，$m=n-k$。列表记录占 $n$ bits，归一化向量操作计 $n$ 位操作，宽度 $b_i$ 的分块消元计 $nkb_i$，每叶每综合征的代表变换计 $nk$。树成本 $C_{\rm tree}(u)$ 汇总各层消元及叶列表工作；另计一次性转换 $T_0$：

$$
T=T_0(u)+\frac{C_{\rm tree}(u)}{P_{\rm succ}},\qquad T_0(u)=(n+u)m^2.
$$

QCSD 联合优化树参数及 $u$；QCCF 固定 $u=1$，全部 $M$ 个码字只进入外层概率，时间与内存沿用单综合征计价，包括零代表本可省去的变换和存储。该结论针对固定参数，重新优化后树与内存可以变化。现有 $p\ge1$ 约束结合完整信息集满秩排除零码字。

两种并集公式均假设不同目标的整树失败事件独立，无须 $uS\ll1$。QCCF 的 $S_{\rm cw}$ 仍是随机重量支撑代理，并非满秩条件下真实码字分布的精确概率。实现采用 CE 基本操作价格，未复现论文的逻辑门 RAM 与稀疏存储模型。固定点评估、树搜索和批量优化分别见 [mage_costs.py](../codebased_estimator/mage_costs.py)、[mage_search.py](../codebased_estimator/mage_search.py)、[mage_targets.py](../codebased_estimator/mage_targets.py)。

## 量子成本

QSS/QMMT+ 依 [Kachigar–Tillich §4–5](https://arxiv.org/abs/1703.00263v2) 优化直接、完整列表与量子游走分支。设 $P$ 为重量命中概率、$\sigma$ 为表示存活代理、$\rho$ 为共同秩条件概率、$L$ 为每综合征解数：

$$
P_{\rm eff}=\rho[1-(1-P\sigma)^L],\qquad
T=T_0+\frac{C_{\rm inner}}{\sqrt{P_{\rm eff}}}.
$$

共同秩条件留在并集之外，QCCF 取 $L=M$。固定参数的内层预算包含消元、列表与查找，不再叠加解数收益。矩阵配置默认 `partial-ge-aggregate-v1`，可选 `partial-m4ri-aggregate-v1`；两者均假设相干主元选择、查表、更新及逆算。

概率并集采用独立命中假设，列表按有限规模与平均负载定价。公式与搜索见 [quantum_costs.py](../codebased_estimator/quantum_costs.py)、[list_costs.py](../codebased_estimator/list_costs.py)、[matrix_costs.py](../codebased_estimator/matrix_costs.py)、[quantum_search.py](../codebased_estimator/quantum_search.py)。

## 内置 Hamming 方案的 DOOM 映射

[hamming.py](../codebased_estimator/hamming.py) 将 42 组参数展开为 119 条路线。下表 $r$ 为基础循环块长，Mito 的 $d=2^\ell$ 为环坐标数。

| 方案 | 密钥恢复 | 消息恢复 | `doom="auto"` 目标数 |
|---|---|---|---|
| BIKE_MLThre、TRIKE | QCCF | QCSD | $r$ |
| HARE、NSS-HQC、TriQ-KEM、QUBE | QCSD | `u_only`／`composite` QCSD | $r$ |
| Mito | `baseline`／`parity` QDSD 代理 | `u_only` QDSD／`composite` QCSD | key、`u_only`：$dr$；`composite`：$r$ |
| QCTM | 未实现 | QCSD | $19$ |
| UVW-KEM | 未实现 | 多元 SD | $1$ |

QCSD 路线每综合征单解。`doom="none"` 将可用路线改为普通 SD、单目标、单解，仍保留所有候选路线。通用路线合并块重量，不另计不平衡重量、不交支撑、折叠及密钥／消息后处理收益；完整目标轨道按可用性假设处理。

消息路线统一忽略截断、压缩残差和未知消息成本，视 $v-\operatorname{Encode}(m)$ 为免费可得。以下为完整核心代理的 $(N,K,W)$，不是从真实未知消息密文到综合征的完整归约：

| 方案 | `u_only` | `composite` |
|---|---|---|
| HARE、TriQ-KEM | $(2r,r,2w_r)$ | $(3r,r,2w_r+w_e)$ |
| NSS-HQC | $(2r,r,w_{r1}+w_{r2})$ | $(3r,r,w_{r1}+w_{r2}+w_e)$ |
| Mito，$W_u=\sum_i(w_r[i]+w_t[i])$ | $(2dr,dr,W_u)$ | $((2d+1)r,dr,W_u+w_e)$ |
| QUBE | $(3r,2r,2w_f+w_g)$ | $(4r,2r,2w_f+w_g+w_e)$ |

Mito 复合路线保留第零环分量投影，只采用 $r$ 个同时循环移位目标。密钥 `parity` 路线令 $W=\sum_i(w_x[i]+w_y[i])$，将 `baseline` 的 $(2dr,dr,W)$ 改为 $(2dr,dr-d,W)$；新增 $d$ 个独立校验行的秩是精确的，成本按同秩随机 SD 估计，不再额外扣除 $d$ 位。结构与来源由 [MitoKeyParity](../codebased_estimator/mito_parity.py) 及 `instance.cost_proxy` 保存。

## 结果与复核

同一方案、参数集和恢复目标下，以相同选项比较可行、已计算且时间单位一致的结果；经典与量子分别选最小时间，精确并列全部保留。参数搜索受预算限制，不保证全局最优；量子结果也不表示内存可行。

JSON 保存完整 `instance`、`options`、模型版本、成本分解和搜索记录，可据此复核。CSV 中 `is_best`／`is_best_route` 区分路线内／跨路线胜者，`effective_doom`／`effective_targets` 表示实际模型。逐实例 `references` 保留来源，详细推导和独立核验保留在本地 `local/path_audit/`。
