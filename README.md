# CodeBasedEstimator

编码密码译码成本估计工具，基于 [CryptographicEstimators](https://github.com/Crypto-TII/CryptographicEstimators) 2.1.1。支持经典 SD／Rank SD、本地 MAGE-Stern 和二元 SD 的 QSS／QMMT+ 量子估计；内置 9 个 Hamming 方案、41 组参数。算法口径与适用范围见[模型说明](docs/model.md)，TRIKE v1.6、Mito/QUBE 参数见[参数一致性](docs/parameter_consistency.md)。

## 安装

需要 Python ≥ 3.9：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## 网页界面

启动本地英文交互工作台，无需安装 Node.js 或额外前端依赖：

```sh
.venv/bin/python -m codebased_estimator.web
```

浏览器打开 <http://127.0.0.1:8000>。可用 `--port 8080` 更改端口；安装后也可运行 `codebased-estimator-web`。按 `Ctrl+C` 关闭服务和计算任务。

- **Estimator**：选择内置方案、参数组、恢复目标和算法；也可手动输入 SD／QCSD／QCCF／Rank SD，或导入实例 JSON。首次体验可点击 **Load example**，再点击 **Run estimation**。不适用或尚未实现的算法会禁用；经典和量子算法分别提供 **Select all / Clear**。
- **批量估计**：将 **Evaluate** 改为 **All parameter sets in this scheme**，使用所选估计算法依次计算该方案的全部参数组。可选择 **Both** 覆盖两种恢复目标；最小成本按参数组和恢复目标分别统计，批量报告同样支持取消、历史记录及 JSON／CSV 导出。
- **Parameters**：搜索全部内置参数，查看原始参数、来源与备注，载入工作台；映射后的译码参数显示在 **Recovery routes**。
- **Results**：分别比较经典与量子成本，查看每条路线的完整假设、算法状态及参数，下载 JSON／CSV 报告。
- **History**：最近 10 次完成的计算保存在当前浏览器，可重新打开报告；浏览器存储不可用或容量不足时请下载报告。

网页直接调用现有 Python 估计引擎，不使用模拟结果。默认只选择 Prange；较大参数及更多候选可能耗时较长，可取消正在运行的任务。服务最多同时运行 2 个独立计算进程，每项任务限时 30 分钟。服务仅监听本机回环地址，面向本地研究使用。量子内存仍标为未估计，不受经典内存上限约束。

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

已知各块重量的路线默认启用 `--unbalanced auto`，修正外层成功概率并重新优化；`--unbalanced none` 使用总重量基线。适用范围见[外层块概率](docs/model.md#unbalanced-外层块概率)。

## 输出

- 时间／内存为 log₂ 值；经典单位为位操作／bits，量子时间为 `quantum_bit_operations`，量子内存未估计。结果是所选路线的模型成本，不代表设备耗时或方案安全位数。
- `--json` 输出完整报告，`hamming --csv` 输出逐算法摘要；`--no-brief` 补充路线、解数、实际使用的目标数及参数来源，同一来源只显示一次。模型假设与适用范围见[模型说明](docs/model.md)。

## Python API

```python
from codebased_estimator import Options, compare_routes, estimate, hamming_instances

options = Options(classical_algorithms=("Stern",), quantum_algorithms=())
instances = hamming_instances(parameter_sets=["Mito-1-128"], goal="key_recovery")
reports = [estimate(instance, options=options) for instance in instances]
print(compare_routes(reports)[0].to_dict())
```

自定义输入使用 `AttackInstance.from_dict(...)`；二元实例可添加 `"block_profile": {"lengths": [100, 100], "weights": [12, 4]}`，长度与重量分别合计为 `n`、`w`。Python API 提供 `BlockProfile`，`hamming_instances(unbalanced="none")` 可关闭块概率。路线比较仅覆盖已估计的候选。

## 测试

```sh
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

前端状态与 JSON 导入的回归测试使用 Node.js 内置测试工具（运行网页本身不需要 Node.js）：

```sh
node --test tests/test_web_ui.cjs
```
