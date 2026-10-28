# 通用 QPrange

本增量只把现有 `QSS` 的 `ell=p=0` 直接点暴露为 `QPrange`。准备、消元、检查、逆算、随机满行秩集合概率和显式多解代理全部复用 `quantum_costs.evaluate_parameters`；没有另造成本内核，也不是把经典总费用指数除以二。

```sh
.venv/bin/python -m codebased_estimator estimate examples/instance.json \
  --classical-algorithms --quantum-algorithms QPrange --json
```

结果是原平台 `quantum_bit_operations` 单位的 log₂ 抽象时间，量子内存未估，传入的内存上限不会应用。它不是逻辑门数、深度、量子比特数或实际设备耗时，也不证明实际结构矩阵的成功率或安全下界。

支持二元单目标 SD，显式解数沿用原独立并集代理；QCSD 仍回退单目标，不计量子 DOOM 收益。零综合征 QCCF 的可逆尾区直接点只能得到零向量，因此明确不支持。其它标签、额外结构和未建模的多目标仍明确拒绝，不会默默丢掉约束。

## 已知块重

QPrange 直接接受项目已有 `block_profile`，将它传入同一个 `evaluate_parameters` 固定点；不新增分块输入格式或概率实现。各块配额、有限成功概率及其在解数并集之前的位置均由原生外层模型计算。不会再额外乘一次块收益、秩概率，或另加旧原型中的逐块检查价格。

```sh
.venv/bin/python -m codebased_estimator estimate examples/qprange_block_profile.json \
  --classical-algorithms Prange --quantum-algorithms QPrange --json
```

例如块长 `(6,6)`、块重 `(1,3)`、`n-k=6`，原生 Prange 配额的支持命中概率为 `1/12`。这是支持事件，不是实际 QC 矩阵的联合可逆成功率；随机秩、准备和核查仍采用项目共同抽象预算。显式多解计数必须只包含满足同一块画像的解。

Hamming 路线默认已有块画像，因而现在可直接用于此类 qPrange 参考；`--unbalanced none` 保留总重量基线。QCSD 的单目标回退保留画像，但不计量子 DOOM 收益。`metadata.unbalanced` 给出原生模型、尾区配额和概率，`computed` 只表示该项目时间模型已求值，不代表完整候选攻击或安全等级认证。原有 QSS/QMMT+ 和经典算法不改。

默认量子算法名称和顺序保持原样。对于本阶段支持的无块输入，QPrange 由占位变为可计算并参与同单位择优，默认最佳量子结果可能改变。显式只选择原有算法时，结果应保持不变。
