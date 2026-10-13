# CodeBasedEstimator

编码密码译码成本估计工具，基于 [CryptographicEstimators](https://github.com/Crypto-TII/CryptographicEstimators) 2.1.1。
支持经典二元／多元 SD、Rank SD，以及二元 SD 的 QSS、QMMT+ 量子时间估计；内置 9 个 Hamming 方案、42 组参数。
结果描述指定路线的成本。模型与限制见[模型说明](docs/model.md)，Mito/QUBE 参数确认见[参数一致性](docs/parameter_consistency.md)。

## 安装

需要 Python 3.9 或更高版本：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## 命令行

估计一个 JSON 实例；另有 [QCSD](examples/qcsd.json) 与 [QCCF](examples/qccf.json) 示例：

```sh
.venv/bin/python -m codebased_estimator estimate examples/instance.json \
  --classical-algorithms Stern --quantum-algorithms QSS 'QMMT+' --json
```

`estimate` 可用 `--doom qcsd|qccf` 添加标签、`--targets M` 覆盖目标数。普通 SD 的 `--log2-solutions s`（别名 `--nsolutions`）表示每个综合征有 `2^s` 个可接受解；单解设为 `0`。QCCF 通过 `targets` 指定非零码字数，必须省略解数字段。

查看内置参数、路线并比较 Mito 密钥恢复：

```sh
.venv/bin/python -m codebased_estimator hamming --list
.venv/bin/python -m codebased_estimator hamming --list-routes
.venv/bin/python -m codebased_estimator hamming --schemes Mito --goal key_recovery \
  --classical-algorithms Prange Stern --quantum-algorithms --json
```

`--list` 和 `--list-routes` 不运行估计器；后者列出 119 条路线，包含 QCTM、UVW-KEM 尚无模型的密钥记录。可用 `--schemes`、`--parameter-sets` 和 `--goal key_recovery|msg_recovery|both` 筛选。

HARE/NSS-HQC/TriQ-KEM/Mito/QUBE 的消息恢复同时比较 `u_only` 与 `composite`，统一忽略截断、压缩残差和未知消息成本。Mito 密钥恢复同时比较 `baseline` 与 `parity`，后者为增加奇偶校验行的随机 SD 秩代理。经典与量子分别择优，精确并列均保留。

`hamming` 默认 `--doom auto`；`--doom none` 只关闭多目标，仍保留所有候选路径。量子 QCSD 自动回退至单目标估计。路线公式和目标数见[方案映射](docs/model.md#内置-hamming-方案的-doom-映射)。

`estimate`／`hamming` 默认运行后端默认经典候选和全部注册量子候选，其中 QPrange 仅返回未实现记录。算法选项后不列名称可关闭该类别。`--memory-bound` 设置经典内存上限的 log₂ 值；量子内存未估计。量子矩阵配置可用 `--quantum-matrix-profile partial-m4ri-aggregate-v1` 切换。

## 输出

- 时间和内存均为 log₂ 值。经典单位为位操作和 bits；量子时间为模型定义的 `quantum_bit_operations`，内存为 `null`。结果不是设备运行时间或整个方案的安全位数。
- 默认简短文本保留成本、胜者、不可用原因及代理／回退提示。`--details` 展开 Hamming 经典简表；`--no-brief` 显示完整假设与来源。
- `--json` 保存完整报告；`hamming --json` 对多路线组附加 `route_comparison`。`hamming --csv` 导出逐算法摘要，以 `is_best`／`is_best_route` 区分路线内／跨路线胜者。两种格式均不受 `--brief` 影响。

## Python API

```python
from codebased_estimator import Options, compare_routes, estimate, hamming_instances

options = Options(classical_algorithms=("Stern",), quantum_algorithms=())
instances = hamming_instances(parameter_sets=["Mito-1-128"], goal="key_recovery")
reports = [estimate(instance, options=options) for instance in instances]
print(compare_routes(reports)[0].to_dict())
```

自定义输入使用 `AttackInstance.from_dict(...)`；输入格式见 [instance.json](examples/instance.json)。比较仅覆盖同组选项下已估计的候选，不保证全局最优。

## 测试

```sh
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```
