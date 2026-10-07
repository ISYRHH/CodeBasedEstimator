# CodeBasedEstimator

编码密码译码成本估计工具，基于 [CryptographicEstimators](https://github.com/Crypto-TII/CryptographicEstimators) 2.1.1。
支持经典二元／多元 SD、Rank SD，以及二元 SD 的 QSS、QMMT+ 量子时间估计；内置 9 个 Hamming 方案的参数快照。
结果描述指定攻击路线的成本，不代表整个方案的安全位数。详细假设见 [模型说明](docs/model.md)。

## 安装

需要 Python 3.9 或更高版本：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## 命令行

示例统一使用合成参数 `(n,k,w,q)=(40,20,4,2)`，DOOM 示例均设置 `targets=8`。

| 示例 | `targets` 含义 | 支持的后端 |
|---|---|---|
| [instance.json](examples/instance.json)：普通 SD | 默认单个 syndrome | 经典、量子 |
| [qcsd.json](examples/qcsd.json)：QCSD | 同一矩阵下的不同 syndrome 数 | 经典 |
| [qccf.json](examples/qccf.json)：QCCF | 不同、可接受的非零码字数 | 经典、量子成本代理 |

```sh
.venv/bin/python -m codebased_estimator estimate examples/instance.json \
  --classical-algorithms Stern --quantum-algorithms QSS 'QMMT+' --json
.venv/bin/python -m codebased_estimator estimate examples/qcsd.json \
  --classical-algorithms Stern --quantum-algorithms --json
.venv/bin/python -m codebased_estimator estimate examples/qccf.json \
  --classical-algorithms Stern --quantum-algorithms QSS 'QMMT+' --json
```

QCSD 使用 `kind="sd"` 和 `doom:qcsd` 标签；QCCF 使用 `kind="cfp"`（也接受 `qccf`）和 `doom:qccf` 标签。
示例已包含标签；CLI 可用 `--doom qcsd|qccf` 添加标签、`--targets M` 覆盖数量。

`problem.log2_solutions` 表示每个 syndrome 的可接受解数的 log₂，CLI 可用 `--nsolutions s`（别名 `--log2-solutions`）覆盖，例如 `3` 表示 8 个解。
QCCF 的解数由 `targets` 提供，必须省略此字段。普通 SD 省略时，经典使用 CE 默认解数、量子按单解处理；单解比较应显式设为 `0`。

默认选择全部算法；`--classical-algorithms` 或 `--quantum-algorithms` 后不列名称可关闭对应类别。
量子 M4RI 配置可通过 `--quantum-matrix-profile partial-m4ri-aggregate-v1` 选择。其他选项见各子命令的 `--help`。

查看和估计内置 Hamming 参数：

```sh
.venv/bin/python -m codebased_estimator hamming --list
.venv/bin/python -m codebased_estimator hamming \
  --parameter-sets BIKE_MLThre-128 --goal msg_recovery \
  --classical-algorithms Stern --quantum-algorithms --json
```

`--goal` 可选 `key_recovery`、`msg_recovery` 或 `both`；`--schemes` 可筛选方案，`--csv` 可导出结果。
内置路线采用普通 SD 近似，不自动启用 DOOM。

## Python API

```python
import json
from pathlib import Path
from codebased_estimator import AttackInstance, Options, estimate

instance = AttackInstance.from_dict(json.loads(Path("examples/instance.json").read_text()))
report = estimate(instance, options=Options(
    classical_algorithms=("Stern",),
    quantum_algorithms=("QSS", "QMMT+"),
))
print(report.to_dict())
```

## 结果与限制

- 时间和内存均为 log₂ 值。经典单位为位操作和 bits；量子时间为归一化位操作预算，内存 `null` 表示未估计。`--memory-bound` 仅约束经典算法。
- 经典和量子分别报告最小时间结果；启发式搜索不保证全局最优，量子估计不是设备门数或运行时间。

## 测试

```sh
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```
