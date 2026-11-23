# ZD-MM 成本模型

Zero-direction maximal minors（ZD-MM）把普通 MM 的最后一次猜零换成块内的方向枚举。估计器覆盖五个内置 Rank 方案的 17 组参数，每组分别估计密钥恢复和消息恢复。BAG-Loong 和 BAG-Piglet 取 $\omega=2.8$，BRA、BRQC 和 C-Multi-UR-AG 取 $\omega=2$。

## 结构与输入

| 方案 | 报告选用的结构 |
|---|---|
| BAG-Loong | 按两块支撑的交维计算子式数。密钥侧使用已知支撑元素 $1$，消息侧选取公开零尾中的完整密文行。 |
| BAG-Piglet | 按直和块的秩分别计数。部分参数使用中间域打包。256 档的密钥和消息分别取 $d=2,3$，384 档的两个目标均取 $d=2$。 |
| BRA | 转置交换二元坐标矩阵的块长与扩域次数，保留各块的秩。三档均选用转置后的两块表示，消息侧使用第一密文分量。 |
| BRQC | 消息投影按物理块长计算子式数，并按扣除消息核后的有效块长计算方程数。这里对应报告主表的方程计数结果。 |
| C-Multi-UR-AG | 密钥实例使用一个样本及已知支撑元素 $1$，消息实例使用满消息像的列投影，投影后的码维数为 $n_0+k_{\rm msg}$。 |

每个目标使用报告选定的一组归约、猜零数、穿孔数和收缩块。运行时从这些输入计算方程规模、概率和费用。同一条命令可同时选择原仓库的 `Rank-MM` 和 `Rank-ZD-MM`。报告中用于单独衡量方向枚举收益的普通 MM 基线另外采用了与 ZD-MM 相同的结构归约。

例如，BRA-128 密钥恢复在原仓库的 `Rank-MM` 下为 194.6 比特。采用报告的结构归约后，普通 MM 为 116.025 比特，ZD-MM 为 112.088 比特。两者相差 3.937 比特。

CSV 的 `m`、`n` 等实例列沿用方案目录。JSON 的 `results[].parameters` 给出 ZD-MM 实际计算所用的维数。例如，原仓库的 BAG-Piglet-128 目录列出 $n=47,m=43$，ZD-MM 使用报告及 Piglet 参考实现（`bag_piglet128/src/scheme/parameters.h`）中的 $n=43,m=47$。

## 计算

设工作域大小为 $q_0=2^d$，母系统有 $E$ 个方程和 $V$ 个子式变量。ZD-MM 在 $\delta=V-E>1$ 时计算一次母系统的核。选定块 $j$ 的秩为 $r_j$，其 $L=r_j+1$ 个坐标中至少有一个非零线性组合为零，需要检查的射影方向数为 $Q=(q_0^L-1)/(q_0-1)$。施加这个零方向后，以 $E',V'$ 表示缩短后的方程数和变量数，采用 MM 门槛 $\min(E,E')\ge V'-1$。

令 $F=V-V'$，$G$ 为收缩的输出坐标数，$P$ 为外层猜零、保秩以及所选归约要求的事件同时发生的概率。固定配置的期望位操作数为

$$
T_{\rm ZD}=\frac{d^2}{P}
\left(C_{\rm set}+VE^{\omega-1}+dLF\delta+
QG\delta+QG\delta^{\omega-1}+Q C_{\rm rec}\right).
$$

括号中六项依次为准备、母系统求核、收缩准备、方向更新、小系统求解及恢复核验。`metadata.stage_log2` 给出各项乘以 $d^2/P$ 后的二进制对数。总成本 `time_log2` 为 $\log_2 T_{\rm ZD}$。`metadata.success_neglog2` 单独给出 $-\log_2 P$。

## 复算示例

```sh
python -m codebased_estimator rank --parameter-sets BAG-Loong-128 --goal key_recovery --classical-algorithms Rank-ZD-MM --json
```

BAG-Loong-128 密钥侧的两块长度为 $(42,43)$，猜零数为 $(7,0)$，穿孔数为 $(0,0)$。母系统有 $246\,551\,613$ 个方程和 $249\,131\,981$ 个子式变量。第二块给出 63 个方向，六项合计为 **113.074** 比特。JSON 的 `parameters` 记录使用的配置和系统规模。

```sh
python -m codebased_estimator rank --classical-algorithms Rank-ZD-MM --csv
```

这条命令输出全部 34 个目标。工作参数见 [zd_mm_profiles.py](../codebased_estimator/zd_mm_profiles.py)，费用计算见 [zd_mm.py](../codebased_estimator/zd_mm.py)。
