Cold-Start Credit Risk Strategy Design Skill
yaml
name: cold-start-credit-risk
description: 基于 pandas 和 numpy 的信贷风控策略冷启动方案，适用于无或极少历史表现样本的场景，依赖专家经验规则、外部三方数据快速验证、灰度上线与迭代学习回路。
allowed-tools: Bash(python3:*) Bash(python:*) Bash(pip:*) Bash(pip3:*)
Cold-Start Credit Risk Strategy Design Skill
目标与适用任务
核心难点
冷启动的核心挑战在于“无真实表现数据”与“风控决策必须立即生效”之间的矛盾。因此，策略设计需从“数据驱动”切换为“假设驱动”，并通过灰度下的快速迭代验证假设。

目标
在信贷业务冷启动阶段（无历史放款数据、无表现样本、无可用评分模型），通过系统化的专家经验规则梳理、外部三方数据评估、规则组合设计与前置估计，快速构建一套可灰度上线、可迭代优化的初始风控策略，并在灰度过程中积累样本，为后续模型开发奠定基础。

适用任务
新国家/新市场现金贷产品冷启动策略设计

新渠道/新客群的首版风控规则制定

外部三方数据源的快速准入评估与阈值设定

基于业务经验的单变量硬规则设计与组合

规则效果的前置估计（无Y标签时基于假设坏账率或行业基准）

灰度上线计划与监控指标设计

初始规则评分卡（Rule-based Scorecard）搭建

环境与工具约束
仅依赖 pandas、numpy，可选 json、csv、datetime。

禁止使用 scikit-learn、xgboost、lightgbm 等机器学习建模工具（冷启动阶段无需复杂模型）。

禁止依赖 toad、scorecardpy 等评分卡专用库。

所有计算必须基于 pandas DataFrame 操作，确保可审计、可复现。

bash
python3 - <<'PY'
import sys
print('python', sys.version)
for name in ['pandas', 'numpy']:
    try:
        module = __import__(name)
        print(name, getattr(module, '__version__', 'unknown'))
    except Exception as exc:
        print(name, 'IMPORT_FAILED', exc)
PY
输入口径
执行前必须在代码或报告中固化以下口径，并写入 business_config.json：

product_type：产品类型（如现金贷、分期、循环贷）

target_market：目标市场/国家

loan_amount_range：件均范围（如 500-5000 美元）

loan_tenor：贷款期限（如 7-30 天）

expected_bad_rate：预期坏账率假设（基于行业对标或业务目标，如 8%）

external_data_sources：可用外部三方数据列表（如多头、黑名单、运营商、设备指纹等）

expert_rule_sources：专家规则来源（如行业白皮书、监管要求、历史类似项目经验）

gray_traffic_ratio：灰度流量比例（如 5%）

observation_window：表现观察窗口（如首逾 FPD30，即使无数据也需预设）

id_col：客户唯一标识

time_col：申请时间字段（用于灰度分流和后续监控）

feature_cols：所有候选字段（包括外部三方字段、申请字段）

exclude_cols：明显不可用字段（如贷后字段、人工审批结果）

分阶段执行框架
按以下阶段执行，每阶段都要产出 CSV/JSON/Markdown 文件，并把阶段判断写入 decision_log.csv。

阶段	目标	核心产出	进入下一阶段条件
0. 业务目标与口径固化	明确冷启动的业务约束、假设、可用数据源和成功标准	business_config.json, environment.json	所有口径已确认并记录
1. 字段可得性与泄露审计	排除贷后、结果、人工审批、不可稳定获取字段	field_audit.csv	字段可得性无泄露风险
2. 数据覆盖率与基础分析	评估外部三方数据的覆盖率、唯一值分布	coverage_report.csv	覆盖率、唯一值可解释，关键字段覆盖率高于70%
3. 专家规则梳理与单变量阈值设定	梳理所有可用的专家经验规则，设定初始阈值	expert_rules_raw.csv, single_rule_candidates.csv	所有候选规则有明确的阈值和业务解释
4. 规则组合与策略设计	将单变量规则组合成策略流，定义规则评分卡	strategy_flow.json, rule_combination_candidates.csv, rule_scorecard.csv	策略流清晰，组合规则有覆盖率估计
5. 规则效果前置估计	在无真实表现数据的情况下，基于假设坏账率估计效果	rule_simulation.csv, strategy_level_simulation.csv, sensitivity_analysis.csv	前置估计结果在业务可接受范围内，或已识别需调整的规则
6. 灰度上线与学习回路	设计灰度分流、监控预警、回滚机制，规划迭代路径	gray_plan.json, monitoring_plan.csv, iteration_plan.md	灰度计划完整，监控指标可执行，迭代里程碑已定义
7. 总结评审与可追溯证据	汇总所有阶段产出，形成可追溯的策略评审报告	confidence_evidence.csv, decision_log.csv, strategy_summary.md	评审通过，可进入灰度上线
置信与可追溯要求
唯一 ID 体系
每条规则必须有唯一 rule_id，格式 ER_0001（Expert Rule）。

每个策略流必须有唯一 strategy_id，格式 CS_001（Cold Start）。

每个证据条目必须有唯一 evidence_id，格式 EVI_0001。

置信等级定义（冷启动专用）
等级	定义	适用场景
HIGH	规则来源为监管要求、行业强制标准、内部黑名单、或经其他市场验证的成熟规则	年龄下限、黑名单、禁止行业
MEDIUM	规则基于业务专家经验，有明确的业务逻辑，但未经本市场验证	多头阈值、运营商在网时长
LOW	规则为探索性假设，缺乏直接依据，需灰度验证	基于外部数据分位数的试探性阈值
证据日志要求
每条规则在 confidence_evidence.csv 中必须记录：rule_id、confidence、evidence_type（如 industry_standard、expert_opinion、external_benchmark）、business_rationale、source、assumed_bad_rate（前置估计使用的坏账率假设）。

即使无历史表现数据，train_value/test_value/oot_value 三列可填 "N/A"，但必须填写 assumed_value 和 assumption_basis。

每个关键决策（如阈值设定、规则组合、灰度比例）必须记录到 decision_log.csv，包含 timestamp、stage、object_id、decision、reason、input_files、output_files。

核心代码模板
以下代码是 agent 在冷启动场景中编写正式脚本时的骨架。可按任务裁剪，但不能删除字段口径、证据、模拟和日志能力。

python
# -*- coding: utf-8 -*-
from __future__ import print_function

import json
import os
from datetime import datetime
from itertools import combinations

import numpy as np
import pandas as pd

EPSILON = 1e-10

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def save_json(obj, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)

def safe_rate(num, den):
    return float(num) / float(den) if den else 0.0

def now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def log_decision(log_path, stage, object_id, decision, reason, input_files='', output_files='', operator_note=''):
    """Append one decision row to decision_log.csv."""
    row = pd.DataFrame([{
        'timestamp': now_text(),
        'stage': stage,
        'object_id': str(object_id),
        'decision': decision,
        'reason': reason,
        'input_files': input_files,
        'output_files': output_files,
        'operator_note': operator_note,
    }])
    write_header = not os.path.exists(log_path)
    row.to_csv(log_path, mode='a', index=False, header=write_header, encoding='utf-8')

# ---------- 阶段 0：业务配置 ----------

def build_business_config(product_type, target_market, loan_amount_range, loan_tenor,
                          expected_bad_rate, external_data_sources, expert_rule_sources,
                          gray_traffic_ratio=0.05, observation_window='FPD30',
                          id_col='id', time_col='apply_time', feature_cols=None, exclude_cols=None):
    config = {
        'product_type': product_type,
        'target_market': target_market,
        'loan_amount_range': loan_amount_range,
        'loan_tenor': loan_tenor,
        'expected_bad_rate': expected_bad_rate,
        'external_data_sources': external_data_sources,
        'expert_rule_sources': expert_rule_sources,
        'gray_traffic_ratio': gray_traffic_ratio,
        'observation_window': observation_window,
        'id_col': id_col,
        'time_col': time_col,
        'feature_cols': feature_cols or [],
        'exclude_cols': exclude_cols or [],
    }
    return config

# ---------- 阶段 1：字段审计 ----------

def audit_fields_cold_start(df, feature_cols, field_meta=None, decision_time=None):
    """冷启动字段审计：排除贷后字段、人工结果字段、可得时间晚于决策时间的字段。"""
    field_meta = field_meta or {}
    risky_keywords = [
        'overdue', 'dpd', 'due_date', 'm0', 'm1', 'm2', 'ever_30', 'collection', 'write_off',
        'repay', 'repayment', 'settle', 'default', 'delinquency', '逾期', '逾期天数', '逾期金额',
        '催收', '还款', '核销', '坏账', '违约', '放款后', '审批结果', '人工审核', '拒绝原因', '贷后', '结清'
    ]
    rows = []
    for col in feature_cols:
        meta = field_meta.get(col, {})
        text = (col + ' ' + str(meta.get('meaning', '')) + ' ' + str(meta.get('available_time', ''))).lower()
        keyword_hit = [kw for kw in risky_keywords if kw.lower() in text]
        pre_decision_available = bool(meta.get('pre_decision_available', True))
        time_leakage_flag = False
        if meta.get('available_time') and decision_time:
            try:
                time_leakage_flag = pd.to_datetime(meta['available_time']) > pd.to_datetime(decision_time)
            except:
                pass
        leakage_flag = bool(keyword_hit) or (not pre_decision_available) or bool(meta.get('post_loan_field', False)) or time_leakage_flag
        rows.append({
            'feature': col,
            'source': meta.get('source', ''),
            'meaning': meta.get('meaning', ''),
            'available_time': meta.get('available_time', ''),
            'pre_decision_available': pre_decision_available,
            'post_loan_field': bool(meta.get('post_loan_field', False)),
            'keyword_hit': ','.join(keyword_hit),
            'time_leakage_flag': time_leakage_flag,
            'leakage_flag': leakage_flag,
            'decision': 'drop' if leakage_flag else 'keep',
        })
    return pd.DataFrame(rows)

# ---------- 阶段 2：覆盖率报告 ----------

def coverage_report(df, feature_cols, special_values=None):
    """计算每个字段的覆盖率（非空比例）、唯一值比例、Top1占比。"""
    special_values = special_values or {}
    total = len(df)
    rows = []
    for col in feature_cols:
        s = df[col]
        non_null = s.notna().sum()
        coverage = safe_rate(non_null, total)
        unique = s.nunique(dropna=True)
        top1 = s.value_counts(dropna=True).iloc[0] if s.value_counts(dropna=True).shape[0] > 0 else 0
        top1_rate = safe_rate(top1, total)
        rows.append({
            'feature': col,
            'sample_count': total,
            'non_null_count': int(non_null),
            'coverage_rate': coverage,
            'unique_count': int(unique),
            'top1_value': str(s.value_counts(dropna=True).index[0]) if s.value_counts(dropna=True).shape[0] > 0 else '',
            'top1_rate': top1_rate,
            'is_constant': unique <= 1,
        })
    return pd.DataFrame(rows)

# ---------- 阶段 3：单变量规则阈值设定 ----------

def generate_single_rule_candidates(expert_rules_raw):
    """从专家规则原始清单生成候选规则表。"""
    rows = []
    for i, rule in enumerate(expert_rules_raw):
        rows.append({
            'rule_id': 'ER_%04d' % (i + 1),
            'feature': rule['feature'],
            'rule_type': rule.get('rule_type', 'numerical'),
            'direction': rule.get('direction', 'gt'),
            'threshold': rule.get('threshold'),
            'business_rationale': rule.get('business_rationale', ''),
            'source': rule.get('source', 'expert'),
            'confidence': rule.get('confidence', 'MEDIUM'),
        })
    return pd.DataFrame(rows)

def apply_single_rule(df, rule):
    """对DataFrame应用单条规则，返回布尔掩码（True表示命中规则，即应拒绝/审核）。"""
    feature = rule['feature']
    direction = rule['direction']
    threshold = rule['threshold']
    if feature not in df.columns:
        return pd.Series(False, index=df.index)
    s = df[feature]
    if direction == 'gt':
        return s > threshold
    elif direction == 'lt':
        return s < threshold
    elif direction == 'gte':
        return s >= threshold
    elif direction == 'lte':
        return s <= threshold
    elif direction == 'eq':
        return s == threshold
    elif direction == 'in':
        return s.isin(threshold if isinstance(threshold, list) else [threshold])
    elif direction == 'not_in':
        return ~s.isin(threshold if isinstance(threshold, list) else [threshold])
    else:
        raise ValueError('Unknown direction: %s' % direction)

def compute_rule_coverage(df, rule):
    """计算单条规则的覆盖率（命中率）。"""
    mask = apply_single_rule(df, rule)
    return safe_rate(mask.sum(), len(df))

# ---------- 阶段 4：规则组合与策略设计 ----------

def combine_rules_or(df, rule_ids, rule_masks):
    """OR 组合多条规则，返回组合掩码。"""
    combined = pd.Series(False, index=df.index)
    for rid in rule_ids:
        if rid in rule_masks:
            combined = combined | rule_masks[rid]
    return combined

def combine_rules_and(df, rule_ids, rule_masks):
    """AND 组合多条规则。"""
    combined = pd.Series(True, index=df.index)
    for rid in rule_ids:
        if rid in rule_masks:
            combined = combined & rule_masks[rid]
    return combined

def build_rule_scorecard(rule_candidates, score_weights):
    """构建规则评分卡：每条规则赋予一个分数（负向），总分越高风险越大。"""
    # 简易实现：应用到每一行
    def row_score(row, rules, weights):
        total = 0
        for _, r in rules.iterrows():
            if apply_single_rule(pd.DataFrame([row]), r.to_dict()).iloc[0]:
                total += weights.get(r['rule_id'], 0)
        return total
    return rule_candidates  # 实际使用时需向量化处理

# ---------- 阶段 5：规则效果前置估计 ----------

def simulate_rule_no_y(df, mask, assumed_base_bad_rate, hit_bad_rate_multiplier=2.0,
                       pass_bad_rate_multiplier=0.9, rule_id='', segment='ALL'):
    """基于分段假设的前置模拟。允许对命中和通过人群设定不同的坏账率倍数。"""
    total = len(df)
    hit_count = int(mask.sum())
    pass_count = total - hit_count
    hit_rate = safe_rate(hit_count, total)

    # 核心假设
    hit_bad_rate = assumed_base_bad_rate * hit_bad_rate_multiplier
    pass_bad_rate = assumed_base_bad_rate * pass_bad_rate_multiplier

    total_bad = total * assumed_base_bad_rate
    hit_bad = hit_count * hit_bad_rate
    pass_bad = pass_count * pass_bad_rate

    # 计算整体坏账率的预期变化
    expected_total_bad_rate = (hit_count * hit_bad_rate + pass_count * pass_bad_rate) / total
    captured_bad_rate = safe_rate(hit_bad, total_bad)

    return {
        'segment': segment,
        'rule_id': rule_id,
        'total': total,
        'hit_rate': hit_rate,
        'pass_rate': safe_rate(pass_count, total),
        'assumed_base_bad_rate': assumed_base_bad_rate,
        'hit_bad_rate_multiplier': hit_bad_rate_multiplier,
        'assumed_hit_bad_rate': hit_bad_rate,
        'assumed_pass_bad_rate': pass_bad_rate,
        'expected_total_bad_rate': expected_total_bad_rate,
        'captured_bad_rate': captured_bad_rate,
        'captured_bad_rate_vs_base': safe_rate(expected_total_bad_rate, assumed_base_bad_rate) - 1,
    }

def simulate_strategy_no_y(df, rule_masks, assumed_base_bad_rate, strategy_id='CS_001',
                           hit_bad_rate_multiplier=2.0, pass_bad_rate_multiplier=0.9):
    """模拟整个策略（OR组合所有规则）的效果。"""
    combined = pd.Series(False, index=df.index)
    for mask in rule_masks.values():
        combined = combined | mask
    return simulate_rule_no_y(df, combined, assumed_base_bad_rate,
                             hit_bad_rate_multiplier=hit_bad_rate_multiplier,
                             pass_bad_rate_multiplier=pass_bad_rate_multiplier,
                             rule_id=strategy_id, segment='ALL')

def sensitivity_analysis(df, rule_masks, base_assumed_bad_rate, shocks=None):
    """对假设坏账率进行敏感性分析。"""
    if shocks is None:
        shocks = [0.8, 1.0, 1.2]
    rows = []
    for shock in shocks:
        assumed = base_assumed_bad_rate * shock
        sim = simulate_strategy_no_y(df, rule_masks, assumed, strategy_id='sensitivity')
        sim['shock'] = shock
        rows.append(sim)
    return pd.DataFrame(rows)

# ---------- 阶段 6：灰度计划 ----------

def build_gray_plan(gray_ratio=0.05, split_method='random', random_state=42, id_col='id'):
    """生成灰度分流计划。"""
    plan = {
        'gray_ratio': gray_ratio,
        'split_method': split_method,
        'random_state': random_state,
        'id_col': id_col,
        'gray_condition': 'hash(id) %% 100 < gray_ratio*100' if split_method == 'hash' else 'random_sample',
    }
    return plan

def assign_gray_label(df, gray_plan, id_col='id'):
    """为DataFrame分配灰度标签（1=灰度组，0=对照组）。"""
    if gray_plan['split_method'] == 'random':
        np.random.seed(gray_plan['random_state'])
        df['is_gray'] = np.random.rand(len(df)) < gray_plan['gray_ratio']
    elif gray_plan['split_method'] == 'hash':
        # 基于id的哈希分流
        df['_hash'] = df[id_col].apply(lambda x: hash(str(x)) % 100)
        df['is_gray'] = df['_hash'] < gray_plan['gray_ratio'] * 100
        df.drop(columns='_hash', inplace=True)
    return df

# ---------- 阶段 7：迭代计划 ----------

def build_iteration_plan(milestones):
    """生成迭代计划。milestones: list of dict，包含 sample_count, action, description。"""
    plan = pd.DataFrame(milestones)
    return plan

# ---------- 证据与总结 ----------

def build_confidence_evidence_cold_start(rule_id, confidence, evidence_type, business_rationale,
                                         source, assumed_bad_rate, assumed_lift,
                                         coverage_rate, hit_rate, train_value='N/A',
                                         test_value='N/A', oot_value='N/A'):
    """构建冷启动证据条目（无Y标签时使用假设值）。"""
    return {
        'evidence_id': 'EVI_%s' % rule_id,
        'object_type': 'rule',
        'object_id': rule_id,
        'confidence': confidence,
        'evidence_type': evidence_type,
        'business_rationale': business_rationale,
        'source': source,
        'assumed_bad_rate': assumed_bad_rate,
        'assumed_lift': assumed_lift,
        'coverage_rate': coverage_rate,
        'hit_rate': hit_rate,
        'train_value': train_value,
        'test_value': test_value,
        'oot_value': oot_value,
        'threshold': '',
        'pass_flag': '',
    }

def build_strategy_summary(business_config, field_audit, coverage, rule_candidates,
                           rule_simulation, strategy_simulation, gray_plan,
                           iteration_plan, confidence_evidence, decision_log):
    """生成策略总结 Markdown 文件。"""
    summary = """# 冷启动风控策略总结报告

## 1. 样本口径
- 产品类型: {product_type}
- 目标市场: {target_market}
- 预期坏账率: {expected_bad_rate}
- 灰度比例: {gray_traffic_ratio}
- 观察窗口: {observation_window}

## 2. 字段审计结论
- 可用字段数: {keep_fields}
- 剔除字段数: {drop_fields}
- 主要剔除原因: {drop_reasons}

## 3. 专家规则清单
- 规则总数: {rule_count}
- HIGH置信规则: {high_count}
- MEDIUM置信规则: {medium_count}
- LOW置信规则: {low_count}

## 4. 前置估计结果
- 策略命中率: {hit_rate}
- 策略通过率: {pass_rate}
- 假设命中坏账率: {hit_bad_rate}
- 假设通过坏账率: {pass_bad_rate}
- 坏账捕获率: {captured_bad_rate}

## 5. 灰度计划
- 灰度比例: {gray_ratio}
- 分流方法: {split_method}
- 监控指标: 命中率、通过率、FPD7+/FPD30+

## 6. 迭代计划
- 里程碑1: 积累1000样本后首次规则调优
- 里程碑2: 积累3000样本后尝试评分卡建模

## 7. 风险提示
- 无历史表现数据，所有估计基于假设，实际效果可能偏离
- 外部三方数据覆盖率可能随时间波动
- 灰度期间需密切监控通过率和早期逾期指标
"""
    return summary
最终交付清单
推荐输出目录 output/cold_start/

文件	阶段	说明
business_config.json	阶段0	业务配置，包含所有输入口径
environment.json	阶段0	Python环境版本
field_audit.csv	阶段1	字段可得性与泄露审计结果
coverage_report.csv	阶段2	外部数据覆盖率报告
expert_rules_raw.csv	阶段3	原始专家规则清单（人工输入）
single_rule_candidates.csv	阶段3	单变量候选规则（含阈值、依据、置信等级）
strategy_flow.json	阶段4	策略流定义（规则顺序、动作）
rule_combination_candidates.csv	阶段4	规则组合候选（OR/AND）
rule_scorecard.csv	阶段4	规则评分卡权重表
rule_simulation.csv	阶段5	单规则前置估计结果
strategy_level_simulation.csv	阶段5	策略级前置估计结果
sensitivity_analysis.csv	阶段5	敏感性分析结果
gray_plan.json	阶段6	灰度上线计划
monitoring_plan.csv	阶段6	监控指标与预警阈值
iteration_plan.md	阶段6	迭代学习回路计划
confidence_evidence.csv	阶段7	置信证据表
decision_log.csv	全程	决策日志
strategy_summary.md	阶段7	策略总结报告
禁止事项
不得使用机器学习模型：冷启动阶段禁止使用 scikit-learn、xgboost、lightgbm 等建模工具，所有规则必须基于业务经验或简单统计（分位数、覆盖率）。

不得跳过灰度直接全量上线：任何规则在未经灰度验证前，不得直接应用于全量流量。灰度比例不得低于1%（建议5%）。

不得在对照组不施加任何风控规则：对照组必须应用基本的合规与反欺诈规则，确保风险底线。

不得仅凭单次覆盖率或分位数设定阈值：所有规则阈值必须有业务解释或外部对标依据，并记录在 business_rationale 中。

不得依赖未经审计的外部数据：外部数据必须完成可得性审计（阶段1），且覆盖率低于70%的字段不得作为自动拒绝规则的唯一依据，可降级为人工审核参考或观察。

不得使用贷后字段或人工审批结果：严格排除任何在审批时点不可得的字段（如逾期状态、催收记录、放款后行为）。

不得进行无假设的模拟：前置估计必须基于显式的假设坏账率和 lift 倍数假设，并必须在 confidence_evidence.csv 中记录这些假设。必须包含悲观/中性/乐观的敏感性分析。

不得隐藏不利结果：敏感性分析必须包含坏账率假设变动±20%的场景，若策略在悲观假设下通过坏账率超过业务容忍度，必须在总结中明确风险提示。

不得省略证据日志：每条规则、每个阈值设定、每个策略组合决策必须记录到 decision_log.csv，缺失证据的规则不得进入灰度。

不得在未完成字段审计时进入规则设计：阶段1的字段审计是强制前置条件，未完成不得进入阶段2。

不得忽视过程指标监控：灰度期间必须每日监控各规则命中率和三方数据源覆盖率，问题是累积爆发的，不能只看最终的逾期率。

灰度回滚不能仅靠人工判断：必须有预设的、基于指标的硬性回滚触发条件，并记录在 gray_plan.json 中。
