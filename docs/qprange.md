# 通用 QPrange

本增量只把现有 `QSS` 的 `ell=p=0` 直接点暴露为 `QPrange`。准备、消元、检查、逆算、随机满行秩集合概率和显式多解代理全部复用 `quantum_costs.evaluate_parameters`；没有另造成本内核，也不是把经典总费用指数除以二。

```sh
.venv/bin/python -m codebased_estimator estimate examples/instance.json \
  --classical-algorithms --quantum-algorithms QPrange --json
```

结果是原平台 `quantum_bit_operations` 单位的 log₂ 抽象时间，量子内存未估，传入的内存上限不会应用。它不是逻辑门数、深度、量子比特数或实际设备耗时，也不证明实际结构矩阵的成功率或安全下界。

支持二元单目标 SD，显式解数沿用原独立并集代理；QCSD 仍回退单目标，不计量子 DOOM 收益。零综合征 QCCF 的可逆尾区直接点只能得到零向量，因此明确不支持。其它标签、额外结构、多目标和块画像也明确拒绝，不会默默丢掉约束。分块 QPrange 将在下一增量直接复用仓库现有 `BlockProfile`，不会新增平行的块输入接口。

Hamming 候选默认可能带 `block_profile`，本阶段的此类 QPrange 行仍显示不支持。仅需运行通用总重量参考时，可显式使用 `hamming --unbalanced none`。原有 QSS/QMMT+ 的块画像处理不受影响。

默认量子算法名称和顺序保持原样。对于本阶段支持的无块输入，QPrange 由占位变为可计算并参与同单位择优，默认最佳量子结果可能改变。显式只选择原有算法时，结果应保持不变。
