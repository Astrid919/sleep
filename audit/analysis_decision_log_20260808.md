# 分析审计与决策记录（2026-08-08）

## 1. 复杂抽样结论

- 当前重建后的主 Cox 并非未加权模型：使用 `WTMEC2YR/7`，并以 strata–PSU 聚类的 sandwich 协方差进行推断。
- 已显式构造 pooled-cycle identifiers：`cycle × SDMVSTRA` 与 `cycle × SDMVSTRA × SDMVPSU`，同时保留原始 masked design variables 供审计。
- 七个周期之间没有原始 stratum 或 stratum–PSU 编号碰撞。因此，显式 nesting 与直接使用 NCHS released masked variance units 得到完全相同的系数和协方差。
- 加权与未加权结果并不相同：Model 2 的 ≥9 h HR 分别为 1.698 与 1.772。这证明权重确实进入了主估计。

## 2. 主结果与模型诊断

- 共同 complete-case 样本：32,880 人，875 例心脏病死亡，2,629 例其他原因死亡。
- Model 2：≥9 h vs 7–<8 h，HR 1.70（95% CI 1.30–2.22）。
- Model 3：HR 1.53（1.18–1.99）。
- ≥9 h 的 `sleep × log(time)`：Model 2 P=0.312，Model 3 P=0.321；四睡眠组全局时间交互 P=0.817、0.759。未发现明确违反 PH 假设的统计证据。
- 4-knot weighted-percentile sleep spline（5、7、8、9 h）仍支持 Model 2 总体关联（P=0.004）与非线性（P=0.003）；Model 3 总体 P=0.048。

## 3. Reverse causation 与 calendar composition

在同一个 2005–2014 cycle 来源内，Model 2 的 0、2、5 年 landmark HR 分别为：

- 0 年：1.92（1.46–2.53）；
- 2 年：1.94（1.48–2.56）；
- 5 年：2.14（1.62–2.82）。

因此，原先 1.70→2.14 的比较确实混入了 cycle composition；但早期周期内部 5 年 landmark 仍较高。landmark 分析条件于存活超过该时间点，不能解释为纯粹排除 reverse causation 后的因果增强。

## 4. MI、competing risk 与绝对风险

- 20 次 MI 改用教育多项 logistic 抽样；加入心脏病事件、其他原因死亡、随访时间、Nelson–Aalen 累积风险、权重、strata、PSU 和 cycle。
- MI pooled HR：Model 2 为 1.736（1.351–2.230）；Model 3 为 1.587（1.243–2.025）。
- Fine–Gray 保留为带权重和 stratified-PSU sandwich 的近似敏感性分析，不作为完全等同于主 survey Cox 的估计器。
- 500 次分层 PSU bootstrap 中，心脏病与其他原因 cause-specific Cox 均 500/500 收敛。
- 10 年标准化风险：≥9 h 为 2.88%，7–<8 h 为 1.87%；RD 1.01 个百分点（95% bootstrap interval 0.61–1.45）。

## 5. 健康状态与炎症

在同一个 SIRI-complete 样本上，单独加入各 domain 后，long-sleep log-HR 衰减为：

- BMI：9.3%；
- hypertension/diabetes：7.0%；
- prevalent CVD：11.5%；
- log-SIRI：7.4%。

累计序列为 HR 1.71→1.63→1.60→1.54→1.50。SIRI 的真正增量是 1.54→1.50；25.4% 是所有健康状态变量累计衰减，不能归因于 SIRI，也不是 mediated proportion。

## 6. Bayesian / elastic net 决策

- 不使用 Bayesian elastic net 来追求“更显著”。惩罚模型可能改善预测稳定性，但不能修复 OSA、depression、frailty、physical activity 或 sleep quality 的未测量混杂。
- 现有 elastic-net 结果仅保留为 prediction-oriented sensitivity analysis；one-standard-error rule 没有稳定选择额外变量。
- skeptical Bayesian shrinkage 保留为阈值概率表达，而不是显著性补救：Model 3 的 skeptical posterior HR 约 1.34（95% CrI 1.08–1.67），P(HR>1.10)=0.964，P(HR>1.20)=0.844，P(HR>1.50)=0.159。
- 最稳妥的论文定位是 **robust mortality risk marker**，不是 causal effect，也不是已经验证的 prognostic model。

## 7. 文稿定位

最终故事应为：长睡眠与心脏病死亡存在 survey-validated、在多种敏感性分析中可重复的关联，并具有约 1 个百分点的 10 年绝对风险差；但健康状态衰减、未测量混杂敏感性及薄弱的 SIRI 增量更支持它是潜在健康恶化的风险标志，而不是简单的炎症介导型可干预暴露。
