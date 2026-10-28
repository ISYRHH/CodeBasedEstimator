# QPrange

QPrange 使用现有 `QSS` 模型的 `ell=p=0` 直接点，通过 `quantum_costs.evaluate_parameters` 计算。准备、消元、核查、逆算、随机满行秩集合概率和显式多解代理均采用项目共同模型。

固定点的抽象时间为

$$
T=T_0+\frac{n(G+1)}{\sqrt{\rho[1-(1-P)^L]}}.
$$

其中 $P$ 是外层支撑命中概率，$\rho$ 是共同秩条件概率，$L$ 是每综合征的解数；省略解数时取 $L=1$。$G$ 为共同准备与消元预算，$1$ 沿用直接分支的归一化核查价格，$T_0$ 为一次性成本。多解并集沿用给定共同秩事件后命中独立的代理。

```sh
.venv/bin/python -m codebased_estimator estimate examples/instance.json \
  --classical-algorithms --quantum-algorithms QPrange --json
```

结果是原平台 `quantum_bit_operations` 单位的 log₂ 抽象时间，量子内存未估，传入的内存上限不会应用。它不是逻辑门数、深度、量子比特数或实际设备耗时，也不证明实际结构矩阵的成功率或安全下界。

支持二元单目标 SD，显式解数沿用原独立并集代理；QCSD 仍回退单目标，不计量子 DOOM 收益。零综合征 QCCF 的可逆尾区直接点只能得到零向量，因此明确不支持。其它标签、额外结构和未建模的多目标仍明确拒绝，不会默默丢掉约束。

## 已知块重

已知块重量通过 `block_profile` 输入同一个固定点。各块配额与有限命中概率由项目外层模型计算，再进入解数并集；秩、准备和核查保持共同预算。

```sh
.venv/bin/python -m codebased_estimator estimate examples/qprange_block_profile.json \
  --classical-algorithms Prange --quantum-algorithms QPrange --json
```

例如块长 `(6,6)`、块重 `(1,3)`、`n-k=6`，原生 Prange 配额的支持命中概率为 `1/12`。这是支持事件，不是实际 QC 矩阵的联合可逆成功率；随机秩、准备和核查仍采用项目共同抽象预算。显式多解计数必须只包含满足同一块画像的解。

提供已知块重量的 Hamming 路线默认携带块画像；`--unbalanced none` 使用总重量基线。QCSD 的单目标回退保留画像，但不计量子 DOOM 收益。`metadata.unbalanced` 给出模型、尾区配额和概率；`computed` 表示该项目时间模型已求值，不代表完整候选攻击或安全等级认证。

QPrange 与 QSS、QMMT+ 按同一量子时间单位参与择优，只比较实际请求且可计算的算法。
