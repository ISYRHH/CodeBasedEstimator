# CodeBasedEstimator

面向 NGCC 编码方案 key recovery / msg recovery 研究的 Python 程序，基于
[CryptographicEstimators](https://github.com/Crypto-TII/CryptographicEstimators) 2.1.1。
已按 `local/notes/HammingISD.md` 接入 `local/HammingSchemes` 的 9 个方案，
初步计算**不考虑 DOOM、Unbalanced 等优化的普通 ISD 成本**。结果保留具体路线和简化假设。

## 运行

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m codebased_estimator hamming
.venv/bin/python -m codebased_estimator demo
.venv/bin/python -m codebased_estimator estimate examples/instance.json --classical-algorithms Prange Stern --quantum-algorithms QPrange QSS 'QMMT+' --json
.venv/bin/python -m codebased_estimator estimate examples/instance.json --classical-algorithms Stern --quantum-algorithms QSS --doom qcsd --targets 32
.venv/bin/python -m pytest -q
```

也可在已安装 CryptographicEstimators 的环境中，从本仓库直接运行，无需安装本项目。
本机已有的环境可用：

```sh
../CryptographicEstimators/.venv/bin/python -m codebased_estimator demo
../CryptographicEstimators/.venv/bin/python -m pytest -q
```

若要开发本地基石库，在自己的虚拟环境中用 `python -m pip install -e ../CryptographicEstimators`
替换 PyPI 依赖即可。本 demo 不复制或改写基石库；测试所用本地版本为
`2.1.1 / 071cce7a942af423422cb0c6d6af55778c72e4d1`。
对于 2.1.1 的二元 Prange/Stern，适配器用高斯消元成本下界 `G(r) >= 2^r`
提前终止不可能改善结果的 `r` 枚举，避免大码长下无谓计算巨大整数。
这保留上游成本公式、比较和内存判定，以及 Stern 其余参数的自适应搜索；
JSON 的 `gaussian_elimination_search` 记录该等价加速。其他版本沿用上游搜索。

## HammingSchemes 初步评估

```sh
# 查看参数集和原始参数；不运行估算器
.venv/bin/python -m codebased_estimator hamming --list

# 默认评估全部参数集的 key/msg，包含全部上游经典算法和全部量子占位
.venv/bin/python -m codebased_estimator hamming
.venv/bin/python -m codebased_estimator hamming --progress --json > hamming-baseline.json
.venv/bin/python -m codebased_estimator hamming --csv > hamming-baseline.csv

# 选择方案、参数集、目标，查看每个算法的成本和来源说明
.venv/bin/python -m codebased_estimator hamming --schemes BIKE_MLThre --parameter-sets BIKE_MLThre-128 --goal key_recovery --details
.venv/bin/python -m codebased_estimator hamming --schemes UVW-KEM --goal msg_recovery --classical-algorithms Prange Stern LeeBrickell

# 如需快速检查，可显式只选 Prange/Stern，并关闭量子占位
.venv/bin/python -m codebased_estimator hamming --parameter-sets BIKE_MLThre-128 --classical-algorithms Prange Stern --quantum-algorithms
```

`hamming`、`estimate` 和 Python `Options()` 默认选择各后端的全部经典候选及全部量子候选。
当前二元经典候选为 **BallCollision、BJMMdw、BJMMpdw、BJMM、BJMMplus、BothMay、Dumer、
MayOzerov、Prange、Stern**；Fq 候选为 **Prange、Stern、LeeBrickell**。
名单从上游后端读取；BJMM 和 MayOzerov 已在内部比较深度 2/3，沿用上游规则不重复列出其固定深度实现。
量子候选统一登记为 **QPrange、QSS、QMMT+**，有限成本待实现，逐项返回
`not_implemented`；不适用的域/问题返回 `not_applicable`。`--all-classical` 保留为兼容选项，现与默认行为相同。

默认文本逐算法展示结果，并分别给出经典、量子的最小时间结论；`--json` 保留完整记录。
CSV 也逐算法输出，用 `model` 区分类别，`is_best` 标记该类别中最优的可行结果；
`time_log2` / `memory_log2` 的单位分别由 `time_unit` / `memory_unit` 给出，待实现成本留空。
显式关闭量子后，默认文本改用简洁的经典最优值表，`--details` 可展开。
完整搜索可能耗时较长，`--progress` 在 stderr 显示当前路线，不影响 JSON/CSV 输出。
`--memory-bound` 仍以 log₂(bits) 为单位。显式算法名必须适用于所选方案的后端；
例如 `LeeBrickell` 用于 Fq，不能同时选二元方案。
此前生成的 `local/hamming-baseline.json` / `.csv` 是显式 Prange/Stern 子集的初步快照，未按新默认重算。

参数目录是从本地实现/规范核对后保存的快照，位于
[`hamming_parameters.py`](codebased_estimator/hamming_parameters.py)，包含源文件路径、行号或 PDF 页码。
因此安装后的程序不依赖未跟踪的 `local/` 目录，也不会随其中头文件变化自动更新。
42 个参数集的范围如下：

| 方案 | 参数集后缀 | key → `(n,k,w)` | msg → `(n,k,w)` |
|---|---|---|---|
| BIKE_MLThre | 128 / 192 / 256 / 512 | `(2r,r,w)` | `(2r,r,t)` |
| TRIKE | 1 / 2 / 3 / 5 / 7 / 9 | `(3r,2r,w)` | `(3r,r,t)` |
| HARE | 128 / 256 / 384 / 512 | `(2r,r,2w)` | `(2r,r,2wr)` |
| NSS-HQC | 128 / 256 / 384 / 512 | `(2r,r,2wsk)` | `(2r,r,wr1+wr2)` |
| TriQ-KEM | 128 / 256 / 384 / 512 | `(2r,r,wx+wy)` | `(2r,r,2wr)` |
| Mito | 1 / 1-E / 2-E，各 128 / 256 / 512 | `(2dr,dr,Σwx+Σwy)` | `(2dr,dr,Σwr+Σwt)` |
| QUBE | 128 / 192 / 256 / 384 / 512 | `(3r,r,2wx+wy)` | `(3r,2r,2wf+wg)` |
| QCTM | 128 / 256 / 512 | 未提供归约 | `(n,n-m(t-1)-1,(t-1)/2)` |
| UVW-KEM | 128 / 256 / 512 | 需按重量分析结构码字区分攻击 | `(n,k1+k2,w)`，`q=433/857/1709` |

BIKE 的 `w=2*DV`，TRIKE 的 `w=3*PARAM_D`；Mito 的 `d=PARAM_L`，两个向量分别求和，
Mito-2-E 中两个向量复用同一组四个重量。QCTM 的 `t` 是 Goppa degree，
而非实现中的 `ERROR_WEIGHT`。QCTM 参数集 ID 为 `QCTM128` 等，其余 ID 见 `--list`。

目录包含显式注明的 BIKE-192 legacy、BIKE-512 candidate，以及 TRIKE-1/3 仅规范参数。
TRIKE-2 使用规范 Table 1 和参考实现一致的 `r=15581`，保留 DFR Table 8 写作 `15541` 的冲突说明。
QUBE 使用五个规范对齐的参考参数集，不包含默认构建已排除的旧 optimized-only 变体。

所有可计算路线固定 `targets=1`、`log2_solutions=0`，不使用 QC 轨道、多目标、多解折扣，
也不利用分块重量和其他结构。key 路线按笔记的元组借用普通 SD 成本近似寻找指定非零秘密；
独立 CFP 模型、恢复后处理及验证成功率尚未实现。QCTM / UVW 的 key 路线保留
`not_implemented` 记录和 `unavailable` 结论。以上数值应作为所列简化路线的初步比较，
不能直接作为整个方案的安全位数。

```python
from codebased_estimator import HammingScheme, Options, estimate, hamming_instances

adapter = HammingScheme("BIKE_MLThre")
instance, = adapter.instances("BIKE_MLThre-128", "key_recovery")
report = estimate(instance)  # 默认：全部经典候选和全部量子占位
print(report.to_dict())

# 只生成实例，便于检查映射或传给其他攻击模型
instances = hamming_instances(schemes=("QCTM", "UVW-KEM"), goal="msg_recovery")
```

## 当前范围与口径

| 输入 / 模型 | 当前行为 |
|---|---|
| `sd`，`q=2` | 调用 `SDEstimator` |
| `sd`，`q>2`，q 为素数幂 | 调用 `SDFqEstimator`，显式设置非零综合征 |
| `rank_sd`，`q,m,n,k,r` | 调用 `RankSDEstimator`，包含组合与代数攻击 |
| `QPrange`、`QSS`、`QMMT+` | 独立量子算法名称，逐算法返回待实现状态 |
| `doom:qccf` / `doom:qcsd` | 实例标签，传入每个算法的计算/优化入口；目前未实现相应成本 |
| CFP、RSL、结构恢复、其他标签或分块约束 | 明确返回未支持，不自动降为普通 SD/RSD |

一个实例只生成一份报告，经典、量子结果按 `model` 和 `algorithm` 区分。
所有时间与内存都是 **log₂**：经典时间沿用上游有限参数 `bit_complexities=1` 的位操作口径，
内存是 **bits，不是 bytes**；`--memory-bound 30` 表示最多 `2^30` bits。
固定使用 `complexity_type=0`、常数成本内存访问；Rank 默认线性代数指数为 3、`theta=2`。
优化使用上游搜索范围和启发式，不声称证明全局最优。`infeasible` 表示没有有限估计或内存超限；
若保留了超限数值，仅供诊断，不属于可行攻击结果。

`log2_solutions=0` 表示同一综合征有一个可接受解；省略/null 沿用上游期望解数。
`targets` 默认 1，含义由标签指定：`doom:qccf` 是同一零综合征下可利用的非零码字候选数，
`doom:qcsd` 是同一矩阵下可利用的综合征目标数；不假设目标独立或轨道一定达到环长。
QCCF 标签要求 `cfp` / `qccf` 问题，并省略 `log2_solutions`，避免重复计数；
QCSD 标签要求 `sd` / `qcsd` 问题。两个标签互斥，不允许把 targets 无条件换成解数。
Rank 后端不支持解数设置。
普通 SD 输入暂遵循上游 `1 <= w <= n-k` 的定义域。

`demo` 使用小型**合成参数**展示 Hamming、q-ary、Rank 的 key/msg 两种目标；
`hamming` 使用上面的真实参数快照及初步归约。两种目标的标签不会替代数学归约；
完整恢复分析仍须说明候选是否为所需秘密、后续译码/验证成本及成功率。
JSON 保留原始实例、标签、假设、有效解数、内部参数和各后端来源（`backends`），便于复现；
文本表在逐算法结果后输出经典、量子各自的最优结论；JSON 对应 `conclusions.classical` / `conclusions.quantum`。
结论仅比较本次评估中已计算、成本有限且满足内存约束的结果，按时间最小选取，保留并列项及其内存、参数和单位。
同类时间单位不同则返回 `incomparable_units`；指定 bits 内存上限时，其他内存单位需先由后端换算。
无可用结果为 `unavailable`，未选择该类算法为 `not_requested`，两种情况的 `best` 都为空。
这表示给定路线、所选算法与搜索范围内的最优估计，不是全局最优证明或整个方案的安全结论。

## Python 与扩展接口

```python
from codebased_estimator import AttackInstance, Options, Problem, estimate

instance = AttackInstance(
    name="my-decoding-experiment", goal="msg_recovery",
    problem=Problem("sd", {"n": 100, "k": 50, "w": 10, "q": 2}, log2_solutions=0),
    route="generic decoding baseline; recovery reduction to be supplied",
)
options = Options(
    classical_algorithms=("Prange", "Stern"),
    quantum_algorithms=("QPrange", "QSS", "QMMT+"),
)
report = estimate(instance, options=options)
print(report.to_dict())
for family, conclusion in report.conclusions.items():
    for best in conclusion.best:
        print(family, best.algorithm, best.time_log2, best.time_unit)
```

添加 DOOM 时修改实例标签和目标数，仍然使用同一次估计：

```python
from dataclasses import replace

doom_instance = replace(instance, tags=("doom:qcsd",), targets=32)
doom_report = estimate(doom_instance, options=options)
```

这里 32 是合成示例值；真实目标数需由方案归约给出。`doom_report` 中每个选中的算法
各返回一行，当前为待实现。后续 QCCF 模型可在计算成功概率时考虑更多码字候选，
QCSD 模型需将目标批量、列表构造、匹配等纳入算法流程与参数搜索；不在输出端统一扣 bits。

- `classical_algorithms=None` 使用上游全部默认算法，`()` 禁用经典；
  `quantum_algorithms` 默认包含全部登记候选 `("QPrange", "QSS", "QMMT+")`，`()` 禁用量子。
  可显式传入子集；两类均禁用会报错。
  CLI 对应 `--classical-algorithms` / `--quantum-algorithms`；旗标后不列名称即禁用该类。
  `demo` 为快速合成演示，使用显式的小规模算法选择，其 Hamming 实例同时展示全部量子占位。
- 方案侧：实现 `SchemeAdapter.instances(parameter_set, goal)`，返回一个或多个
  `AttackInstance`。合成示例见 `codebased_estimator/schemes.py`；本地 Hamming 方案适配见
  `codebased_estimator/hamming.py`。
- 攻击侧：实现 `AttackModel.name` 和 `estimate(instance, options) -> list[Estimate]`，
  分别通过 `estimate(..., classical_model=...)` / `estimate(..., quantum_model=...)` 接入。
  后端读取自身算法列表，逐算法检查标签、优化参数并记录单位与假设；入口不修改实例或折扣结果。
  `Estimate.model` 填所属的 `classical` / `quantum`，用于分别汇总最优结果；自定义后端名称放在 `AttackModel.name`。
  内置实现位于 `backend.py`、`quantum.py`。旧的 `Options.algorithms` 和 `model="doom"` 接口已移除。
- CLI 单实例输入见 `examples/instance.json`。不认识的字段或算法名称会报错，避免拼写错误被忽略。

## 后续开发顺序

1. **量子有限成本**：先 qPrange（初始化、可逆单轮、重复/幅度放大、输出），再 SS/QMMT+；
   独立优化量子参数，与经典结果分别验证。不要整体减半经典时间指数。
2. **DOOM 与结构约束**：分别建模同矩阵多综合征、QC 轨道、多解、分块重量和内存成本；
   逐算法优化目标批量与内部参数。不要通用扣除 `log₂(targets)/2`。
3. **完善方案归约**：在已接入的 Hamming 普通 SD/Fq 基线上继续核验实际恢复条件；
   CFP、RSL、理想/分块结构与后续恢复成本另建模型，并补充 Rank 方案参数集。
