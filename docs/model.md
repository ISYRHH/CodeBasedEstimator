# 成本模型

本项目分别调用经典后端和量子模型，报告所选算法及译码路线的成本，不将其直接视为整个密码方案的安全位数。

## 经典后端与适用范围

经典二元 SD、多元 SD、Rank SD 分别委托 CryptographicEstimators 2.1.1 的 `SDEstimator`、`SDFqEstimator`、`RankSDEstimator`。采用有限复杂度、位复杂度和常数内存访问模型；时间单位为位操作，内存单位为 bits，均输出 $\log_2$ 值。普通单目标路线保留 CE 成本和参数搜索；Rank SD 不接受显式解数。经典 QCSD 使用以下 DOOM 扩展。

## 经典 QCSD 的 DOOM 模型

接口为二元 `Problem(kind="sd", ...)`、`tags=("doom:qcsd",)` 和正整数 `targets=M`。$M$ 表示同一矩阵下可用的 syndrome 数量，由调用方提供；模型不从 QC 轨道自动推导数量或独立性。`log2_solutions` 仍表示**每个 syndrome** 的解数对数，省略时保留 CE 默认值，不能再加 $\log_2M$。`qcsd` 问题类型仍留给自定义模型；额外标签、结构约束、非二元 DOOM 和 QCCF 不受支持。内置 `hamming` 路线仍采用原有单目标 SD 近似，不自动启用 DOOM。

Prange、Stern、Dumer、BJMM 使用 `ce-doom-finite-v1` 调参模型。设 $m=n-k$、$S$ 为每个 syndrome 的解数、$P_0$ 为一个解满足重量分布的概率，选择实际使用的目标数 $1\le u\le M$。一次迭代的成功率代理、位操作成本及内存为

$$
P_{\rm succ}=\min(1,uSP_0),\qquad
W=n(G+W_{\rm shared}+uW_{\rm target})+(u-1)m^2,
$$
$$
B=n(B_{\rm matrix}+B_{\rm shared}+uB_{\rm target})+(u-1)m,
\qquad T=W/P_{\rm succ}.
$$

$G,B_{\rm matrix}$ 采用 CE 的高斯消元与矩阵存储预算，列表项按 CE 的向量口径乘 $n$ 转为位操作或 bits。第一份 syndrome 已包含在 CE 基线中；额外 $u-1$ 份各计 $m^2$ 位操作的稠密线性变换及 $m$ bits 存储。列表显式存储，$B$ 受经典内存上限约束。固定列表参数时，$W,B$ 随 $u$ 仿射增长；搜索检查内存允许的端点及成功率饱和点相邻的整数，避免盲目使用全部目标。

Prange 使用 $P_0=\binom mw/\binom nw$，没有列表项，优化目标批量与 CE 消元块宽。Stern 和 Dumer 分别取 $K=k$ 和 $K=k+\ell$，令 $h_0=\lfloor K/2\rfloor$、$h_1=K-h_0$，允许两个半区采用不同重量 $p_L,p_R$：

$$
A=\binom{h_0}{p_L},\quad D=\binom{h_1}{p_R},\quad
P_0=\frac{AD\binom{m-\ell}{w-p_L-p_R}}{\binom nw},
$$
$$
W_{\rm shared}=B_{\rm shared}=A,\qquad
W_{\rm target}=D+AD/2^\ell,\qquad B_{\rm target}=D.
$$

列表匹配计期望碰撞数，优化 $\ell,p_L,p_R$，因此 DOOM 收益取决于重新选择的列表大小、重量和匹配位数。该构造依据 [Sendrier, *Decoding One Out of Many*, §5、式 (8)](https://eprint.iacr.org/2011/367)；这里的有限多项式价格是本项目的建模选择。

BJMM 的显式 DOOM 分支采用两层结构，仅第四张底层列表附带目标。设 $K=k+\ell$，两个半区长度为 $h_0,h_1$；输出半区重量为 $p,p-z$，四张底层列表重量为 $p_1,p_1,p_1,p_1-z$，其中 $z$ 对应 `weight_deficit`，$p$ 为偶数。有限半区表示数与匹配位数为

$$
R=\binom p{p/2}\binom{h_0-p}{p_1-p/2}
  \binom{p-z}{p/2}\binom{h_1-p+z}{p_1-p/2},\qquad
\ell_1=\min(\ell,\lfloor\log_2R\rfloor).
$$

令 $A=\binom{h_0}{p_1}$、$C=\binom{h_1}{p_1}$、$D=\binom{h_1}{p_1-z}$。中间列表及顶层输出采用均值 $X=AC/2^{\ell_1}$、$Y=AD/2^{\ell_1}$、$Z=XY/2^{\ell-\ell_1}$，不将小于 1 的均值向上取整。哈希合并使用 $a+b+ab/2^j$ 的向量成本，得到

$$
W_{\rm shared}=2A+C+2X,\quad W_{\rm target}=D+2Y+Z,\qquad
B_{\rm shared}=A+C+X,\quad B_{\rm target}=D+Y,
$$
$$
P_0=\frac{\binom{h_0}p\binom{h_1}{p-z}\binom{m-\ell}{w-2p+z}}{\binom nw}.
$$

优化 $\ell,p,p_1,z$，目标扩展由 $uD,uY$ 体现。构造依据 [Esser–May–Zweydinger, *McEliece needs a Break*, §2、§5.1](https://eprint.iacr.org/2021/1634)，有限半区计数延续 CE BJMMd2 的划分方式。$\ell_1$ 只保证期望表示数至少为 1，不保证每个目标都存在存活表示；模型保留随机标签和表示法的启发式假设，也不计目标间相关性。显式存储预算可能高于论文的流式实现。

四个算法在 $M=1$ 时完全返回原有 CE 时间、内存和参数。$M>1$ 时继续保留该单目标候选；BJMM 的 CE 两层／三层基线也参与比较，因此选择忽略额外目标不会产生更差成本。小实例在预算内枚举，较大实例使用确定性网格和整数局部细化；结果中的 `metadata.doom.search` 记录搜索范围、预算与停止信息，不宣称一般实例的全局最优。`active_targets` 记录最终使用的目标数，`strategy` 区分显式 DOOM 和单目标基线。

BothMay、MayOzerov 以及其余二元经典算法使用 `sqrt_targets_approximation`：

$$
\log_2T_{\rm DOOM}=\max(0,\log_2T_{\rm CE}-\tfrac12\log_2M).
$$

此近似不重新调参，也不改变内存或不可行状态；`log2_speedup` 记录名义加速，`realized_log2_speedup` 记录截断后的实际差值。它不建模目标相关性、额外变换或算法专用的多目标列表费用。

实现及参数点重放见 [DOOM 成本与搜索](../codebased_estimator/classical_doom.py) 的 `evaluate_parameters`，BJMM 有限计数见 [BJMM DOOM](../codebased_estimator/doom_bjmm.py)。这些均为随机实例下的成本近似，不是安全下界或实测运行时间。

## 量子适用范围

量子实现 QSS 和 QMMT+，面向随机满行秩矩阵下的普通二元、单目标、单解 SD：$He^{\mathsf T}=s$、$\operatorname{wt}(e)=w$，整数输入满足 $0<k<n$、$1\le w\le n-k$。非二元、Rank SD、多目标、多解、DOOM 和结构专用量子模型不在此范围。

`log2_solutions=0` 指定单解；省略或 `null` 时，量子仍按单解处理，经典使用上游默认解数。比较同一单解问题时应显式指定 `0`。内置 Hamming 路线采用普通 SD 近似，不计结构或 DOOM 加速。

量子仅估计时间，不估计内存，也不使用经典内存上限筛选参数。一次长度至多为 $n$ 的向量操作归一计为 1，重复预算乘 $n$ 转为位操作；输出 `time_log2` 的单位为 `quantum_bit_operations`。模型假设抽象相干访问，固定成功率放大及正反算的常数因子统一归一化，不能据此推断实际门数或设备运行时间。

## 组合计数与表示

令 $m=n-k$、$K=k+\ell$、$r=m-\ell$。部分消元处理尾部 $r$ 列；列表搜索处理剩余 $K$ 个坐标，其中目标重量为 $p$，尾部重量为 $w-p$。$q,t$ 是单叶支撑区长度与重量，$V$ 是完整叶列表大小，$P$ 是指定重量分布的概率，$R$ 是每个目标的有序表示数。

QSS 将 $K$ 个坐标分成四个等长区，各含 $p/4$ 个目标 1：

$$
q=K/4,\quad t=p/4,\quad V=\binom qt,\quad
P=\frac{V^4\binom r{w-p}}{\binom nw},\quad R=1.
$$

QMMT+ 将坐标分成两个半区，各含 $p/2$ 个目标 1；两个大分量在每半区额外共有 $d/2$ 个 1，经 XOR 抵消：

$$
q=K/2,\quad t=p/4+d/2,\quad V=\binom qt,\quad
P=\frac{\binom q{p/2}^{2}\binom r{w-p}}{\binom nw},\quad
R=\left[\binom{p/2}{p/4}\binom{q-p/2}{d/2}\right]^2.
$$

叶列表 $V_{00},V_{10}$ 支撑前半区，$V_{01},V_{11}$ 支撑后半区；第一层合并 $(00,01)$ 和 $(10,11)$，得到大分量 $x,y$，满足 $x+y=e'$。$d=0$ 是普通 QMMT，仍不同于 QSS。上述定义采用有限组合数；大组合数的对数可用 `lgamma` 求值，不采用熵近似。

## 过滤与成功比例

设 $f=a+b$。第一层分别匹配 $f$ 位过滤值及其与目标综合的 XOR，第二层匹配剩余 $\ell-f$ 位。$a$ 位过滤值由内层 Grover 搜索；均匀选择的另外 $b$ 位与坐标划分共同构成外层候选，在内层搜索中保持不变。

表示存活采用随机投影与均匀过滤值上的二阶矩代理；它不假设各表示独立。尾部满列秩概率按随机满行秩 $m\times n$ 矩阵集合计算：

$$
\sigma=\frac{R}{R+2^b-1},\qquad
\rho_\ell=\frac{\prod_{i=0}^{r-1}(1-2^{i-m})\prod_{i=0}^{\ell-1}(1-2^{i-K})}
{\prod_{i=0}^{m-1}(1-2^{i-n})},\qquad P_{\rm eff}=P\rho_\ell\sigma.
$$

空乘积为 1；$b=0$ 时 $\sigma=1$。表示收益已计入 $\sigma$ 和过滤划分，不再额外乘 $R$ 加速或 $2^{b/2}$ 费用。将集合平均成功比例代入时间公式属于本模型假设，不给出逐矩阵或随机码平均运行时间上界。

## 列表和量子游走预算

四张游走子列表各含 $u$ 个叶子。定义有序动态索引深度 $L(z)=\lceil\log_2(2+z)\rceil$，以及 CE 的静态有序合并预算：

$$
\mathcal M(v,j)=\begin{cases}1,&v=1,\\
2v\lfloor\log_2v\rfloor+\lfloor v^2/2^j\rfloor,&v\ge2.
\end{cases}
$$

均匀标签下的平均列表大小、更新负载和静态建立代理为

$$
D_1=u^2/2^f,\quad D_2=u^4/2^{\ell+f},\quad
\eta_1=u/2^f,\quad\eta_2=u^2/2^\ell,\quad
J_1=\max\{1,\lfloor D_1\rfloor\},\quad J_2=\lfloor J_1^2/2^{\ell-f}\rfloor.
$$

$J_1,J_2$ 仅用于建立成本，不替换平均负载或成功概率。叶生成、列表建立、一次更新和已缓存的有效候选标记查询，分别计为

$$
g=1+t+q\lceil\log_2(V+1)\rceil/n,\qquad
S=4ug+2\mathcal M(u,f)+\mathcal M(J_1,\ell-f)+J_2L(J_2),
$$
$$
U=g+1+2\left[L(u)+\eta_1(1+L(D_1))+\eta_1\eta_2(1+L(D_2))\right],\qquad C=1.
$$

$g$ 包含定重支撑生成及线性像；删除旧叶复用缓存，更新的倍数 2 计删除和插入。匹配输出的聚合价格包含候选判定与有效计数维护。$J_2=0$ 时顶层索引费用为零。

使用四轴等概率、半概率停留的 Johnson 游走；对至少一个存活见证，取标记比例下界 $\varepsilon=(u/V)^4$、谱隙 $\delta=V/[8u(V-u)]$：

$$
\mathcal Q=S+\varepsilon^{-1/2}(\delta^{-1/2}U+C),\qquad
T^{\rm bit}=T_0+\frac{n}{\sqrt{P_{\rm eff}}}\left[G+2^{a/2}\mathcal Q\right],\qquad
T_0=(q+1)^2(t+1)+n(m+1).
$$

$G,g,S,U,C,\mathcal Q$ 均为向量操作，$T_0$ 已为位操作。$T_0$ 计一次性组合数表及最终恢复验证；$G$ 随外层候选重复，$S$ 还随内层过滤搜索重复。$U$ 是平均负载预算，不是最坏更新费用；这些有限常数是模型价格，论文的渐近结论不证明其精确性。

## 矩阵处理配置

默认 `partial-ge-aggregate-v1` 对应成本版本 `ka17-ce-ordered-average-v2`：

$$
G=G_{\rm prep}+mr,\qquad G_{\rm prep}=mL(n)^2+n.
$$

可选 `partial-m4ri-aggregate-v1` 对应 `ka17-ce-ordered-partial-m4ri-v3`。块宽 $h$ 与过滤位数 $b$ 无关；每块实际宽度为 $h_j=\min(h,r-jh)$：

$$
E_0=mr,\qquad E_h=\sum_{j=0}^{\lceil r/h\rceil-1}(h_j^2+2^{h_j}+m-h_j)\quad(1\le h\le r),
$$
$$
G_{\rm M4RI}=G_{\rm prep}+\min_{0\le h\le r}E_h.
$$

三项聚合计面板处理、表生命周期及非面板行访问更新。准备项仍随外层候选重复；末块按真实宽度计价。$h=0$ 保留普通消元，$r=0$ 时核心费用为零；平局保留更小 $h$。用单调下界 $E_h\ge2^h$ 剪枝后，块宽子问题仍完整求最小值。

该配置假设尾部限定的确定性主元选择、秩失败标记、查表和行更新均相干执行，不测量或丢弃失败分支。更新前查表地址及选择历史保留到逆算；面板表由未改变的主元行局部清理，整个 oracle 再清理其余历史。抽象相干访问和统一正反算归一化是使用前提；聚合价格不是完整量子电路或精确门成本证明，面板表记录数也不是总量子内存。

固定攻击参数时，配置仅改变 $G$。优化时重新搜索攻击参数，并把默认配置的胜者按新配置重放后保留较优结果。`Options.quantum_matrix_profile` 选择配置；定点重放也须保留配置，自动选择的 $h$ 位于矩阵元数据。

## 参数域、边界与搜索

所有搜索参数为整数。四列表分支满足 $0\le\ell\le m$、$0<p<K$、$p\le w$、$0\le w-p\le r$ 和 $4\mid p$；QSS 要求 $4\mid K,d=b=0$，QMMT+ 要求 $2\mid K,2\mid d,0\le d\le K-p$。

过滤条件为 $a,b\ge0$、$f=a+b\le\ell$、$b\le\lfloor\log_2R\rfloor$。非退化游走要求 $V>1$、$1\le u\le\lfloor V/2\rfloor$、$f\ge\lceil\log_2u\rceil$、$\ell\ge\lceil2\log_2u\rceil$；后两项保证平均负载 $\eta_1,\eta_2\le1$。

完整列表 $u=V$ 单独采用 $\mathcal Q=S+C$，保留重量和过滤条件，取消游走及平均负载限制。$p=0$ 或 $p=K$ 时，两个算法均使用固定候选直接分支，不受四列表整除条件限制，固定 $(d,u,a,b)=(0,1,0,0)$：

$$
P_{\rm dir}=\binom r{w-p}/\binom nw,\qquad
T_{\rm dir}^{\rm bit}=n(m+1)+\frac{n}{\sqrt{P_{\rm dir}\rho_\ell}}(G+1+p).
$$

直接分支仍满足 $0\le\ell\le m$、$p\le w$、$0\le w-p\le r$。最终比较直接、完整列表和游走分支。

$n\le16$ 时穷举上述模型参数域；较大实例采用确定性多起点、对数域细化和有预算的整数边界搜索，保留已找到的最好候选。预算耗尽或局部停止不证明搜索收敛、剩余误差或全局最优；M4RI 块宽的完整优化不改变这一限制。

结果元数据记录成本版本、矩阵配置、搜索版本、参数和停止信息。`cost_breakdown` 中成本项通常为向量操作的 $\log_2$，`T0` 为位操作的 $\log_2$，概率和列表大小也在对数域；零输出数或零费用用 `null` 表示。`evaluate_parameters` 可独立重放参数点。

## 实现与来源

生产定义见 [成本求值](../codebased_estimator/quantum_costs.py)、[矩阵预算](../codebased_estimator/matrix_costs.py)、[列表原语](../codebased_estimator/list_costs.py) 和 [参数搜索](../codebased_estimator/quantum_search.py)。

算法与表示结构依据 [Kachigar–Tillich 2017 v2](https://arxiv.org/abs/1703.00263v2) §4–5，QMMT+ 的有限表示计数对应其证明中的式 (16)、(21)；游走结构见 [Magniez–Nayak–Roland–Santha](https://arxiv.org/abs/quant-ph/0608026)。经典后端及静态有序合并口径来自 [CryptographicEstimators](https://github.com/Crypto-TII/CryptographicEstimators)。本项目的有限量子预算和搜索是启发式模型，不是安全下界。
