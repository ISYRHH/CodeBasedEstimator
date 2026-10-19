# CodeBasedEstimator

编码密码译码成本估计工具，基于 [CryptographicEstimators](https://github.com/Crypto-TII/CryptographicEstimators) 2.1.1。支持经典 SD／Rank SD、本地 MAGE-Stern 和二元 SD 的 QSS／QMMT+ 量子估计；内置 9 个 Hamming 方案、42 组参数。算法口径与适用范围见[模型说明](docs/model.md)，Mito/QUBE 参数见[参数一致性](docs/parameter_consistency.md)。

## 安装

需要 Python ≥ 3.9：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## 命令行

估计 [SD](examples/instance.json) 实例（另有 [QCSD](examples/qcsd.json)／[QCCF](examples/qccf.json) 示例）：

```sh
.venv/bin/python -m codebased_estimator estimate examples/instance.json \
  --classical-algorithms Stern --quantum-algorithms QSS 'QMMT+' --json
```

`--targets M` 指定目标数：QCSD 为综合征数，QCCF 为可接受非零码字数。普通 SD 的 `--log2-solutions s` 表示每个综合征的解数为 `2^s`；QCCF 必须省略此字段。

查看内置参数、路线并估计 Mito 密钥恢复：

```sh
.venv/bin/python -m codebased_estimator hamming --list
.venv/bin/python -m codebased_estimator hamming --list-routes
.venv/bin/python -m codebased_estimator hamming --schemes Mito --goal key_recovery \
  --classical-algorithms Prange Stern --quantum-algorithms --json
```

默认运行已注册的经典与量子候选；算法选项后留空可关闭该类别。`hamming` 默认 `--doom auto`，`--doom none` 关闭多目标。更多筛选与成本选项见各子命令的 `--help`。

## 输出

- 时间／内存为 log₂ 值；经典单位为位操作／bits，量子时间为 `quantum_bit_operations`，量子内存未估计。结果是所选路线的模型成本，不代表设备耗时或方案安全位数。
- `--json` 输出完整报告，`hamming --csv` 输出逐算法摘要；`--no-brief` 展开假设与来源。

## Python API

```python
from codebased_estimator import Options, compare_routes, estimate, hamming_instances

options = Options(classical_algorithms=("Stern",), quantum_algorithms=())
instances = hamming_instances(parameter_sets=["Mito-1-128"], goal="key_recovery")
reports = [estimate(instance, options=options) for instance in instances]
print(compare_routes(reports)[0].to_dict())
```

自定义输入使用 `AttackInstance.from_dict(...)`。路线比较仅覆盖已估计的候选。

## 测试

```sh
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```
