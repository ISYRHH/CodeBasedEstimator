# 成本模型

本项目估计指定恢复路线的成本，经典与量子分别择优，不代表方案安全下界。用法见 [README](../README.md)，参数版本见[参数说明](parameter_consistency.md)。

## 输入与计量

| 后端 | 支持范围 | 时间／内存单位 |
|---|---|---|
| 经典 | CE 2.1.1 的二元 SD、多元 SD、Rank SD，以及本地 MAGE-Stern | `bit_operations`／`bits` |
| 量子 | 二元 SD 的 QSS、QMMT+，以及不带块画像的通用 QPrange | `quantum_bit_operations`／未估计 |

输出均为 $\log_2$。经典采用有限参数、位复杂度和常数内存访问计价；`--memory-bound` 仅约束经典。量子采用抽象相干访问预算，不是完整电路门数或设备运行时间。未知标签及额外 `structure` 不会被通用后端忽略；`cost_proxy` 只记录路线近似的来源。

| 问题 | `problem.kind` / `tags` | `targets=M` | `log2_solutions=s` |
|---|---|---|---|
| 普通 SD | `sd` / 无 | `1` | 每综合征有 $L=2^s$ 个可接受解 |
| QCSD | `sd` / `doom:qcsd` | 同一矩阵下可用的不同综合征数 | 与综合征数分开计数 |
| QCCF | `cfp` 或 `qccf` / `doom:qccf` | 可用的不同非零重量 $w$ 码字数 | 必须省略，由 $M$ 提供 |

SD 参数为 $(n,k,w,q)$，要求 $0<k<n$、$1\le w\le n-k$；Rank SD 使用 $(q,m,n,k,r)$，不接受显式解数。`s=0` 表示单解；省略时经典使用 CE 默认解数，量子使用单解。给定块画像时，经典默认的 log₂ 解数为 $\max(0,\sum_i\log_2\binom{n_i}{w_i}-(n-k))$，均匀与块选择候选共享此值。目标数、轨道可用性及独立性是输入和模型假设。

## 算法与多目标

下表区分**多个综合征**与**同一零综合征下的多个码字**；二者不叠加计数。$M$ 指当前候选可用的目标数，块权重策略可能只使用保持画像的子集。

| 算法 | QCSD | QCCF |
|---|---|---|
| CE Prange、Stern、Dumer、二层 BJMM | 联合优化参数和实际综合征数 $1\le u\le M$，计共享与逐目标成本；保留原 CE 单目标候选 | 优化前设置 `nsolutions=log2(M)`，替换 CE 默认解数 |
| CE 三层 BJMM | 独立固定深度为 3 后优化，再减去 $\tfrac12\log_2M$；与二层显式 DOOM 和原 CE 候选择优 | 由普通 CE BJMM 在二层与三层间择优，无额外折扣 |
| 其余 CE 二元算法 | $\log_2$ 时间减去 $\tfrac12\log_2M$，最低为 0；参数、内存不变 | 使用 CE 多解模型，无额外折扣 |
| MAGE-Stern | 以 $1-(1-S)^u$ 计整树成功率，并计逐综合征成本 | 以 $1-(1-S_{\rm cw})^M$ 计整树成功率，固定参数的内层成本不变 |
| QSS、QMMT+ | 回退至单目标，不计 DOOM 加速 | 将 $M$ 作为解数，仅改变外层概率，并排除 $p=0$ 直接分支 |

经典非二元 QCSD 也回退为单目标，保留每综合征解数及适用配置。非二元 QCCF、量子非二元／Rank SD 不支持；额外标签或结构不适用上述回退。

CE 与量子 QCCF 采用通用 SD 多解成本代理，尚未完整处理零综合征的自身碰撞及排除费用。经典 Prange 在此解释为码字搜索成本代理并参与择优，不将普通 SD 的零信息向量分支当作可执行的非零码字求解器。

显式 CE QCSD 模型令 $m=n-k$、$P_0$ 为单解命中概率，以线性并集近似成功概率：

$$
P_{\rm succ}=\min(1,uLP_0),\qquad
T=\frac{n[G+J(u)(W_{\rm shared}+uW_{\rm target})]+(u-1)m^2}{P_{\rm succ}}.
$$

$G$ 为 CE 消元预算，$W$ 为共享／逐目标列表工作；额外综合征各计 $m^2$ 位操作和 $m$ bits。除 Stern 外 $J(u)=1$；BJMM 的表示重复次数已包含在 $W$ 中。Stern/Dumer 展开一侧列表，BJMM 仅第四张底层列表附带目标；$M=1$ 返回原 CE 结果。有限列表与内存公式见 [classical_doom.py](../codebased_estimator/classical_doom.py)、[doom_bjmm.py](../codebased_estimator/doom_bjmm.py)，构造依据为 [Sendrier §5](https://eprint.iacr.org/2011/367) 和 [Esser–May–Zweydinger §5.1](https://eprint.iacr.org/2021/1634)。

`ce-doom-finite-v2` 在共同参数域、$u=1$ 时逐点对齐 CE 2.1.1 的时间与内存，保留整数列表、取整和表示重复成本。Stern 消元不乘投影次数；二层 BJMM 使用流式末级合并。BJMM 比较原 CE、显式二层 DOOM 和三层 CE/$\sqrt M$ 三种候选，折扣仅作用于最后一种。带画像时还比较完整轨道与保持画像的子集。

### MAGE-Stern

二元 SD、QCSD 和 QCCF 的默认经典候选。SD/QCSD 要求每综合征单解；省略解数字段时，也须满足经典默认解数为单解。分支存活递推采用 [Carrier–Hatey–Luzzi–Tillich §5](https://eprint.iacr.org/2026/1498)，按完整树执行计费，不考虑提前返回。

令 $S$ 为单目标整树成功率，$u$ 为物化综合征数，$m=n-k$。列表记录占 $n$ bits，归一化向量操作计 $n$ 位操作，宽度 $b_i$ 的分块消元计 $nkb_i$，每叶每综合征的代表变换计 $nk$。树成本 $C_{\rm tree}(u)$ 汇总各层消元及叶列表工作；另计一次性转换 $T_0$：

$$
T=T_0(u)+\frac{C_{\rm tree}(u)}{P_{\rm succ}},\qquad T_0(u)=(n+u)m^2.
$$

QCSD 联合优化树参数及 $u$；QCCF 固定 $u=1$，使用的 $M$ 个码字只进入外层概率，保留单综合征的变换与存储开销。固定参数的内层成本不变，重新优化后的树与内存可以变化。正信息重量和满秩信息集约束排除零码字。

两种并集公式均假设不同目标的整树失败事件独立，无须 $uS\ll1$。QCCF 的 $S_{\rm cw}$ 仍是随机重量支撑代理，并非满秩条件下真实码字分布的精确概率。实现采用 CE 基本操作价格，未复现论文的逻辑门 RAM 与稀疏存储模型。固定点评估、树搜索和批量优化分别见 [mage_costs.py](../codebased_estimator/mage_costs.py)、[mage_search.py](../codebased_estimator/mage_search.py)、[mage_targets.py](../codebased_estimator/mage_targets.py)。

## 量子成本

通用 [QPrange](qprange.md) 复用下述量子模型的 `ell=p=0` 直接点，不运行参数搜索。二元 QCSD 沿用单目标回退；非零码字 QCCF 和块画像暂不支持，输入不会被默默忽略。原算法名称列表不变，但支持范围内的 QPrange 由占位变为可计算，会参与量子择优。

QSS/QMMT+ 依 [Kachigar–Tillich §4–5](https://arxiv.org/abs/1703.00263v2) 优化直接、完整列表与量子游走分支。设 $P$ 为重量命中概率、$\sigma$ 为表示存活代理、$\rho$ 为共同秩条件概率、$L$ 为每综合征解数：

$$
P_{\rm eff}=\rho[1-(1-P\sigma)^L],\qquad
T=T_0+\frac{C_{\rm inner}}{\sqrt{P_{\rm eff}}}.
$$

共同秩条件留在并集之外，QCCF 取 $L=M$。解数只影响外层成功概率，固定参数的内层预算不再叠加解数收益。矩阵配置默认 `partial-ge-aggregate-v1`，可选 `partial-m4ri-aggregate-v1`；两者均使用抽象相干主元选择、更新与逆算，M4RI 实际采用行表时另假设相干查表。

多解并集假设给定共同秩事件后命中独立；列表分支按有限规模与平均负载定价。公式与搜索见 [quantum_costs.py](../codebased_estimator/quantum_costs.py)、[list_costs.py](../codebased_estimator/list_costs.py)、[matrix_costs.py](../codebased_estimator/matrix_costs.py)、[quantum_search.py](../codebased_estimator/quantum_search.py)。

## 内置 Hamming 方案的 DOOM 映射

[hamming.py](../codebased_estimator/hamming.py) 将 41 组参数展开为 117 条路线。下表 $r$ 为基础循环块长，Mito 的 $d=2^\ell$ 为环坐标数。

| 方案 | 密钥恢复 | 消息恢复 | `doom="auto"` 目标数 |
|---|---|---|---|
| BIKE_MLThre、TRIKE | QCCF | QCSD | $r$ |
| HARE、NSS-HQC、TriQ-KEM、QUBE | QCSD | `u_only`／`composite` QCSD | $r$ |
| Mito | `baseline`／`parity` QDSD 代理 | `u_only` QDSD／`composite` QCSD | key、`u_only`：$dr$；`composite`：$r$ |
| QCTM | 未实现 | QCSD | $19$ |
| UVW-KEM | 未实现 | 多元 SD | $1$ |

QCSD 路线每综合征单解。`doom="none"` 将可用路线改为普通 SD、单目标、单解，仍保留所有候选路线。已知块重量默认进入支持的外层概率模型；不另计不交支撑、折叠及密钥／消息后处理收益，完整目标轨道按可用性假设处理。

下列方案的 `u_only` 路线仅用完整 $u$ 方程恢复临时随机量。`composite` 才假设 $v-\operatorname{Encode}(m)$ 免费可得，并忽略截断和压缩残差；它不是实际未知消息密文的完整恢复归约。两种路线均不计方案层面的消息恢复及验证。完整核心代理的 $(N,K,W)$ 为：

| 方案 | `u_only` | `composite` |
|---|---|---|
| HARE、TriQ-KEM | $(2r,r,2w_r)$ | $(3r,r,2w_r+w_e)$ |
| NSS-HQC | $(2r,r,w_{r1}+w_{r2})$ | $(3r,r,w_{r1}+w_{r2}+w_e)$ |
| Mito，$W_u=\sum_i(w_r[i]+w_t[i])$ | $(2dr,dr,W_u)$ | $((2d+1)r,dr,W_u+w_e)$ |
| QUBE | $(3r,2r,2w_f+w_g)$ | $(4r,2r,2w_f+w_g+w_e)$ |

Mito 复合路线保留第零环分量投影，只采用 $r$ 个同时循环移位目标。密钥 `parity` 路线（`mito-key-parity-rank-v1`）令 $W=\sum_i(w_x[i]+w_y[i])$，将 `baseline` 的 $(2dr,dr,W)$ 改为 $(2dr,dr-d,W)$；新增 $d$ 个独立校验行的秩是精确的，成本按同秩随机 SD 估计，不再额外扣除 $d$ 位。这是通用成本近似，不是针对结构化 P 问题的专用攻击。结构与来源由 [MitoKeyParity](../codebased_estimator/mito_parity.py) 及 `instance.cost_proxy` 保存。

## Unbalanced 外层块概率

`AttackInstance.block_profile` 保存 `lengths`、`weights`，分别合计为 $N,W$，例如 `{"lengths": [100, 100], "weights": [12, 4]}`。Hamming 映射默认提供已知固定重量；BIKE/TRIKE 消息错误只有总重量，QCTM/UVW 未提供块画像。`--unbalanced none` 或 `hamming_instances(unbalanced="none")` 使用总重量基线。

设尾区包含每块的 $R_i$ 个坐标，非尾区允许总计 $p$ 个错误。各块独立均匀选坐标，有限成功概率为

$$
P_{\boldsymbol R}(p)=[z^p]\prod_i\left(\sum_j
\frac{\binom{n_i-R_i}{j}\binom{R_i}{w_i-j}}{\binom{n_i}{w_i}}z^j\right).
$$

信息区内部均匀洗牌后，半区／四分区、零窗等条件分割因子沿用原公式。以块概率替换总重量事件后，再计算解数／目标并集和重复次数；不扣组合空间差，原始均匀策略仍参与择优。

Prange 块配额采用离散凹优化；其他路径对小实例枚举配额，对较大实例作有限整数搜索。概率使用二项式计数及稳定卷积，矩阵满秩条件仍使用原随机码代理。

* **CE**：替换外层重复项后优化，保留列表、表示、消元和内存公式。适配 CE 2.1.1 的十种二元算法及其深度子算法，其他入口标记 `generic_fallback`。
* **显式 QCSD**：先修正单目标事件，再联合优化算法参数和批量大小。
* **量子**：先修正 $P$，再计算 $\rho[1-(1-P\sigma)^L]$；$T_0$、$\rho$ 和内层成本不变，QCSD 单目标回退保留画像。
* **MAGE-Stern**：首个 pivot block 的配额分布进入树递推，后续坐标均匀洗牌。画像搜索也可退回均匀采样，实际策略见 `cost_breakdown.unbalanced.selected_strategy`。

受限内存下，上游 BJMMdw/pdw 隐藏搜索可能漏掉可行约束；本地块概率适配按实际位内存筛选，修正这一问题，因此该情况下不保证与原 CE 结果相同。

Mito 的 dyadic 作用会置换块重量，因此比较保持画像的目标子群与全轨道均匀策略；不同画像不能免费共用最优配额。`target_permutations` 描述等大小的目标类，非整类截断目标数回退为单目标。量子 QCCF 暂不支持不同画像的目标并集。Mito parity 的块重量／条件秩联合模型尚未建立，不叠加 unbalanced。

显式解数假定所有计数的解均满足画像；目标与解之间的相关性仍沿用原代理。`metadata.unbalanced`、成本分解和搜索记录给出实际选中的策略及配额。

## 结果与复核

同一方案、参数集和恢复目标下，以相同选项比较可行、已计算且时间单位一致的结果；经典与量子分别选最小时间，精确并列全部保留。参数搜索受预算限制，不保证全局最优；量子结果也不表示内存可行。

JSON 保存输入、选项、模型版本、成本分解和搜索记录。`instance.cost_proxy` 记录路线近似；`instance.references` 与结果的 `references` 分别记录参数和成本模型来源。

`assumptions` 只列影响结果解读的条件与限制：路线层描述恢复范围、轨道有效性和结构近似；算法层描述实际采用的概率与成本假设。参数、公式、状态和实现细节由相应字段或本说明承载，不在假设中重复。同一条件使用统一措辞，网页按适用路线和算法合并显示。

可用目标数不等于实际使用数。CLI CSV 的 `is_best`／`is_best_route` 区分路线内／跨路线胜者，`effective_doom`／`effective_targets` 表示实际模型。
