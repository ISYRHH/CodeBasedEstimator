# Decoding Cost Lens (DCL)

编码密码译码成本估计工具，基于 [CryptographicEstimators](https://github.com/Crypto-TII/CryptographicEstimators) 2.1.1。支持经典 SD／Rank SD、MAGE-Stern 和二元 SD 的 QPrange／QSS／QMMT+ 量子估计；内置 10 个 Hamming 方案（47 组参数）和 5 个 Rank 方案（17 组参数）。成本口径见[模型说明](docs/hamming_model.md)，QPrange 及其块画像的范围见[使用说明](docs/qprange.md)，参数版本与差异见[参数说明](docs/parameter_consistency.md)。

[项目网站](https://pqc-dcl.info/) 汇总了 NGCC 首轮候选方案的译码成本估计结果。[配套论文（IACR ePrint 2026/2994）](https://eprint.iacr.org/2026/2994) 说明了如何将密钥恢复与消息恢复建模为译码问题，并将估计成本与各方案声明的成本及安全目标进行比较。

## 安装

需要 Python ≥ 3.9：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## 网页界面

启动本地英文网页，无需额外前端依赖：

```sh
.venv/bin/python -m codebased_estimator.web
```

浏览器打开 <http://127.0.0.1:8000>。可用 `--port 8080` 更改端口；安装后也可运行 `codebased-estimator-web`。按 `Ctrl+C` 关闭服务和计算任务。

- 在 **Estimator** 选择方案、参数组、恢复目标和算法，或输入／导入自定义实例。快速体验：**Load example → Run estimation**。不可用算法自动禁用，经典与量子算法分别提供 **Select all / Clear**。
- **Evaluate → All parameter sets in this scheme** 批量估计当前方案；**Both** 覆盖两种恢复目标。结果按参数组、恢复目标和成本类别分别比较。
- **Parameters** 查看来源，**Recovery routes** 查看映射，**Results** 查看详情并导出 JSON／CSV；**History** 保留当前浏览器最近 10 次完成的运行。

网页默认只选 Prange，直接调用 Python 引擎。选择 BAG-Loong、BAG-Piglet、BRA、BRQC 或 C-Multi-UR-AG 后，可勾选对应的 `Rank-*` 算法。服务仅监听本机回环地址，最多同时运行 2 项任务；任务不限时，可随时取消。更新后端代码后需重启服务；历史报告保留运行时的结果。

## 命令行

估计 [SD](examples/instance.json) 实例（另有 [QCSD](examples/qcsd.json)／[QCCF](examples/qccf.json) 示例）：

```sh
.venv/bin/python -m codebased_estimator estimate examples/instance.json \
  --classical-algorithms Stern --quantum-algorithms QSS 'QMMT+' --json
```

查看内置参数、路线并估计 Mito 密钥恢复：

```sh
.venv/bin/python -m codebased_estimator hamming --list
.venv/bin/python -m codebased_estimator hamming --list-routes
.venv/bin/python -m codebased_estimator hamming --schemes Mito --goal key_recovery \
  --classical-algorithms Prange Stern --quantum-algorithms --json
```

查看 Rank 参数及路线，或运行一个参数组：

```sh
.venv/bin/python -m codebased_estimator rank --list
.venv/bin/python -m codebased_estimator rank --schemes BAG-Loong --list-routes
.venv/bin/python -m codebased_estimator rank --parameter-sets BAG-Loong-128 \
  --goal key_recovery --classical-algorithms Rank-OJ --json
```

`rank` 默认运行所选方案的经典候选，量子候选默认关闭；可用 `--csv` 导出逐算法结果。其他 CLI 默认运行已注册的经典与量子候选；算法选项后留空可关闭该类别。`hamming` 默认 `--doom auto`，`--doom none` 关闭多目标。目标数和每综合征解数是不同输入，定义见[输入与计量](docs/hamming_model.md#输入与计量)；完整选项见各子命令的 `--help`。

已知各块重量的路线默认启用 `--unbalanced auto`，修正外层成功概率并重新优化；`--unbalanced none` 使用总重量基线。适用范围见[外层块概率](docs/hamming_model.md#unbalanced-外层块概率)。

## 输出

- 时间／内存为 log₂ 值；经典单位为位操作／bits，量子时间为 `quantum_bit_operations`，量子内存未估计。结果是所选路线的模型成本，不代表设备耗时或方案安全位数。
- 新接入的本地 Rank 算法只输出时间，内存显示为未估计；设置 `--memory-bound` 时，这些经典结果不参与最小值选择。
- `--json` 输出完整报告，`hamming --csv`／`rank --csv` 输出逐算法摘要；`--no-brief` 补充路线、解数、实际使用的目标数及来源。

## Python API

```python
from codebased_estimator import Options, compare_routes, estimate, hamming_instances

options = Options(classical_algorithms=("Stern",), quantum_algorithms=())
instances = hamming_instances(parameter_sets=["Mito-1-128"], goal="key_recovery")
reports = [estimate(instance, options=options) for instance in instances]
print(compare_routes(reports)[0].to_dict())
```

Rank 方案使用同一个 `estimate` 入口：

```python
from codebased_estimator import Options, estimate, rank_instances

instance, = rank_instances(parameter_sets=["BAG-Loong-128"], goal="key_recovery")
report = estimate(instance, options=Options(
    classical_algorithms=("Rank-OJ",), quantum_algorithms=()))
print(report.to_dict())
```

自定义输入使用 `AttackInstance.from_dict(...)`。已知块重量可用 `BlockProfile` 或 JSON 的 `block_profile` 指定，定义见[外层块概率](docs/hamming_model.md#unbalanced-外层块概率)。路线比较仅覆盖已估计的候选。

HARE 真实公开尾部的线性观察及独立验证见[公开尾部约束](docs/hare_observations.md)；该模块不增加默认估算路线或新的攻击成本。

## 测试

```sh
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

前端交互测试使用 Node.js 内置测试工具；运行网页本身不需要 Node.js：

```sh
node --test tests/test_web_ui.cjs
```

## 引用

如在研究中使用 DCL，请引用配套论文。

```bibtex
@misc{cryptoeprint:2026/2994,
  author       = {Tianrui Wang and Anyu Wang and Yuxuan Li and Qicheng Teng and Bo Pang},
  title        = {{Decoding Cost Lens}: Cost Estimation for Code-Based Cryptography},
  howpublished = {Cryptology {ePrint} Archive, Paper 2026/2994},
  year         = {2026},
  url          = {https://eprint.iacr.org/2026/2994}
}
```
