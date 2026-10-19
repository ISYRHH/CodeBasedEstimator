# 成本模型

本项目估计指定译码路线的成本，经典与量子分别比较。以下均为有限参数成本模型或明确标记的代理，不构成方案安全下界。参数来源见[参数确认](parameter_consistency.md)，用法见 [README](../README.md)。

## 输入与适用范围

| 后端 | 支持范围 | 时间／内存单位 |
|---|---|---|
| 经典 | CE 2.1.1 的二元 SD、多元 SD、Rank SD；下述 QCSD/QCCF 代理 | `bit_operations`／`bits` |
| 量子 | 二元 SD 的 QSS、QMMT+；下述 QCCF 代理 | `quantum_bit_operations`／未估计 |

成本均输出 $\log_2$。经典采用有限复杂度、位复杂度和常数内存访问模型；内存上限只约束经典。量子采用抽象相干访问和归一化操作预算，不表示完整电路门数。QPrange 尚未实现。

`AttackInstance` 描述一条恢复路线。`Problem("sd", ...)` 使用 $(n,k,w,q)$，要求 $0<k<n$、$1\le w\le n-k$；Rank SD 使用 $(q,m,n,k,r)$，不接受显式解数。`structure` 表示必须由专用模型处理的约束，内置通用后端不会忽略它；`cost_proxy` 仅描述已选近似的来源，不改变调度或放宽检查。

| 机制 | `problem.kind` / `tags` | `targets=M` | `log2_solutions` |
|---|---|---|---|
| 普通 SD | `sd` / 无 | `1` | 每个综合征的可接受解数对数 |
| QCSD | `sd` / `doom:qcsd` | 同一矩阵下不同、可用的综合征数 | 与目标数分开计数 |
| QCCF | `cfp` 或 `qccf` / `doom:qccf` | 不同、可用的非零重量 $w$ 码字数 | 必须省略；由 `targets` 提供 |

普通 SD 的 `log2_solutions=0` 表示单解；省略时经典使用 CE 默认解数，量子按单解处理。QCSD 不把 $\log_2M$ 再加入解数。轨道数量、可用性和相关性均须由路线说明，后端不会自动证明。

仅含 `doom:qcsd` 且无额外结构时，经典非二元输入回退为单目标 SDFq，量子二元输入回退为单目标 SD；保留每综合征解数、矩阵配置及适用的内存约束，不计 DOOM 加速。回退由 `metadata.doom.model="single_target_fallback"`、`effective_tags=[]`、`effective_targets=1` 标识。非二元 QCCF、量子非二元／Rank SD、未知标签或结构仍不支持。

## 经典成本

普通单目标路线调用 [CE 后端](../codebased_estimator/backend.py)。二元 DOOM 在优化前按目标语义分派：

| 机制／算法 | 处理方式 |
|---|---|
| QCSD：Prange、Stern、Dumer、BJMM | `ce-doom-finite-v1`，联合优化算法参数、消元块宽及实际目标数 $1\le u\le M$ |
| QCSD：其余 CE 二元经典算法 | `sqrt_targets_approximation`，从 CE 时间减去 $\frac12\log_2M$，最低为 0；参数和内存不变 |
| QCCF：二元经典算法 | 优化前设置 CE 的 `nsolutions=log2(M)`，替换默认解数，不再叠加目标折扣 |

显式 QCSD 模型令 $m=n-k$、$S$ 为每综合征解数、$P_0$ 为一个解命中所选重量分布的概率：

$$
P_{\rm succ}=\min(1,uSP_0),\qquad
T=\frac{n(G+W_{\rm shared}+uW_{\rm target})+(u-1)m^2}{P_{\rm succ}},
$$
$$
B=n(B_{\rm matrix}+B_{\rm shared}+uB_{\rm target})+(u-1)m.
$$

$G,B_{\rm matrix}$ 使用 CE 矩阵预算；第一份综合征已包含在基线中，其余各计 $m^2$ 位操作及 $m$ bits。Prange 无列表项；Stern/Dumer 共享一侧列表，另一侧按目标展开；BJMM 采用两层表示、仅第四张底层列表附带目标。列表大小及匹配数用有限组合数和均值定价。

$M=1$ 返回原 CE 结果，$M>1$ 也保留单目标候选。大实例采用有预算的确定性搜索，`metadata.doom.search` 记录范围与停止原因，`active_targets` 记录实际使用数量。公式、边界及定点重放见 [classical_doom.py](../codebased_estimator/classical_doom.py) 与 [doom_bjmm.py](../codebased_estimator/doom_bjmm.py)；构造依据为 [Sendrier §5](https://eprint.iacr.org/2011/367) 和 [Esser–May–Zweydinger §5.1](https://eprint.iacr.org/2021/1634)。目标相关性和有限多项式价格均属模型假设。

经典 QCCF 仍是通用 SD 多解代理：零综合征下 Prange 的 $p=0$ 分支退化为零码字，自身碰撞及排除费用未专门定价，不能将结果解释为已证明的非零码字搜索成本。

### MAGE-Stern

`MAGE-Stern` 属于二元 SD 的默认经典候选，与其他算法分别估计并由统一报告择优。输入限于二元普通 SD 或 QCSD、每综合征一个可接受解、无额外 `structure`。显式 `log2_solutions=0` 使用单解；省略时仅在 CE 默认解数也为单解时适用。QCCF、非二元、Rank SD 和专用 regular/projective 算法尚不支持。

算法分支递推来自 [Carrier–Hatey–Luzzi–Tillich，ePrint 2026/1498 §5](https://eprint.iacr.org/2026/1498)。实现只保留项目现有的计量约定：每个归一化向量操作计 $n$ 位操作、列表记录占 $n$ bits、常数内存访问费用。未实现论文的逻辑门 RAM 模型或稀疏列表内存模型。因此论文表中的时间和内存收益不是此实现的预期校准值。

令 $u\le M$ 为实际使用的目标数，$m=n-k$；左右列表重量为 $p,p-\delta$，长度取 $k_L=\lfloor k/2\rfloor$、$k_R=k-k_L$，保留奇数码维数和原始输入。有限列表大小为

$$
L_L=\binom{k_L}{p},\quad L_R=\binom{k_R}{p-\delta},\quad D=L_LL_R/2^\ell.
$$

这些计数复用现有 Stern DOOM 原语。两侧列表均按完整向量存储，右表按目标展开；候选检查沿用 CE 的匹配输出聚合计价。生成矩阵方向的每层普通部分消元计 $G_i=nkb_i$ 位操作，$b_i>0$、$\sum_i b_i=k$，暂不假设额外的部分 M4RI 加速。每个叶节点对每个目标做一次完整代表向量变换，计 $nk$ 位操作，其后列表工作为

$$
C_{\rm leaf}=n\left[L_L+u(L_R+D+k)\right],\qquad
C_{\rm tree}=\sum_{i=1}^{N}\left(\prod_{j=1}^{i}r_j\right)G_i
+\left(\prod_{j=1}^{N+1}r_j\right)C_{\rm leaf}.
$$

初次从校验矩阵输入转换为生成矩阵及目标代表，另计一次性 $T_0=(n+u)m^2$。这是一套使用 CE 基本操作价格的生成矩阵有限成本代理；它采用完整向量和普通部分消元，对论文的低层实现优化取较保守的处理，但不构成经证明的电路成本上界。内存和总时间为

$$
B=\max\{n(m+u),\ n(k+u+L_L+uL_R)\},\qquad
T=T_0+C_{\rm tree}/P_{\rm succ}.
$$

单目标树成功率 $S=P_{\rm tree}$ 按论文式 (5.10)、(5.14)–(5.15) 的多类型分支存活递推计算，数值使用存活概率的对数，避免小成功率被相减消去。末层零窗口使用剩余重量 $w-(2p-\delta)$，修正原文式 (5.11) 与 (5.14) 的不一致。MAGE-Stern 的 `ce-mage-generator-v2` 模型使用论文的多目标公式

$$
P_{\rm succ}=1-(1-S)^u.
$$

这里明确假设不同目标的整树失败事件相互独立；只有随机误差向量独立，还不足以推出共享随机树后的无条件独立。公式无须 $uS\ll1$，该条件只用于 $P_{\rm succ}\approx uS$ 的线性近似。每次尝试计完整树成本，不提前停止，重新随机化的整树尝试按独立重复处理。不额外叠加 $\sqrt M$ 折扣，也不把同一树内叶子当作独立信息集。秩与随机矩阵处理、目标的轨道可用性及相关性仍属于模型假设。

优化器采用有限预算的确定性多起点搜索，联合细化列表参数、树分块、重复数和目标批量，记录实际搜索范围与停止原因。它保留同一生成矩阵模型下的单层退化策略，只返回自身搜索结果；可行点的 `metadata.selected_strategy` 为 `single_level` 或 `multilevel`。内存界在固定点评估与搜索中都生效；时间最优不意味着内存最小。

固定树的成本写成 $T(u)=n m^2+m^2u+(A+Cu)/(1-(1-S)^u)$，其中 $A>0$ 是共享树成本，$C>0$ 是每目标树成本。这一函数严格凸，故可用相邻整数差分的符号二分寻找内存允许范围内的最优批量；代码使用整数／有理数成本系数、对数判号及近并列时的高精度回退。该子问题的凸性不代表外层树参数搜索全局最优，固定点评估仍受总预算限制。

MAGE-Stern 的原生结果可能比现有 CE Stern/M4RI 更慢，也可能不可行。默认运行时，它与其他经典候选一同交给 `report.conclusions` 统一比较；显式限制为仅 `MAGE-Stern` 时，只评估该算法。

相对原 Stern 的收益可能同时包含生成矩阵方向和多层复用的影响，不能全部归因于分支树；`search.one_level_baseline_time_log2` 记录相同生成矩阵计价下的单层搜索基线，便于另算多层复用的效果。

公式重放见 [mage_costs.py](../codebased_estimator/mage_costs.py)，树搜索见 [mage_search.py](../codebased_estimator/mage_search.py)，目标批量优化见 [mage_targets.py](../codebased_estimator/mage_targets.py)。`metadata.cost_breakdown` 保留成本、成功率分解及整树独立和完整执行假设，`metadata.search` 保留搜索范围、停止原因及单层基线。重放时从结果参数中移除 `strategy`，保留输入、`targets_used`、内存界与完整分块／重复数，交给固定点评估器；单层和多层点使用同一接口。结果仍是当前参数搜索和计价模型下的估计，不是全局最优攻击或方案安全下界。

## 量子成本

QSS/QMMT+ 对随机满行秩二元矩阵估计单目标时间，分别优化直接、完整列表和量子游走分支。令 $m=n-k$、$K=k+\ell$、$r=m-\ell$；本节 $r$ 为消元尾部长度，$d$ 为 QMMT+ 表示中的额外重量，与后文方案参数含义不同。

| 算法 | 叶列表大小 $V$ | 重量命中概率 $P$ | 表示数 $R$ |
|---|---|---|---|
| QSS | $\binom{K/4}{p/4}$ | $V^4\binom r{w-p}/\binom nw$ | $1$ |
| QMMT+ | $\binom{K/2}{p/4+d/2}$ | $\binom{K/2}{p/2}^2\binom r{w-p}/\binom nw$ | $\left[\binom{p/2}{p/4}\binom{(K-p)/2}{d/2}\right]^2$ |

第一层合并 $(00,01)$ 与 $(10,11)$。设过滤位数 $f=a+b$，$a$ 位由内层 Grover 搜索，$b$ 位在外层固定。表示存活与尾部满列秩概率分别为

$$
\sigma=\frac{R}{R+2^b-1},\qquad
\rho_\ell=\frac{\prod_{i=0}^{r-1}(1-2^{i-m})\prod_{i=0}^{\ell-1}(1-2^{i-K})}
{\prod_{i=0}^{m-1}(1-2^{i-n})}.
$$

每综合征有 $L=2^s$ 个可接受解时，$s$ 取 `log2_solutions`，使用 `independent-solution-union-v1`：

$$
P_{\rm eff}=\rho_\ell[1-(1-P\sigma)^L].
$$

所有解共享的秩条件留在并集概率之外；单解时为 $P\rho_\ell\sigma$。$\sigma$ 是随机投影上的二阶矩代理，多解并集另作独立命中假设；不再把表示数或解数计入内层加速。

四张子列表各取 $u$ 个叶子，游走使用 $\varepsilon=(u/V)^4$、$\delta=V/[8u(V-u)]$：

$$
\mathcal Q=S_{\rm list}+\varepsilon^{-1/2}(\delta^{-1/2}U+C),\qquad
T=T_0+\frac{n}{\sqrt{P_{\rm eff}}}\bigl(G+2^{a/2}\mathcal Q\bigr).
$$

列表建立、平均更新、检查和矩阵预算按归一化向量操作定价，乘 $n$ 转为位操作；$T_0$ 为一次性位操作。完整列表 $u=V$ 使用 $\mathcal Q=S_{\rm list}+C$；直接分支单独计价。QCCF 设置 $L=M$ 并排除 $p=0$ 直接分支，其余仍为通用 SD 代理，未完整处理零综合征下的自身碰撞。

| 矩阵配置 | 成本版本 | 处理 |
|---|---|---|
| `partial-ge-aggregate-v1`（默认） | `ka17-ce-ordered-average-v2` | 部分普通消元 |
| `partial-m4ri-aggregate-v1` | `ka17-ce-ordered-partial-m4ri-v3` | 部分 M4RI，优化块宽并保留普通消元候选 |

两种配置均假设相干主元选择、查表、更新和逆算；不估计量子内存。M4RI 块宽子问题完整优化，不意味着攻击参数全局最优。小实例 $n\le16$ 枚举模型参数域，大实例使用多起点和有预算的整数细化；停止信息保存在 `search` 元数据中。

有限列表价格、整数约束和直接分支见 [quantum_costs.py](../codebased_estimator/quantum_costs.py)、[list_costs.py](../codebased_estimator/list_costs.py)、[matrix_costs.py](../codebased_estimator/matrix_costs.py)；搜索见 [quantum_search.py](../codebased_estimator/quantum_search.py)。`evaluate_parameters` 重放时须保留 `log2_solutions`、`matrix_profile`，QCCF 另设 `codeword_finding=True`。算法依据为 [Kachigar–Tillich 2017 v2 §4–5](https://arxiv.org/abs/1703.00263v2) 和 [MNRS 游走](https://arxiv.org/abs/quant-ph/0608026)，本项目有限预算仍是启发式定价。

## 内置 Hamming 方案的 DOOM 映射

[hamming.py](../codebased_estimator/hamming.py) 将 42 组参数展开为 119 条候选路线，按方案、参数集和恢复目标分组。下表的 $r$ 为基础循环块长，Mito 的 $d=2^\ell$ 为环坐标数。

| 方案 | 密钥机制 | 消息机制 | `doom="auto"` 的目标数 |
|---|---|---|---|
| BIKE_MLThre、TRIKE | QCCF 非零码字代理 | QCSD | $r$ |
| HARE、NSS-HQC、TriQ-KEM、QUBE | QCSD | `u_only` 与 `composite` QCSD | $r$ |
| Mito | `baseline` 与 `parity` QDSD 代理 | `u_only` QDSD／`composite` QCSD | key／`u_only`：$dr$；`composite`：$r$ |
| QCTM | 未实现 | QCSD | 自同构阶 $\ell=19$ |
| UVW-KEM | 未实现 | 普通多元 SD | $1$ |

QCSD 指定每综合征一个可接受解；BIKE/TRIKE 的 QCCF 由目标数提供码字数。除 BIKE 密钥的可逆块保证移位互异外，完整轨道均作为可用性假设，未检查具体公钥的重复综合征或稳定子。NSS-HQC 的轨道由公开方程推导，不声称 Spec 已使用该折扣。QCTM 的变换须保留非循环尾部校验行。

`doom="none"` 将可用路线改为 `sd`、单目标、单解，不删除 `composite` 或 `parity`；BIKE/TRIKE 密钥此时也是普通 SD 代理。通用 Hamming 路线将块重量合并为总重量，不另计 Unbalanced、CombGap／collapse、不交支撑和密钥／消息后处理费用。量子 QCSD 始终按前述规则回退。

逐实例 `references` 保留本地 Spec 路径及页码，参数快照可脱离 `local/` 目录运行。原文攻击表与本项目计算使用不同口径时，不混作同一结果；详细原文审计保留在 `local/path_audit/`。

### Composite message routes：复合消息路线

比较统一忽略截断、压缩残差和未知消息成本，将 $v-\operatorname{Encode}(m)$ 视为免费可得，不增加消息码维度或猜测成本。这是完整核心的比较约定，不是从真实未知消息密文到该综合征的归约。以下 $(N,K,W)$ 为 SD 长度、码维数与总重量，均使用 $q=2$。

| 方案 | `u_only` 的 $(N,K,W)$ | `composite` 的 $(N,K,W)$ |
|---|---|---|
| HARE、TriQ-KEM | $(2r,r,2w_r)$ | $(3r,r,2w_r+w_e)$ |
| NSS-HQC | $(2r,r,w_{r1}+w_{r2})$ | $(3r,r,w_{r1}+w_{r2}+w_e)$ |
| Mito，$W_u=\sum_i(w_r[i]+w_t[i])$ | $(2dr,dr,W_u)$ | $((2d+1)r,dr,W_u+w_e)$ |
| QUBE | $(3r,2r,2w_f+w_g)$ | $(4r,2r,2w_f+w_g+w_e)$ |

HARE/NSS-HQC/TriQ-KEM 使用 $u=a+hb$、$v-\operatorname{Encode}(m)=sb+e$；QUBE 使用 $u=g+h_1f_1+h_2f_2$、$v-\operatorname{Encode}(m)=s_1f_1+s_2f_2+e$。各自的两个单位块给出 $2r$ 个独立校验行。

Mito 保留取第零环分量的 `Pr`，仅忽略其后的截断：$u=a+A_ht$，$v-\operatorname{Encode}(m)=B_st+e$，其中 $a,t$ 各长 $dr$、$e$ 长 $r$、$B_s=[\operatorname{Cir}(s_0)\cdots\operatorname{Cir}(s_{d-1})]$。联合矩阵为

$$
H=\begin{pmatrix}I_{dr}&A_h&0\\0&B_s&I_r\end{pmatrix},\qquad
\operatorname{rank}(H)=(d+1)r.
$$

全部复合核心保留同时循环移位，故采用 $r$ 个目标。Mito 的 dyadic 置换会涉及未发布的其他分量，不能沿用 $dr$ 个目标。真实截断、消息消元或压缩后的轨道须另行证明。消息路线未加入 parity 专用收益。

### Mito P：包含 parity 条件的密钥恢复代理

真实秘密分别采自 $S^D(w_x)$、$S^D(w_y)$：逐块精确重量、同一元组内部支撑不交，两个元组独立。不能按 Spec 定义 4.1.10 的误写将其换为均匀 parity 切片。令 $E=I_d\otimes\mathbf1_r^{\mathsf T}$、$p_x=w_x\bmod2$、$p_y=w_y\bmod2$，则 $EA_h=B_hE$，其中 $B_h[i,j]=E(h)_{i\mathbin{\mathrm{xor}}j}$；给定公开 $h$，P 的随机对照综合征均匀分布于 $E(s)=p_x+B_hp_y$ 的切片。

$$
H_P\binom{x}{y}=\binom{s}{p_y},\qquad
H_P=\begin{pmatrix}I_{dr}&A_h\\0&E\end{pmatrix},\qquad
\operatorname{rank}(H_P)=dr+d.
$$

$Ex=p_x$ 由上式推出，不再增加独立行。因此 $W=\sum_i(w_x[i]+w_y[i])$ 不变，`baseline` 为 $(2dr,dr,W)$，`parity` 为 $(2dr,dr-d,W)$，保留全部原坐标。增秩是精确结论，但新增行具有结构；成本将其替代为同秩随机 SD，未实现专用 P 搜索或精确条件成功率。固定总重量还可能已蕴含一个 parity 组合，故不按 $d$ 位额外扣成本。

DOOM 对完整综合征同步作用：$(s,p_y)\mapsto(P_gs,D_gp_y)$，其中 $P_g$ 为循环／dyadic 坐标置换，$D_g$ 为对应的块标签置换；有 $H_P\operatorname{diag}(P_g,P_g)=\operatorname{diag}(P_g,D_g)H_P$。完整 $dr$ 轨道仍是假设，逆变换恢复原候选。

精确描述由 [MitoKeyParity](../codebased_estimator/mito_parity.py) 生成，JSON 的 `instance.cost_proxy` 保存矩阵、parity、来源及代理维数；`source_targets` 是适配器原始值，实际请求见 `instance.targets`。Spec 的采样与证明范围问题详见本地 `local/path_audit/Mito.md`；本项目未由修正定义推出搜索／决策等价、ISD 最优性或折叠攻击。

## 结果比较与重放

[compare_routes](../codebased_estimator/comparison.py) 按 `(scheme, parameter_set, goal)` 分组，要求组内选项相同、实例名称唯一。经典与量子各自从可行、已计算且时间单位一致的候选中选最小时间，精确并列全部保留；单位不兼容时不选胜者。量子仅估计时间，不能据此判断其内存可行性。比较不覆盖未请求算法，也不保证启发式搜索全局最优。

`Report.to_dict()` 保存单路线报告；`hamming --json` 对多路线组附加 `route_comparison`。CSV 为逐算法摘要：`route_id` 标识路线，`is_best`／`is_best_route` 标记路线内／跨路线最优，`effective_doom`／`effective_targets` 区分实际计算与输入上下文，`cost_proxy` 只保存代理名称。重放输入使用 JSON 的 `instance`，并沿用 `options`；成本元数据保留版本、参数及搜索停止信息。
