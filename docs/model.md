# 成本模型

本项目分别调用经典后端和量子模型，报告所选算法及译码路线的成本，不将其直接视为整个密码方案的安全位数。

## 经典后端与量子适用范围

经典二元 SD、多元 SD、Rank SD 分别委托 CryptographicEstimators 2.1.1 的 `SDEstimator`、`SDFqEstimator`、`RankSDEstimator`。采用有限复杂度、位复杂度和常数内存访问模型；时间单位为位操作，内存单位为 bits，均输出 $\log_2$ 值。经典内存上限交由后端处理。适配器只接受无结构、无标签的单目标路线；Rank SD 不接受显式解数。

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
