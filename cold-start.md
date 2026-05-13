---
name: cold-start-credit-risk
description: 基于 pandas 和 numpy 的信贷风控冷启动方案。适用于无历史表现样本的新产品/新市场/新渠道场景，通过专家规则、三方数据评估、灰度上线与迭代学习快速构建初始风控策略。
allowed-tools: Bash(python3:*) Bash(python:*) Bash(pip:*) Bash(pip3:*)
---

# Cold-Start Credit Risk Strategy

## 目标与适用场景

冷启动的核心挑战：无真实表现数据与风控决策必须立即生效之间的矛盾。策略从"数据驱动"切换为"假设驱动"，通过灰度下快速迭代验证假设，逐步向数据驱动演进。

**适用场景：**
- 新国家/新市场现金贷/分期/循环贷产品冷启动
- 新渠道/新客群的首版风控规则制定
- 外部三方数据源快速准入评估与阈值设定
- 无Y标签时的规则效果前置估计
- 初始规则评分卡（Rule-based Scorecard）搭建

**工具限制：** 仅允许 `pandas`、`numpy`、`json`、`datetime`。禁止使用 scikit-learn、xgboost、lightgbm、toad、scorecardpy 等建模库。冷启动阶段无需复杂模型，所有计算必须基于 pandas DataFrame 操作，确保可审计、可复现。

## 环境校验

```bash
python3 - <<'PY'
import sys
print('python', sys.version)
for name in ['pandas', 'numpy']:
    try:
        m = __import__(name)
        print(name, getattr(m, '__version__', 'ok'))
    except Exception as e:
        print(name, 'MISSING', e)
PY
```

## 输入口径

执行前必须在 `business_config.json` 中固化以下口径：

| 字段 | 说明 | 示例 |
|------|------|------|
| `product_type` | 产品类型 | 现金贷/分期/循环贷 |
| `target_market` | 目标市场/国家 | PH / ID / MX |
| `loan_amount_range` | 件均范围 | [500, 5000] (USD) |
| `loan_tenor` | 贷款期限（天） | 7–30 / 90–180 |
| `expected_bad_rate` | 预期坏账率假设（行业对标或业务目标） | 0.08 |
| `bad_definition` | 违约定义（见下方观察窗口指引） | FPD30 / M1_DPD30+ |
| `external_data_sources` | 可用三方数据列表 | ["bureau","blacklist","telco","device"] |
| `risk_appetite` | 风险容忍度：最大可接受坏账率与最低通过率 | {"max_bad_rate": 0.12, "min_approval_rate": 0.30} |
| `pricing_buffer` | 冷启动不确定性溢价（bp，叠加在基准APR上） | 300 |
| `product_cap` | 单笔最高额度（监管或业务约束） | 5000 |
| `floor_limit` | 最低批款额度（低于此值不批） | 500 |
| `gray_traffic_ratio` | 灰度流量比例 | 0.05 |
| `observation_window` | 表现观察窗口（预设，即使无数据） | FPD30 |
| `id_col` | 客户唯一标识字段 | "user_id" |
| `time_col` | 申请时间字段 | "apply_time" |
| `feature_cols` | 候选特征字段列表 | [...] |
| `exclude_cols` | 明确不可用字段 | [...] |

---

## 信贷风控领域知识参考

> 以下内容是冷启动策略设计的领域知识基础，直接影响规则设计、阈值标定与监控指标选取。

### 一、策略漏斗（决策流）结构

信贷风控策略必须以**漏斗/瀑布式（Waterfall）**多层次执行，每层有独立的退出动作，而非将所有规则平铺并列。执行顺序固定，不可打乱：

```
申请进入
    │
    ▼
[Layer 0] KYC / 身份核验（合规强制）
    │  命中 → 拒绝（不可申诉）
    ▼
[Layer 1] 黑名单 / 欺诈信号（HIGH置信）
    │  命中 → 拒绝（记录欺诈原因码）
    ▼
[Layer 2] 监管合规（年龄/禁止行业/地域限制）
    │  命中 → 拒绝（合规原因码）
    ▼
[Layer 3] 还款能力 / 负债率（Affordability）
    │  严重不足 → 拒绝；边缘 → 降额或人工审核
    ▼
[Layer 4] 风险规则 / 专家评分（Expert Scorecard）
    │  高风险 → 拒绝；中风险 → 人工审核或降额；低风险 → 通过
    ▼
[Layer 5] 额度策略（Limit Assignment）
    │  按风险档位 × DTI 分层定额，设置 floor / cap
    ▼
通过 → 放款
```

**关键原则：**
- Layer 0-2 为硬拒（Hard Decline），无例外，无人工干预。
- Layer 3 可降额而非纯拒绝（Ability-based floor），避免因保守额度损失好客户。
- Layer 4 规则评分支持细粒度动作：拒绝（score > reject_cutoff）、人工审核（review_cutoff < score ≤ reject_cutoff）、通过（score ≤ review_cutoff）。
- 冷启动阶段 Layer 5 应使用**保守系数矩阵**（风险档位×DTI分档），而非单一固定额度。

---

### 二、违约定义与观察窗口

**不同产品适用不同违约定义**，冷启动前必须明确，且在整个迭代周期内不可随意更改：

| 产品类型 | 推荐违约定义 | 观察窗口 | 说明 |
|----------|------------|---------|------|
| 超短期（7-30天） | FPD（First Payment Default）≥1天 | 到期后7-14天 | 只有一期，到期未还即违约 |
| 短期分期（3-6个月） | M1：30 DPD at 1st payment | 首期后45天 | 首期未还30天视为违约 |
| 中期分期（6-24个月） | M3：90 DPD cumulative | 放款后90-180天 | 需要充分熟成 |
| 循环贷 | DPD30+ 最近12个月内 | 账单后60天 | 按账单周期追踪 |

**指标说明：**
- **FPD7/FPD14/FPD30**：到期后7/14/30天首逾率。超短期产品最重要的前哨指标。
- **M1+**：首月末逾期30天以上的比率。
- **M3+**：3个月末逾期90天以上（接近银行级别核销标准）。
- **DPD（Days Past Due）**：逾期天数，从应还款日起算。
- **Early-bucket roll rate**：M0→M1→M2 滚动率，冷启动阶段首选，因为样本熟成快。

> 超短期产品以 FPD30 为主 bad 定义；中长期产品若过早用 FPD 会高估/低估真实坏账率，必须用 M1+ 或 M3+。

---

### 三、三方数据源风险信号参考

冷启动依赖三方数据替代历史表现，以下是各类数据的主要风险信号及典型变量：

| 数据类型 | 核心风险信号 | 典型特征变量 | 冷启动常用方式 |
|----------|------------|------------|--------------|
| **信用局（Bureau）** | 历史违约、负债水平、查询频次 | bureau_score, num_dpd30_past12m, total_outstanding_debt, num_inquiries_30d | 直接设阈值（score/查询次数）；有分数则作为 Layer 4 主评分 |
| **多头查询（Multi-lending）** | 短期内大量借贷申请，"以贷养贷"风险 | num_loans_applied_30d, num_platforms_applied_90d, num_loans_active | 硬拒或高权重规则：30天申请笔数>3-5笔 → 拒绝 |
| **黑名单（Blacklist）** | 历史欺诈、恶意违约、法院执行 | in_fraud_blacklist, in_court_blacklist, in_telecom_blacklist | 硬拒（Layer 1） |
| **运营商数据（Telco）** | 实名注册稳定性、消费能力代理 | months_on_network, avg_monthly_arpu, num_sim_changes_6m, is_contract_user | 在网时长<6个月 → 风险升高；后付费用户风险更低 |
| **设备指纹（Device）** | 设备共享/多账号欺诈 | device_shared_accounts_30d, device_age_days, is_rooted, is_emulator | 设备30天内关联账号>2 → 欺诈信号；模拟器/root → 拒绝 |
| **银行流水（Bank Flow）** | 真实收入与负债水平 | avg_monthly_inflow, income_volatility, num_months_negative_balance, debt_service_ratio | 计算 verified income / DTI；收入稳定性评级 |
| **政府/身份核验（eKYC）** | 身份真实性 | id_match_score, face_match_score, id_in_sanctions_list | 不匹配 → 拒绝（Layer 0） |
| **社交/电商行为** | 消费行为与还款意愿代理 | ecomm_purchase_count_90d, avg_order_value, payment_on_time_rate | 作为 Layer 4 辅助特征，覆盖率低时勿用作硬拒 |

> **注意：** 覆盖率低于 70% 的三方字段不得作为硬拒唯一依据；覆盖率低于 50% 的字段只能用作辅助参考。

---

### 四、专家规则参考库

以下为冷启动阶段常见规则，含典型阈值和业务依据，应根据本市场情况调整：

**Layer 1–2：硬拒规则（HIGH 置信）**

| rule_id | 规则描述 | 典型阈值 | 数据源 | 业务依据 |
|---------|---------|---------|--------|---------|
| HR_BL001 | 欺诈黑名单命中 | in_fraud_blacklist == 1 | 内部/三方黑名单 | 历史欺诈记录，零容忍 |
| HR_BL002 | 法院执行/失信被执行人 | in_court_blacklist == 1 | 政府数据 | 偿债意愿极低 |
| HR_CO001 | 年龄不符合准入要求 | age < 18 或 age > 65 | 身份证 | 监管要求 + 还款能力 |
| HR_CO002 | 禁止行业/职业 | occupation in ['学生','无业'] | 申请信息 | 收入来源不稳定或监管限制 |
| HR_FR001 | 模拟器/机器人申请 | is_emulator == 1 | 设备指纹 | 批量欺诈特征 |
| HR_FR002 | 设备短期多账号关联 | device_accounts_30d > 2 | 设备指纹 | 身份/账号欺诈 |
| HR_KY001 | 身份证面部核验不通过 | face_match_score < 0.6 | eKYC | 身份真实性存疑 |

**Layer 3：还款能力规则（MEDIUM–HIGH 置信）**

| rule_id | 规则描述 | 典型阈值 | 数据源 | 业务依据 |
|---------|---------|---------|--------|---------|
| CA_001 | DTI 超限 | existing_debt / monthly_income > 0.6 | 申请 + bureau | 还款能力严重不足 |
| CA_002 | 收入不足覆盖本期还款 | monthly_income < installment_amount × 1.5 | 银行流水/申请 | 最低偿债能力要求 |
| CA_003 | 活跃贷款笔数过多 | num_active_loans > 5 | 多头数据 | 过度负债风险 |

**Layer 4：风险规则（MEDIUM 置信，冷启动阶段需灰度验证）**

| rule_id | 规则描述 | 典型阈值 | 数据源 | 业务依据 |
|---------|---------|---------|--------|---------|
| ER_0001 | 30天内多头申请 | num_inquiries_30d > 3 | 多头查询 | 以贷养贷信号；每增加1笔申请坏账率上升约15-20% |
| ER_0002 | 运营商在网时长偏短 | months_on_network < 6 | 运营商 | 实名注册稳定性低，欺诈/流动性风险 |
| ER_0003 | 信用分低 | bureau_score < 580 | 信用局 | 历史违约风险高（需确认该市场分值含义） |
| ER_0004 | 历史逾期30天以上 | num_dpd30_past12m > 0 | 信用局 | 历史违约行为是未来违约的最强预测因子 |
| ER_0005 | 月均ARPU极低 | avg_monthly_arpu < 1st_quartile | 运营商 | 消费能力极弱，还款能力代理指标 |
| ER_0006 | 收入极不稳定 | income_cv > 0.8 | 银行流水 | 收入波动大，还款来源不确定 |
| ER_0007 | 设备过新（欺诈高发） | device_age_days < 7 | 设备指纹 | 新设备+新账号组合是欺诈高危特征 |
| ER_0008 | 90天内申请平台数多 | num_platforms_90d > 5 | 多头 | 多平台借贷，过度负债 |

> **阈值校准原则：** 若无本市场数据，优先参考数据提供商推荐阈值或相邻市场经验值；阈值确定后记录在 `business_rationale` 中。所有 MEDIUM/LOW 置信规则须在灰度中验证后再升级置信级别。

---

### 五、灰度期早期预警指标

冷启动灰度期除坏账率（因熟成慢）外，还必须监控以下**领先指标（Leading Indicators）**：

| 指标 | 定义 | 正常范围 | 预警含义 | 监控频率 |
|------|------|---------|---------|---------|
| **联系率（Contact Rate）** | 催收首次接触成功率 | >70% | 低联系率=身份/手机号质量差，欺诈信号 | 周 |
| **用款率（Drawdown Rate）** | 批款后实际提款比例（循环贷） | >60% | 极低=产品不适配；极高（100%立即提款）=流动性危机客群 | 周 |
| **首还意愿率** | 首期还款日前完成主动还款的比例 | >85%（优质产品） | 低首还意愿=还款意愿/能力问题前兆 | 按到期批次 |
| **FPD7率** | 到期后7天内首逾率 | <5%（一般市场） | 超限=还款能力/意愿整体差，或欺诈集中爆发 | 周 |
| **客诉率（Complaint Rate）** | 每百笔放款投诉数 | <2‰ | 高投诉=产品定价/条款问题，或催收违规 | 日 |
| **数据覆盖率变化** | 三方数据每日有效返回率 | 日变化<±5% | 突然下降=数据源故障，规则命中率失效 | 日 |
| **规则命中率漂移** | 各规则每日命中率相对基准变化 | 日变化<±30% | 突变=数据质量问题或客群结构变化 | 日 |

> **早期预警的重要性：** FPD30 数据要30天后才能看到，但联系率、首还意愿率在放款后**7-14天内**就能揭示风险信号。冷启动阶段应将这些领先指标与 FPD7 结合，构成"早期预警三角"。

---

### 六、首版模型样本积累指引

| 里程碑 | 所需样本量 | 熟成要求 | 可做的事 | 注意事项 |
|--------|----------|---------|---------|---------|
| **规则初步调优** | 每核心分层 ≥ 300 件（FPD30 熟成） | 放款后45天 | 调整规则阈值、剔除无效规则 | 样本量不足时不要拆分太细 |
| **评分卡探索** | 总体 ≥ 1000 件，坏件 ≥ 100 件 | FPD30熟成 | 单变量IV筛选，简单逻辑回归尝试 | 坏件数不足100时模型不稳定 |
| **初版模型开发** | 总体 ≥ 3000 件，坏件 ≥ 300 件 | FPD30 或 M1熟成 | 评分卡开发，KS/AUC评估 | **必须处理拒绝推断偏差** |
| **模型上线** | OOT样本 ≥ 500 件 | 独立时间窗口 | 回测验证，KS>25为基本可用 | OOT时间窗口需与开发窗口隔离 |

**拒绝推断（Reject Inference）处理方法：**
- **扩增法（Augmentation）**：对拒绝样本按拒绝原因赋予假设坏账率（通常2-5倍于通过样本），然后合并训练。
- **重加权法（Reweighting / IPW）**：用通过概率的倒数对通过样本加权，模拟全量分布。
- **接受推断法（Accept Inference）**：仅用通过样本训练，但在模型验证时评估分布偏差程度并记录局限性。
- **冷启动推荐**：因样本少，优先使用接受推断法 + 保守阈值；积累 3000+ 样本后引入扩增法。

> 无论使用哪种方法，最终模型报告中必须记录拒绝推断假设和局限性，避免过度自信。

---

## 分阶段执行框架

每阶段产出对应文件，关键决策写入 `decision_log.csv`。

| 阶段 | 目标 | 核心产出 | 进入下一阶段条件 |
|------|------|----------|------------------|
| 0. 业务配置 | 固化口径、假设、成功标准 | `business_config.json`, `environment.json` | 所有口径已确认 |
| 1. 字段审计 | 排除贷后/结果/泄露字段 | `field_audit.csv` | 无泄露风险 |
| 2. 覆盖率分析 | 三方数据覆盖率与分布质量 | `coverage_report.csv` | 关键字段覆盖率 ≥70% |
| 3. 准入与反欺诈硬拒 | 黑名单/欺诈信号/合规强制规则（HIGH置信） | `hard_reject_rules.csv` | 所有硬拒规则有明确法规或业务依据 |
| 4. 专家规则设计 | 策略漏斗 + 单变量阈值 + 规则评分卡 | `strategy_waterfall.json`, `expert_rules_raw.csv`, `rule_scorecard.csv` | 所有规则有业务解释和阈值，漏斗层次清晰 |
| 5. 规则效果前置估计 | 基于假设坏账率估计效果（含增量价值与敏感性） | `rule_simulation.csv`, `incremental_value.csv`, `sensitivity_analysis.csv` | 效果在业务可接受范围，或已识别需调整规则 |
| 6. 灰度上线计划 | 分流、监控预警、回滚机制 | `gray_plan.json`, `monitoring_plan.csv` | 监控指标与回滚阈值已定义 |
| 7. 评审与可追溯 | 汇总可追溯评审报告 | `confidence_evidence.csv`, `decision_log.csv`, `strategy_summary.md` | 评审通过 |

## 置信等级与证据要求

| 等级 | 定义 | 示例 |
|------|------|------|
| HIGH | 监管要求、行业强制标准、内部黑名单、跨市场验证规则 | 年龄下限、黑名单命中、禁止行业 |
| MEDIUM | 业务专家经验，有明确逻辑，未经本市场验证 | 多头阈值、运营商在网时长 |
| LOW | 探索性假设，无直接依据，需灰度验证 | 基于分位数的试探性阈值 |

**ID 体系：** 规则 `ER_0001`，策略 `CS_001`，证据 `EVI_0001`。

**证据日志：** 每条规则在 `confidence_evidence.csv` 中必须记录 `rule_id`、`confidence`、`evidence_type`、`business_rationale`、`source`、`assumed_bad_rate`、`assumed_value`、`assumption_basis`。无历史数据时 `train_value / test_value / oot_value` 填 `N/A`。每个关键决策（阈值设定、规则组合、灰度比例）必须记录到 `decision_log.csv`。

**注意拒绝推断偏差（Reject Inference）：** 冷启动灰度通过的样本并非全量随机样本，首版模型开发必须评估并记录拒绝偏差的处理方法（见上方"首版模型样本积累指引"）。

---

## 核心代码模板

```python
# -*- coding: utf-8 -*-
from __future__ import print_function

import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

EPSILON = 1e-10


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def save_json(obj, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)


def safe_rate(num, den):
    """Return num/den; returns 0.0 when den is zero or effectively zero."""
    d = float(den)
    return float(num) / d if d > EPSILON else 0.0


def now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def log_decision(log_path, stage, object_id, decision, reason,
                 input_files='', output_files=''):
    """Append one decision row to decision_log.csv."""
    row = pd.DataFrame([{
        'timestamp': now_text(), 'stage': stage,
        'object_id': str(object_id), 'decision': decision,
        'reason': reason, 'input_files': input_files, 'output_files': output_files,
    }])
    write_header = not os.path.exists(log_path)
    row.to_csv(log_path, mode='a', index=False, header=write_header, encoding='utf-8')


# ---------- 阶段 0：业务配置 ----------

def build_business_config(product_type, target_market, loan_amount_range, loan_tenor,
                          expected_bad_rate, bad_definition, external_data_sources,
                          risk_appetite=None, pricing_buffer_bp=300,
                          product_cap=None, floor_limit=None,
                          gray_traffic_ratio=0.05, observation_window='FPD30',
                          id_col='id', time_col='apply_time',
                          feature_cols=None, exclude_cols=None):
    """
    固化冷启动业务配置。

    bad_definition: 违约定义，如 'FPD30'（超短期）、'M1_30DPD'（分期）、'M3_90DPD'（中长期）。
    risk_appetite: {'max_bad_rate': 0.12, 'min_approval_rate': 0.30}。
    pricing_buffer_bp: 冷启动不确定性溢价（基点），叠加在基准APR上用于抵补未知风险。
    product_cap: 单笔最高额度（监管或业务上限）。
    floor_limit: 最低批款额度，低于此值不批，防止小额亏损。
    """
    return {
        'product_type': product_type,
        'target_market': target_market,
        'loan_amount_range': loan_amount_range,
        'loan_tenor': loan_tenor,
        'expected_bad_rate': expected_bad_rate,
        'bad_definition': bad_definition,
        'external_data_sources': external_data_sources,
        'risk_appetite': risk_appetite or {
            # Default: tolerate up to 1.5x expected bad rate, require ≥25% approval.
            # 1.5x is derived from typical cold-start variance: with <500 mature samples
            # the 95% CI on a bad rate can easily span ±30-50% relative, so 1.5x
            # gives a safety margin before the policy triggers a mandatory review.
            # Tighten this multiplier once 1000+ samples have matured.
            'max_bad_rate': expected_bad_rate * 1.5,
            # 25% minimum approval avoids a useless pilot with too few observations.
            'min_approval_rate': 0.25,
        },
        'pricing_buffer_bp': pricing_buffer_bp,
        'product_cap': product_cap,
        'floor_limit': floor_limit,
        'gray_traffic_ratio': gray_traffic_ratio,
        'observation_window': observation_window,
        'id_col': id_col,
        'time_col': time_col,
        'feature_cols': feature_cols or [],
        'exclude_cols': exclude_cols or [],
        'created_at': now_text(),
    }


# ---------- 阶段 1：字段审计 ----------

_LEAKAGE_KEYWORDS = [
    # Post-loan delinquency terms (EN)
    'overdue', 'dpd', 'due_date', 'm0', 'm1', 'm2', 'ever_30',
    'default', 'delinquency',
    # Collection and write-off terms (EN)
    'collection', 'write_off', 'repay', 'repayment', 'settle',
    # Post-loan delinquency terms (ZH)
    '逾期', '坏账', '违约',
    # Collection and write-off terms (ZH)
    '催收', '还款', '核销',
    # Approval result / post-loan fields (ZH)
    '放款后', '审批结果', '人工审核', '贷后', '结清',
]


def audit_fields(df, feature_cols, field_meta=None, decision_time=None):
    """排除贷后字段、人工结果字段、可得时间晚于决策时间的字段。"""
    field_meta = field_meta or {}
    rows = []
    for col in feature_cols:
        meta = field_meta.get(col, {})
        text = ' '.join([col, str(meta.get('meaning', '')),
                         str(meta.get('available_time', ''))]).lower()
        keyword_hit = [kw for kw in _LEAKAGE_KEYWORDS if kw.lower() in text]
        pre_decision = bool(meta.get('pre_decision_available', True))
        post_loan = bool(meta.get('post_loan_field', False))
        time_leak = False
        if meta.get('available_time') and decision_time:
            try:
                time_leak = (pd.to_datetime(meta['available_time'])
                             > pd.to_datetime(decision_time))
            except Exception:
                pass
        leakage = bool(keyword_hit) or not pre_decision or post_loan or time_leak
        rows.append({
            'feature': col,
            'source': meta.get('source', ''),
            'meaning': meta.get('meaning', ''),
            'pre_decision_available': pre_decision,
            'post_loan_field': post_loan,
            'keyword_hit': ','.join(keyword_hit),
            'time_leakage_flag': time_leak,
            'leakage_flag': leakage,
            'decision': 'drop' if leakage else 'keep',
        })
    return pd.DataFrame(rows)


# ---------- 阶段 2：覆盖率报告 ----------

def coverage_report(df, feature_cols, min_coverage_for_hard_reject=0.70):
    """
    计算每个字段的覆盖率、唯一值数、Top1集中度，并标记是否可作为硬拒依据。
    覆盖率 <70% 的字段不得作为硬拒唯一依据（usable_for_hard_reject=False）。
    """
    total = len(df)
    rows = []
    for col in feature_cols:
        s = df[col]
        vc = s.value_counts(dropna=True)
        non_null = int(s.notna().sum())
        unique = int(s.nunique(dropna=True))
        coverage = safe_rate(non_null, total)
        rows.append({
            'feature': col,
            'sample_count': total,
            'non_null_count': non_null,
            'coverage_rate': round(coverage, 4),
            'unique_count': unique,
            'is_constant': unique <= 1,
            'top1_value': str(vc.index[0]) if len(vc) else '',
            'top1_rate': round(safe_rate(vc.iloc[0], total) if len(vc) else 0.0, 4),
            'usable_for_hard_reject': coverage >= min_coverage_for_hard_reject,
        })
    return pd.DataFrame(rows)


# ---------- 阶段 3：准入与反欺诈硬拒规则 ----------

def build_hard_reject_rules(fraud_blacklist_cols=None, compliance_rules=None):
    """
    构建漏斗 Layer 0-2 的硬拒规则：黑名单命中、合规限制、欺诈信号。
    这些规则为 HIGH 置信，必须在所有其他规则之前执行，命中即拒绝，无例外。

    fraud_blacklist_cols: list of column names that, if True/1, trigger hard reject.
    compliance_rules: list of dict with keys: rule_id, feature, direction,
                      threshold, business_rationale.
    """
    rules = []
    for col in (fraud_blacklist_cols or []):
        rules.append({
            'rule_id': 'HR_{}'.format(col[:8].upper()),
            'feature': col,
            'direction': 'eq',
            'threshold': 1,
            'action': 'reject',
            'layer': 'L1_blacklist',
            'confidence': 'HIGH',
            'business_rationale': '黑名单/欺诈信号命中，硬性拒绝',
            'source': 'blacklist',
        })
    for r in (compliance_rules or []):
        rules.append({**r, 'action': 'reject', 'confidence': 'HIGH',
                      'layer': r.get('layer', 'L2_compliance')})
    return pd.DataFrame(rules) if rules else pd.DataFrame(
        columns=['rule_id', 'feature', 'direction', 'threshold',
                 'action', 'layer', 'confidence', 'business_rationale', 'source'])


# ---------- 阶段 4：策略漏斗与专家规则 ----------

def apply_rule(df, rule, strict=False):
    """
    对 DataFrame 应用单条规则，返回布尔掩码（True=命中/触发）。
    NaN 视为未命中（False）：缺失数据不触发拒绝规则。
    若需对缺失值单独处理，请在调用前补填或单独定义"缺失值规则"。

    strict: 若为 True，feature 不存在时抛出 KeyError（推荐用于 Layer 1-2 硬拒规则，
            确保黑名单字段缺失时不会静默放行）。默认 False，仅发出 UserWarning。
    """
    feature = rule['feature']
    direction = rule['direction']
    threshold = rule['threshold']
    if feature not in df.columns:
        if strict:
            raise KeyError(
                'apply_rule(strict=True): feature "{}" not found in DataFrame. '
                'Missing fraud/blacklist signals must not silently pass. '
                'Ensure the data pipeline provides this column.'.format(feature))
        import warnings
        warnings.warn(
            'apply_rule: feature "{}" not found in DataFrame columns. '
            'Returning False for all rows. Check data pipeline or feature_cols config.'.format(feature),
            UserWarning, stacklevel=2)
        return pd.Series(False, index=df.index)
    s = df[feature]
    ops = {
        'gt':     s > threshold,
        'lt':     s < threshold,
        'gte':    s >= threshold,
        'lte':    s <= threshold,
        'eq':     s == threshold,
        'in':     s.isin(threshold if isinstance(threshold, list) else [threshold]),
        'not_in': ~s.isin(threshold if isinstance(threshold, list) else [threshold]),
    }
    if direction not in ops:
        raise ValueError('Unknown direction: {}'.format(direction))
    return ops[direction].fillna(False)


def build_strategy_waterfall(hard_reject_df, capacity_rules, risk_rules):
    """
    构建完整策略漏斗（决策流）结构。
    漏斗层次：L1_blacklist → L2_compliance → L3_capacity → L4_risk

    hard_reject_df: output of build_hard_reject_rules() — Layer 1-2
    capacity_rules: list of dicts — Layer 3 (DTI/负债/收入)
    risk_rules: list of dicts — Layer 4 (专家规则/评分卡)

    返回含 layer 字段的完整规则 DataFrame，layer 决定执行顺序。
    Layer 执行顺序: L1 → L2 → L3 → L4（发现命中即按该 layer action 处理）
    """
    layer_order = {'L1_blacklist': 1, 'L2_compliance': 2,
                   'L3_capacity': 3, 'L4_risk': 4}

    rows = []
    if hard_reject_df is not None and len(hard_reject_df):
        rows.append(hard_reject_df)

    for i, r in enumerate(capacity_rules or []):
        rows.append(pd.DataFrame([{
            'rule_id': r.get('rule_id', 'CA_{:03d}'.format(i + 1)),
            'feature': r['feature'],
            'direction': r['direction'],
            'threshold': r['threshold'],
            'action': r.get('action', 'reject'),
            'layer': 'L3_capacity',
            'confidence': r.get('confidence', 'HIGH'),
            'business_rationale': r.get('business_rationale', ''),
            'source': r.get('source', 'affordability'),
        }]))

    for i, r in enumerate(risk_rules or []):
        rows.append(pd.DataFrame([{
            'rule_id': r.get('rule_id', 'ER_{:04d}'.format(i + 1)),
            'feature': r['feature'],
            'direction': r['direction'],
            'threshold': r['threshold'],
            'action': r.get('action', 'score'),
            'layer': 'L4_risk',
            'confidence': r.get('confidence', 'MEDIUM'),
            'business_rationale': r.get('business_rationale', ''),
            'source': r.get('source', 'expert'),
            'score_weight': r.get('score_weight', 1.0),
        }]))

    if not rows:
        return pd.DataFrame()
    waterfall = pd.concat(rows, ignore_index=True, sort=False)
    waterfall['layer_order'] = waterfall['layer'].map(layer_order).fillna(99)
    return waterfall.sort_values('layer_order').reset_index(drop=True)


def apply_waterfall(df, waterfall_df, reject_cutoff=3.0, review_cutoff=1.5):
    """
    对 DataFrame 执行策略漏斗，返回含决策列的 DataFrame。

    执行逻辑：
    - Layer 1-3（action='reject'）：命中 → final_decision='reject'，记录第一个命中规则。
    - Layer 4（action='score'）：累加 score_weight，
        score > reject_cutoff → 'reject'
        review_cutoff < score ≤ reject_cutoff → 'manual_review'
        score ≤ review_cutoff → 'approve'

    reject_cutoff: Layer 4 评分拒绝阈值（需根据模拟结果校准）。
    review_cutoff: Layer 4 评分人工审核阈值。
    """
    df = df.copy()
    df['final_decision'] = 'approve'
    df['reject_rule_id'] = ''
    df['reject_layer'] = ''
    df['risk_score'] = 0.0

    # Layer 1-3: hard rejects
    hard_layers = ['L1_blacklist', 'L2_compliance', 'L3_capacity']
    hard_rules = waterfall_df[waterfall_df['layer'].isin(hard_layers)]
    for _, rule in hard_rules.iterrows():
        mask = apply_rule(df, rule.to_dict())
        # Only update rows not yet rejected
        still_pending = (df['final_decision'] == 'approve') & mask
        df.loc[still_pending, 'final_decision'] = 'reject'
        # still_pending already implies reject_rule_id == '' (rows just transitioned from approve)
        df.loc[still_pending, 'reject_rule_id'] = rule['rule_id']
        df.loc[still_pending, 'reject_layer'] = rule['layer']

    # Layer 4: risk scoring
    l4_rules = waterfall_df[waterfall_df['layer'] == 'L4_risk']
    for _, rule in l4_rules.iterrows():
        mask = apply_rule(df, rule.to_dict())
        weight = float(rule.get('score_weight', 1.0))
        df['risk_score'] += mask.astype(float) * weight

    # Apply score-based decision for still-pending rows
    pending = df['final_decision'] == 'approve'
    df.loc[pending & (df['risk_score'] > reject_cutoff), 'final_decision'] = 'reject'
    df.loc[pending & (df['risk_score'] > review_cutoff) &
           (df['risk_score'] <= reject_cutoff), 'final_decision'] = 'manual_review'

    return df[['final_decision', 'reject_rule_id', 'reject_layer', 'risk_score']]


def build_rule_candidates(expert_rules_raw):
    """从专家规则清单生成候选规则表（含 rule_id）。"""
    rows = []
    for i, rule in enumerate(expert_rules_raw):
        rows.append({
            'rule_id': 'ER_{:04d}'.format(i + 1),
            'feature': rule['feature'],
            'rule_type': rule.get('rule_type', 'numerical'),
            'direction': rule.get('direction', 'gt'),
            'threshold': rule.get('threshold'),
            'business_rationale': rule.get('business_rationale', ''),
            'source': rule.get('source', 'expert'),
            'confidence': rule.get('confidence', 'MEDIUM'),
            'layer': rule.get('layer', 'L4_risk'),
        })
    return pd.DataFrame(rows)


def compute_rule_stats(df, rule_df):
    """计算每条规则的命中率。"""
    stats = []
    for _, rule in rule_df.iterrows():
        mask = apply_rule(df, rule.to_dict())
        hit = int(mask.sum())
        stats.append({
            'rule_id': rule['rule_id'],
            'hit_count': hit,
            'hit_rate': round(safe_rate(hit, len(df)), 4),
        })
    return pd.DataFrame(stats)


def build_rule_scorecard(rule_df, weights):
    """
    构建规则评分卡：为每条规则设置分值（正值=风险增加）。
    weights: dict {rule_id: score_weight}
    返回含 score_weight 列的规则表。
    """
    df = rule_df.copy()
    df['score_weight'] = df['rule_id'].map(weights).fillna(0)
    return df


def score_applicants(df, rule_df):
    """
    对申请人进行规则评分（Layer 4 评分卡）。
    rule_df 必须含 rule_id, feature, direction, threshold, score_weight 列。
    返回含 rule_score（加权总分）和 rule_hit_count（命中规则数）的 DataFrame。
    """
    scores = pd.Series(0.0, index=df.index)
    hit_counts = pd.Series(0, index=df.index)
    for _, rule in rule_df.iterrows():
        mask = apply_rule(df, rule.to_dict())
        weight = float(rule.get('score_weight', 1.0))
        scores += mask.astype(float) * weight
        hit_counts += mask.astype(int)
    return pd.DataFrame({'rule_score': scores, 'rule_hit_count': hit_counts})


# ---------- 阶段 5：规则效果前置估计 ----------

def simulate_rule_no_y(df, mask, assumed_base_bad_rate,
                       hit_bad_rate_multiplier=2.0, pass_bad_rate_multiplier=0.85,
                       rule_id='', segment='ALL'):
    """
    基于分段假设的前置模拟（无 Y 标签）。

    命中人群坏账率 = base × hit_multiplier（被拒群体风险更高，行业经验值 1.5-3x）
    通过人群坏账率 = base × pass_multiplier（通过群体风险更低，行业经验值 0.7-0.9x）

    输出指标：
    - captured_bad_ratio: 规则命中的坏账占总假设坏账比例（规则区分能力代理）
    - bad_rate_improvement: 通过后坏账率相对基准的下降幅度
    - approval_cost: 命中率（规则带来的通过率代价）
    """
    total = len(df)
    hit_count = int(mask.sum())
    pass_count = total - hit_count
    hit_bad_rate = assumed_base_bad_rate * hit_bad_rate_multiplier
    pass_bad_rate = assumed_base_bad_rate * pass_bad_rate_multiplier
    # Validate multiplier assumptions — values above 1.0 indicate misconfigured
    # multipliers (e.g. hit_multiplier=10 gives 80% bad rate for an 8% base,
    # which is unrealistic). Raise ValueError to prevent silent mask with capping.
    if hit_bad_rate > 1.0 or pass_bad_rate > 1.0:
        raise ValueError(
            'simulate_rule_no_y: computed bad rate exceeds 1.0 before capping '
            '(hit={:.3f}, pass={:.3f}). Review multiplier assumptions: '
            'hit_multiplier={}, pass_multiplier={}, base_bad_rate={}.'.format(
                hit_bad_rate, pass_bad_rate,
                hit_bad_rate_multiplier, pass_bad_rate_multiplier,
                assumed_base_bad_rate))
    hit_bad_rate = min(hit_bad_rate, 1.0)
    pass_bad_rate = min(pass_bad_rate, 1.0)
    total_bad_assumed = total * assumed_base_bad_rate
    hit_bad = hit_count * hit_bad_rate
    pass_bad = pass_count * pass_bad_rate
    post_strategy_bad_rate = safe_rate(pass_bad, pass_count)
    captured_bad_ratio = safe_rate(hit_bad, total_bad_assumed + EPSILON)
    return {
        'segment': segment,
        'rule_id': rule_id,
        'total': total,
        'hit_rate': round(safe_rate(hit_count, total), 4),
        'pass_rate': round(safe_rate(pass_count, total), 4),
        'assumed_base_bad_rate': assumed_base_bad_rate,
        'hit_bad_rate_multiplier': hit_bad_rate_multiplier,
        'assumed_hit_bad_rate': round(hit_bad_rate, 4),
        'assumed_pass_bad_rate': round(pass_bad_rate, 4),
        'post_strategy_bad_rate': round(post_strategy_bad_rate, 4),
        'captured_bad_ratio': round(captured_bad_ratio, 4),
        'bad_rate_improvement': round(assumed_base_bad_rate - post_strategy_bad_rate, 6),
        'approval_cost': round(safe_rate(hit_count, total), 4),
    }


def simulate_strategy_no_y(df, rule_masks, assumed_base_bad_rate, strategy_id='CS_001',
                           hit_bad_rate_multiplier=2.0, pass_bad_rate_multiplier=0.85):
    """模拟整个策略（OR 合并所有规则）的整体效果。"""
    combined = pd.Series(False, index=df.index)
    for mask in rule_masks.values():
        combined = combined | mask
    return simulate_rule_no_y(
        df, combined, assumed_base_bad_rate,
        hit_bad_rate_multiplier=hit_bad_rate_multiplier,
        pass_bad_rate_multiplier=pass_bad_rate_multiplier,
        rule_id=strategy_id, segment='ALL')


def compute_incremental_value(df, rule_masks, assumed_base_bad_rate,
                              hit_bad_rate_multiplier=2.0, pass_bad_rate_multiplier=0.85):
    """
    计算每条规则在其他规则已生效前提下的增量价值（Marginal Value）。
    即：加入该规则后的坏账率改善 - 不加入时的坏账率改善。

    输出：
    - marginal_bad_rate_improvement: 该规则的增量坏账率改善
    - marginal_approval_cost: 该规则的增量通过率损失
    - incremental_efficiency: marginal_bad_rate_improvement / marginal_approval_cost
      （每损失1%通过率换来的坏账率改善，越高越好）
    """
    rule_ids = list(rule_masks.keys())
    rows = []

    # Strategy without this rule
    for rid in rule_ids:
        others = {k: v for k, v in rule_masks.items() if k != rid}
        combined_without = pd.Series(False, index=df.index)
        for m in others.values():
            combined_without = combined_without | m
        sim_without = simulate_rule_no_y(df, combined_without, assumed_base_bad_rate,
                                         hit_bad_rate_multiplier, pass_bad_rate_multiplier)

        combined_with = combined_without | rule_masks[rid]
        sim_with = simulate_rule_no_y(df, combined_with, assumed_base_bad_rate,
                                       hit_bad_rate_multiplier, pass_bad_rate_multiplier)

        marginal_br_imp = round(
            sim_without['post_strategy_bad_rate'] - sim_with['post_strategy_bad_rate'], 6)
        marginal_app_cost = round(
            sim_with['hit_rate'] - sim_without['hit_rate'], 4)
        efficiency = safe_rate(marginal_br_imp, marginal_app_cost + EPSILON)
        rows.append({
            'rule_id': rid,
            'marginal_bad_rate_improvement': marginal_br_imp,
            'marginal_approval_cost': marginal_app_cost,
            'incremental_efficiency': round(efficiency, 4),
        })
    return pd.DataFrame(rows).sort_values('incremental_efficiency', ascending=False)


def sensitivity_analysis(df, rule_masks, base_assumed_bad_rate, shocks=None):
    """对假设坏账率进行敏感性分析（悲观/中性/乐观）。"""
    shocks = shocks or [0.8, 1.0, 1.2]
    rows = []
    for shock in shocks:
        assumed = base_assumed_bad_rate * shock
        sim = simulate_strategy_no_y(df, rule_masks, assumed, strategy_id='sensitivity')
        sim['shock_factor'] = shock
        sim['assumed_bad_rate'] = round(assumed, 4)
        rows.append(sim)
    return pd.DataFrame(rows)


# ---------- 阶段 6：灰度计划与监控 ----------

def build_gray_plan(gray_ratio=0.05, split_method='random', random_state=42,
                    id_col='id', rollback_thresholds=None):
    """
    生成灰度分流计划。
    rollback_thresholds: 硬性回滚触发阈值，必须预设，不得依赖人工判断。
    默认阈值为行业保守参考值，需根据产品特性调整。
    """
    return {
        'gray_ratio': gray_ratio,
        'split_method': split_method,
        'random_state': random_state,
        'id_col': id_col,
        'rollback_thresholds': rollback_thresholds or {
            'fpd7_rate_hard_stop': 0.15,          # 3x normal (~5%) — conservatively high for cold-start
                                                   # where the true distribution is unknown; tighten after pilot
            'hit_rate_daily_change_pct': 0.30,     # 规则命中率单日变化超30%
            'third_party_coverage_drop': 0.20,     # 三方数据覆盖率下降超20%
            'contact_rate_floor': 0.50,            # 联系率低于50%（欺诈/身份质量信号）
            'complaint_rate_per_1000': 5.0,        # 每千笔投诉超5件
        },
        'created_at': now_text(),
    }


def assign_gray_label(df, gray_plan):
    """为申请人分配灰度标签（is_gray=True 为灰度组，False 为对照组）。"""
    df = df.copy()
    method = gray_plan['split_method']
    id_col = gray_plan['id_col']
    if method == 'random':
        np.random.seed(gray_plan['random_state'])
        df['is_gray'] = np.random.rand(len(df)) < gray_plan['gray_ratio']
    elif method == 'hash':
        # Use hashlib.md5 for deterministic results across Python sessions.
        # Python's built-in hash() is randomized by PYTHONHASHSEED and is
        # not safe for reproducible gray label assignment in production.
        import hashlib
        def _stable_hash(x):
            return int(hashlib.md5(str(x).encode('utf-8')).hexdigest(), 16) % 100
        hashes = df[id_col].apply(_stable_hash)
        df['is_gray'] = hashes < gray_plan['gray_ratio'] * 100
    else:
        raise ValueError('split_method must be "random" or "hash"')
    return df


def build_monitoring_plan(gray_plan, observation_window='FPD30'):
    """
    生成灰度期监控计划，包含信贷风控专用的领先指标（Leading Indicators）。
    领先指标比坏账率提前7-21天揭示风险信号，冷启动阶段尤为重要。
    """
    rb = gray_plan.get('rollback_thresholds', {})
    fpd7_stop = rb.get('fpd7_rate_hard_stop', 0.15)
    rows = [
        # --- 领先指标（最重要，最早可看到）---
        {'metric': 'contact_rate',
         'description': '催收首次联系成功率（身份/手机号质量代理）',
         'frequency': 'weekly',
         'warning_threshold': rb.get('contact_rate_floor', 0.50) + 0.10,
         'hard_stop_threshold': rb.get('contact_rate_floor', 0.50),
         'unit': 'rate', 'indicator_type': 'leading'},
        {'metric': 'repayment_initiation_rate',
         'description': '首还款日前主动发起还款比例',
         'frequency': 'per_due_batch',
         'warning_threshold': 0.80,
         'hard_stop_threshold': 0.65,
         'unit': 'rate', 'indicator_type': 'leading'},
        {'metric': 'fpd7_rate',
         'description': '7日首逾率（超短期产品核心指标）',
         'frequency': 'weekly',
         'warning_threshold': round(fpd7_stop * 0.8, 4),
         'hard_stop_threshold': fpd7_stop,
         'unit': 'rate', 'indicator_type': 'leading'},
        {'metric': 'drawdown_rate',
         'description': '批款后实际提款比例（循环贷/授信产品）',
         'frequency': 'weekly',
         'warning_threshold': None,
         'hard_stop_threshold': None,
         'unit': 'rate', 'indicator_type': 'leading'},
        {'metric': 'complaint_rate_per_1000',
         'description': '每千笔放款投诉数',
         'frequency': 'daily',
         'warning_threshold': rb.get('complaint_rate_per_1000', 5.0) * 0.6,
         'hard_stop_threshold': rb.get('complaint_rate_per_1000', 5.0),
         'unit': 'count_per_1000', 'indicator_type': 'leading'},
        # --- 规则与数据质量指标 ---
        {'metric': 'hit_rate_daily_change',
         'description': '规则命中率日变化幅度',
         'frequency': 'daily',
         'warning_threshold': rb.get('hit_rate_daily_change_pct', 0.30) * 0.7,
         'hard_stop_threshold': rb.get('hit_rate_daily_change_pct', 0.30),
         'unit': 'pct_change', 'indicator_type': 'quality'},
        {'metric': 'third_party_coverage',
         'description': '三方数据每日有效覆盖率（相对基准的下降幅度）',
         'frequency': 'daily',
         'warning_threshold': rb.get('third_party_coverage_drop', 0.20) * 0.5,
         'hard_stop_threshold': rb.get('third_party_coverage_drop', 0.20),
         'unit': 'drop_pct', 'indicator_type': 'quality'},
        # --- 滞后指标（熟成后才可看）---
        {'metric': observation_window.lower() + '_rate',
         'description': '{} 首逾率（主 bad 定义）'.format(observation_window),
         'frequency': 'monthly',
         'warning_threshold': None,
         'hard_stop_threshold': None,
         'unit': 'rate', 'indicator_type': 'lagging'},
        {'metric': 'approval_rate',
         'description': '通过率（策略松紧监控）',
         'frequency': 'daily',
         'warning_threshold': None,
         'hard_stop_threshold': None,
         'unit': 'rate', 'indicator_type': 'operational'},
        {'metric': 'fraud_hit_rate',
         'description': '欺诈/黑名单命中率',
         'frequency': 'daily',
         'warning_threshold': None,
         'hard_stop_threshold': None,
         'unit': 'rate', 'indicator_type': 'quality'},
    ]
    return pd.DataFrame(rows)


def estimate_min_sample_size(confidence=0.95, mde_pct=0.20, base_bad_rate=0.08,
                             n_segments=1):
    """
    估算首次规则调优所需的最小熟成样本量。

    基于比例检验的样本量公式：
    n = z² × p × (1-p) / (mde × p)²
    其中 p = base_bad_rate, mde_pct = 可检测的最小相对变化。

    n_segments: 需要分别分析的细分数（总样本量 = n_per_segment × n_segments）。
    返回：{'n_per_segment': ..., 'total_n': ..., 'bad_count_per_segment': ...}

    注意：这是统计最小量（正态近似二项比例检验），实际建议翻倍以确保每个分层的坏件数≥30。
    公式：n = z² × p × (1-p) / (Δ)²，其中 Δ = mde_pct × p（绝对检测边界），
    要求 np > 5（正态近似条件）。
    """
    from math import ceil, sqrt
    z = 1.96 if confidence == 0.95 else (2.576 if confidence == 0.99 else 1.645)
    p = base_bad_rate
    mde = mde_pct * p  # absolute MDE
    n_per_segment = ceil(z ** 2 * p * (1 - p) / (mde ** 2))
    # Ensure at least 30 bad cases per segment: the Central Limit Theorem (CLT)
    # approximation for binomial proportions requires np > 5 (and np(1-p) > 5),
    # but empirically 30 bad cases is a common minimum for stable bad rate estimates
    # in credit risk (avoids extreme variance in observed bad rate e.g. 0/100 = 0%).
    # This threshold can be relaxed to 15 for exploratory analysis or tightened
    # to 50+ for segment-level policy decisions requiring high confidence.
    n_for_30_bads = ceil(30 / p)
    n_per_segment = max(n_per_segment, n_for_30_bads)
    return {
        'confidence': confidence,
        'base_bad_rate': base_bad_rate,
        'detectable_relative_change_pct': mde_pct,
        'n_per_segment': n_per_segment,
        'bad_count_per_segment': round(n_per_segment * p),
        'n_segments': n_segments,
        'total_n_required': n_per_segment * n_segments,
    }


# ---------- 证据与总结 ----------

def build_evidence_entry(rule_id, confidence, evidence_type, business_rationale,
                         source, assumed_bad_rate, assumed_lift, hit_rate,
                         coverage_rate, train_value='N/A', test_value='N/A',
                         oot_value='N/A', assumed_value=None, assumption_basis=None):
    return {
        'evidence_id': 'EVI_{}'.format(rule_id),
        'object_type': 'rule',
        'object_id': rule_id,
        'confidence': confidence,
        'evidence_type': evidence_type,
        'business_rationale': business_rationale,
        'source': source,
        'assumed_bad_rate': assumed_bad_rate,
        'assumed_lift': assumed_lift,
        'hit_rate': hit_rate,
        'coverage_rate': coverage_rate,
        'train_value': train_value,
        'test_value': test_value,
        'oot_value': oot_value,
        'assumed_value': assumed_value if assumed_value is not None else assumed_lift,
        'assumption_basis': assumption_basis or 'industry_benchmark',
    }


def build_strategy_summary(config, field_audit_df, rule_df, strategy_sim,
                           gray_plan, sample_size_plan=None):
    """生成策略总结 Markdown 报告（所有占位符均来自实际计算结果）。"""
    keep = int((field_audit_df['decision'] == 'keep').sum()) if field_audit_df is not None else 'N/A'
    drop = int((field_audit_df['decision'] == 'drop').sum()) if field_audit_df is not None else 'N/A'
    high = int((rule_df['confidence'] == 'HIGH').sum()) if rule_df is not None else None
    medium = int((rule_df['confidence'] == 'MEDIUM').sum()) if rule_df is not None else None
    low = int((rule_df['confidence'] == 'LOW').sum()) if rule_df is not None else None
    rule_total = (high + medium + low) if high is not None else None
    hit_rate = strategy_sim.get('hit_rate', 'N/A') if strategy_sim else 'N/A'
    pass_rate = strategy_sim.get('pass_rate', 'N/A') if strategy_sim else 'N/A'
    post_br = strategy_sim.get('post_strategy_bad_rate', 'N/A') if strategy_sim else 'N/A'
    min_n = sample_size_plan.get('total_n_required', 'N/A') if sample_size_plan else 'N/A'
    lines = [
        '# 冷启动风控策略总结报告\n',
        '## 1. 业务配置',
        '- 产品类型: {}  目标市场: {}'.format(
            config.get('product_type', 'N/A'), config.get('target_market', 'N/A')),
        '- 违约定义: {}  观察窗口: {}'.format(
            config.get('bad_definition', 'N/A'), config.get('observation_window', 'N/A')),
        '- 预期坏账率: {}  风险容忍度: {}'.format(
            config.get('expected_bad_rate', 'N/A'), config.get('risk_appetite', 'N/A')),
        '- 灰度比例: {}  冷启动定价溢价: {} bp'.format(
            config.get('gray_traffic_ratio', 'N/A'), config.get('pricing_buffer_bp', 'N/A')),
        '',
        '## 2. 字段审计',
        '- 可用字段: {}  剔除字段: {}'.format(keep, drop),
        '',
        '## 3. 规则清单',
        '- 规则总数: {}  HIGH: {}  MEDIUM: {}  LOW: {}'.format(
            rule_total if rule_total is not None else 'N/A',
            high if high is not None else 'N/A',
            medium if medium is not None else 'N/A',
            low if low is not None else 'N/A'),
        '',
        '## 4. 前置估计（中性假设）',
        '- 命中率: {}  通过率: {}  通过后坏账率: {}'.format(hit_rate, pass_rate, post_br),
        '',
        '## 5. 灰度计划',
        '- 灰度比例: {}  分流方法: {}'.format(
            gray_plan.get('gray_ratio', 'N/A'), gray_plan.get('split_method', 'N/A')),
        '- 回滚阈值: {}'.format(gray_plan.get('rollback_thresholds', {})),
        '',
        '## 6. 样本积累目标',
        '- 首次规则调优所需熟成样本量: {}'.format(min_n),
        '',
        '## 7. 迭代里程碑',
        '- 里程碑1: FPD7 数据可读（放款后7-14天），检查早期预警三角（联系率/首还意愿/FPD7）',
        '- 里程碑2: 积累足够熟成样本后首次规则调优（详见 estimate_min_sample_size）',
        '- 里程碑3: 坏件数≥100后探索评分卡，评估单变量IV值',
        '- 里程碑4: 坏件数≥300+后开发初版评分卡（必须处理拒绝推断偏差）',
        '',
        '## 8. 风险提示',
        '- 所有估计基于假设，无历史表现数据，实际效果可能偏离',
        '- 三方数据覆盖率可能随时间波动，需每日监控',
        '- 灰度期间优先看领先指标（联系率/首还意愿率/FPD7），不要只等FPD30',
        '- 灰度样本存在拒绝推断偏差，不可直接用于全量建模，需记录处理方法',
        '- 冷启动定价溢价（pricing_buffer_bp）须在积累足够数据后重新评估是否可降低',
    ]
    return '\n'.join(lines)
```

## 最终交付清单

推荐输出目录 `output/cold_start/`

| 文件 | 阶段 | 说明 |
|------|------|------|
| `business_config.json` | 0 | 业务配置与口径（含 bad_definition / risk_appetite / pricing_buffer） |
| `environment.json` | 0 | Python 环境版本 |
| `field_audit.csv` | 1 | 字段泄露审计结果 |
| `coverage_report.csv` | 2 | 三方数据覆盖率报告（含 usable_for_hard_reject 标记） |
| `hard_reject_rules.csv` | 3 | Layer 1-2 准入与反欺诈硬拒规则 |
| `strategy_waterfall.json` | 4 | 完整策略漏斗（Layer 1-4 全部规则及执行顺序） |
| `expert_rules_raw.csv` | 4 | 原始专家规则清单 |
| `rule_scorecard.csv` | 4 | Layer 4 规则评分卡权重表 |
| `rule_simulation.csv` | 5 | 单规则前置估计 |
| `incremental_value.csv` | 5 | 每条规则增量价值（效率排序） |
| `sensitivity_analysis.csv` | 5 | 坏账率假设敏感性分析（含±20%场景） |
| `sample_size_plan.json` | 5 | 首次调优所需样本量估算 |
| `gray_plan.json` | 6 | 灰度分流与回滚计划（含领先指标回滚阈值） |
| `monitoring_plan.csv` | 6 | 监控指标（含领先/滞后指标分类与预警阈值） |
| `confidence_evidence.csv` | 7 | 规则置信证据表 |
| `decision_log.csv` | 全程 | 关键决策日志 |
| `strategy_summary.md` | 7 | 策略评审报告 |

## 禁止事项

1. **禁止使用 ML 建模库**：冷启动阶段禁止 scikit-learn、xgboost、lightgbm、toad、scorecardpy。
2. **禁止跳过灰度直接全量上线**：灰度比例不低于 1%，建议 5%。对照组必须保留基本合规与反欺诈规则。
3. **禁止无依据设定阈值**：所有规则阈值必须有业务解释或外部对标，记录在 `business_rationale`。
4. **禁止覆盖率 <70% 的字段作为唯一硬拒依据**：可降级为人工审核参考或观察字段。
5. **禁止使用贷后字段**：严格排除任何审批时点不可得的字段（逾期状态、催收记录、放款后行为）。
6. **禁止无假设的模拟**：前置估计必须基于显式假设坏账率和 lift 倍数，包含悲观/中性/乐观三个场景。
7. **禁止省略证据日志**：每条规则、每个阈值设定必须记录到 `decision_log.csv`，缺失证据的规则不得进入灰度。
8. **禁止无预设回滚条件上线**：`gray_plan.json` 必须包含基于指标的硬性回滚触发阈值，不得依赖事后人工判断。
9. **禁止在未完成字段审计时进入规则设计**：阶段 1 字段审计是强制前置条件。
10. **禁止仅凭通过率或放款量判断灰度成功**：必须同时监控领先指标（联系率/首还意愿/FPD7）、欺诈命中率和三方数据质量。
11. **禁止打乱漏斗层次**：Layer 1-2 硬拒必须在 Layer 4 评分之前执行，顺序不可颠倒。
12. **禁止忽略冷启动定价溢价**：risk_appetite 不满足时，应优先考虑调整 pricing_buffer_bp 而非仅收紧规则。
