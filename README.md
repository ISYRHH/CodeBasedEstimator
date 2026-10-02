# CodeBasedEstimator

面向 NGCC 编码方案 key recovery / msg recovery 研究的最小 Python demo，基于
[CryptographicEstimators](https://github.com/Crypto-TII/CryptographicEstimators) 2.1.1。
目前计算的是**给定攻击路线的通用译码子问题**，尚未接入真实方案归约或给出方案安全位数。

## 运行

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
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
两种目标的标签不会替代数学归约。真实方案还须说明候选是否为所需秘密、后续译码/验证成本及成功率。
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
  `quantum_algorithms` 默认 `()`，按指定名称运行。两类均禁用会报错。
  CLI 对应 `--classical-algorithms` / `--quantum-algorithms`；旗标后不列名称即禁用该类。
  demo 的 Hamming 实例默认同时展示三种量子占位。
- 方案侧：实现 `SchemeAdapter.instances(parameter_set, goal)`，返回一个或多个
  `AttackInstance`。示例见 `codebased_estimator/schemes.py`；真实方案适配留空。
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
3. **方案归约**：按原始方程核验 key/msg 路线，先接普通 SD/q-ary/RSD 基线；
   CFP、RSL、理想/分块结构与后续恢复成本另建模型，再做实际参数集比较。
