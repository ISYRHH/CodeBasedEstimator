# HARE 的公开尾部约束

本模块验证实际公开密文能提供哪些线性约束。它不增加默认攻击路线，不输出新的攻击成本；现有 CE、分块和量子成本内核继续使用原接口。`composite` 仍是免费给定完整、未压缩、已去消息向量的条件参考。

## 输入与位序

`codebased_estimator.hare_observations` 使用 GF(2) 运算，整数的第 `i` 位表示多项式的 `X^i` 系数，消息也按低位在前编号。统一变量顺序为 `(r1,r2,e)`，三个向量都保留完整环长 `r`。

| 输入 | 含义 |
|---|---|
| `r` | 循环环长度，bits |
| `h,s` | 由公钥展开的两个公开环向量，不是私钥 |
| `u` | 完整的第一密文分量 |
| `positions` | 原始编码向量中被原样发送的坐标，HARE 为 `[l2,l1)` |
| `v2` | 按 `positions` 顺序打包的公开未压缩尾部 |
| `BinaryMessageImage(q,columns)` | 编码器在这些坐标上的公开线性映射；每个消息单位向量对应一个 `q` 位输出列 |

实际 KR 密文还含压缩前缀和盐。本子路线只使用 `u,v2`，压缩前缀没有被假定为完整原向量，也没有补零。调用方提交的 `r1,r2,e` 只是待检查的候选，模块不接收私钥、消息或封装种子作为求解输入。

## 方程与消息消去

记 `R` 为坐标投影，`H,S` 为由 `h,s` 定义的循环乘法，`G` 为尾部消息矩阵：

$$
u=r_1+Hr_2,\qquad v_2=Gm+R(Sr_2+e).
$$

模块精确构造完整左消去矩阵 `L`，满足 `LG=0`、`rank(L)=q-d`、`ker(L)=im(G)`，其中 `q=len(positions)`、`d=rank(G)`。因此

$$
Lv_2=LR(Sr_2+e)
$$

与“存在消息 `m` 使尾部方程成立”等价。连同完整 `u`，环境线性秩恰为 `r+q-d`：`r1` 的单位块保证前 `r` 行独立，`e` 上的 `LR` 保证其余 `q-d` 行独立。实现直接作用于位向量，不分配真实参数的稠密循环矩阵。

`messages_for(...)` 返回一个特解及消息核基；所有相容消息组成仿射集合 `particular XOR span(kernel_basis)`，维数为 `message_bits-d`。这不是唯一消息恢复，也不是共享密钥恢复。`accepts(...)` 只检查上述线性观察，不检查块重量、KR 预像、译码或重加密。

## 冻结编码器的四档核对

| 仓库参数名 | 冻结代码目录后缀 | 尾部位数 `q` | 消息秩 `d` | 消去后约束 `q-d` | 消息核维数 |
|---|---:|---:|---:|---:|---:|
| HARE-2 | 128/kr | 29 | 6 | 23 | 122 |
| HARE-5 | 256/kr | 24 | 6 | 18 | 250 |
| HARE-7 | 384/kr | 27 | 6 | 21 | 378 |
| HARE-9 | 512/kr | 42 | 7 | 35 | 505 |

`tests/data/hare_tail_generators.json` 保存完整公开生成列及来源哈希，测试从列重新计算秩，不只比较硬编码维度。HARE-1/3 已在成本参数目录中；这里的冻结代码证据只覆盖上述四个 KR 实现，不能据此宣称已经验证 1/3 的实际密文。

## parity 与投影重量

完整双块、完整已去消息三块的全部块奇偶行，各只增加一行环境秩。本模块的实际尾部仍保留完整 `e`；因尾部严格小于环长，追加三条完整块奇偶行增加两行：`r1` 奇偶由 `u` 和 `r2` 奇偶导出，`e` 的全长奇偶则不能由局部尾部导出。实现也处理完整观察时的 `G` 奇偶关系，独立小矩阵测试核对实际增秩。

固定块重本来就包含这些奇偶信息，增秩不能再作为独立信息扣一次安全位。以上均未接入费用或成功率。

若以后把 `e` 缩为 `e_T=Re`，形式维度是 `N=2r+q,K=r+d`，但它不是当前已计价的普通 SD 输入。对全长均匀固定重 `we`，投影重 `J` 的先验为

$$
\Pr[J=j]=\frac{\binom qj\binom{r-q}{w_e-j}}{\binom r{w_e}}.
$$

`projected_weight_distribution` 返回精确有理数。这里的 `J` 是 `e_T` 的重量，通常不是 `Le_T` 的重量；既不能用 `we` 或均值替代，也不能自动视为给定密文后的后验。被删坐标仍是未知量，多个隐藏补全也不等于多个可用恢复解。

## 使用和复现

普通使用只需项目原有 Python 环境，无量子硬件要求。例如：

```python
from codebased_estimator.hare_observations import BinaryMessageImage, CyclicTailObservation

# 小例：位置 0,2 的消息像为 {00,11}；这些是合成公开输入。
image = BinaryMessageImage(2, (0b11,))
observation = CyclicTailObservation(
    r=3, h=0b001, s=0b011, positions=(0, 2),
    message_image=image, u=0b001, v2=0b11,
)
print(observation.accepts(r1=0b001, r2=0, e=0))
print(observation.messages_for(r1=0b001, r2=0, e=0))
print(observation.to_dict())  # total_attack_time_log2 为 None
```

重新从冻结 C 包导出生成列需要 C99 编译器；`--source-root` 指向同时包含 `Implementations/` 的包目录：

```sh
python tools/export_hare_tail.py --source-root /path/to/frozen-package \
  --output tests/data/hare_tail_generators.json
python -m pytest -q tests/test_hare_observations.py
```

导出器在临时目录编译原参考源文件，不修改它们，并检查输入源码哈希前后一致。每个消息单位向量都调用原 `code_encode`，另核对零消息和确定性线性组合。普通测试读取已导出的公开矩阵，不要求另备 HARE 源码。

## 验证范围及下一层

测试穷举小消息矩阵的像、核及全部消息纤维，比较原方程与消去方程的解集，并独立核对循环方向、列序、parity 秩、非前缀投影和超几何计数；包含遗漏坐标非零、`Le_T` 不保重的反例。四档测试使用冻结生成矩阵和合成稀疏见证，验证真实尺寸下的矩阵自由运算；这不是寻找见证的攻击程序。

下一层加入提交 KR 映射指定的 1024 个表首预像约束，再联合验证候选的公开恢复延续。实际可用解概率、结构求解费用、恢复核查费用和可用 DOOM 目标数闭合后，才能增加可计价路线；不能先把约束数换成安全位或沿用完整循环目标数。
