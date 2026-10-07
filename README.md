# CodeBasedEstimator

编码密码译码成本估计工具，基于 [CryptographicEstimators](https://github.com/Crypto-TII/CryptographicEstimators) 2.1.1。
支持经典二元／多元 SD、Rank SD，以及二元 SD 的 QSS、QMMT+ 量子时间估计；内置 9 个 Hamming 方案的参数快照。
结果描述给定译码路线的成本，不代表整个方案的安全位数。模型与适用范围见 [模型说明](docs/model.md)。

## 安装

需要 Python 3.9 或更高版本。在仓库目录运行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m codebased_estimator demo
```

安装后也可使用 `.venv/bin/codebased-estimator` 命令。

## 命令行

估计单个实例，输入格式见 [`examples/instance.json`](examples/instance.json)：

```sh
.venv/bin/python -m codebased_estimator estimate examples/instance.json \
  --classical-algorithms Prange Stern --quantum-algorithms QSS 'QMMT+' --json
```

为普通二元 SD 实例指定同一矩阵下的可用 syndrome 数量，启用经典 QCSD/DOOM 模型：

```sh
.venv/bin/python -m codebased_estimator estimate examples/instance.json \
  --doom qcsd --targets 32 \
  --classical-algorithms Prange Stern Dumer BJMM BothMay --quantum-algorithms --json
```

Prange、Stern、Dumer 和 BJMM 重新优化 DOOM 参数及实际使用的目标数；BJMM 的显式 DOOM 分支采用两层结构。
BothMay、MayOzerov 等其他二元经典算法采用时间除以 `sqrt(targets)` 的近似，内存与参数保持不变。
JSON 的 `metadata.doom` 区分调参模型和近似，并记录可用目标数、策略和加速量。
`targets` 与每个 syndrome 的 `log2_solutions` 分别计数；不根据 QC 结构自动推定目标数量。

查看内置参数集，并选择方案、参数集和恢复目标：

```sh
.venv/bin/python -m codebased_estimator hamming --list
.venv/bin/python -m codebased_estimator hamming \
  --parameter-sets BIKE_MLThre-128 --goal msg_recovery \
  --classical-algorithms Prange Stern --quantum-algorithms
```

`--goal` 可选 `key_recovery`、`msg_recovery` 或 `both`；`--schemes` 可进一步筛选方案。
`hamming` 支持 `--json`、`--csv` 和 `--details`；`--progress` 将进度写入 stderr。
更多选项见各子命令的 `--help`。

`estimate` 和 `hamming` 默认选择后端的全部算法，运行可能较慢。
`--classical-algorithms`／`--quantum-algorithms` 后不列名称，即关闭该类算法；两类不能同时关闭。
经典算法名称须适用于所选后端，例如 `LeeBrickell` 仅用于多元 SD。
`QPrange` 已登记，有限成本尚未实现。

QSS/QMMT+ 默认使用部分高斯消元预算。启用可选的部分 M4RI 预算：

```sh
.venv/bin/python -m codebased_estimator estimate examples/instance.json \
  --classical-algorithms --quantum-algorithms QSS 'QMMT+' \
  --quantum-matrix-profile partial-m4ri-aggregate-v1 --json
```

## Python API

```python
import json
from pathlib import Path
from codebased_estimator import AttackInstance, Options, estimate

instance = AttackInstance.from_dict(
    json.loads(Path("examples/instance.json").read_text(encoding="utf-8"))
)
report = estimate(instance, options=Options(
    classical_algorithms=("Prange", "Stern"),
    quantum_algorithms=("QSS", "QMMT+"),
    quantum_matrix_profile="partial-m4ri-aggregate-v1",
))
print(report.to_dict())
```

`Options()` 默认选择全部候选；`classical_algorithms=()` 或 `quantum_algorithms=()` 关闭对应类别。
内置方案可通过 `hamming_instances(parameter_sets=("BIKE_MLThre-128",), goal="msg_recovery")` 生成实例。

## 结果与限制

- 时间和内存均输出 log₂ 值。经典时间单位为位操作、内存单位为 bits；量子时间为归一化位操作预算（`quantum_bit_operations`）。
  `--memory-bound 30` 表示经典内存不超过 `2^30` bits，不约束量子结果。量子内存的 `null` 表示未估计。
- QSS/QMMT+ 适用于普通二元、单目标、单解 SD。显式多解、DOOM、结构专用量子模型尚未实现；
  不支持的请求返回明确状态。省略 `log2_solutions` 时，经典采用上游期望解数，量子按单解处理；
  比较同一单解问题时应显式设为 `0`。
- 经典 DOOM 接口为二元 `Problem(kind="sd", ...)` 加 `doom:qcsd` 标签；`qcsd` 问题类型仍留给自定义模型。
  不支持额外结构约束、非二元 DOOM 或 QCCF。显式模型计入额外 syndrome 的变换与存储费用，
  在成功率饱和和内存上限下选择目标数；单目标时完全保留 CE 结果，多目标时仍将它作为候选。
  列表和成功率采用随机标签下的期望近似；较大参数的搜索不保证全局最优。
- 内置 Hamming 参数随包提供，无需本地规范文件；输出中的源文件路径用于记录快照来源。
  这些路线采用普通 SD 近似，不利用 DOOM 或结构加速；QCTM、UVW-KEM 的密钥恢复路线尚未实现。
- 经典与量子分别报告所选算法中的最小时间结果；启发式搜索不保证一般实例的全局最优。
  JSON 保留参数、假设、成本版本及搜索信息，便于复核；量子估计不等同于实际设备的门数或运行时间。

## 测试

```sh
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```
