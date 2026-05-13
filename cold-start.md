---
name: cold-start-credit-risk
description: 基于 pandas 和 numpy 的信贷风控冷启动方案。适用于无历史表现样本的新产品/新市场/新渠道场景，通过专家规则、三方数据评估、灰度上线与迭代学习快速构建初始风控策略。
allowed-tools: Bash(python3:*) Bash(python:*) Bash(pip:*) Bash(pip3:*)
---

# Cold-Start Credit Risk Strategy

## 目标与适用场景

冷启动的核心挑战：无真实表现数据与风控决策必须立即生效之间的矛盾。策略从"数据驱动"切换为"假设驱动"，通过灰度下快速迭代验证假设，逐步向数据驱动演进。

**适用场景：**
- 新国家/新市场现金贷产品冷启动
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
| `loan_tenor` | 贷款期限 | 7–30 天 |
| `expected_bad_rate` | 预期坏账率假设（行业对标或业务目标） | 0.08 |
| `external_data_sources` | 可用三方数据列表 | ["bureau","blacklist","telco","device"] |
| `gray_traffic_ratio` | 灰度流量比例 | 0.05 |
| `observation_window` | 表现观察窗口（预设，即使无数据） | FPD30 |
| `id_col` | 客户唯一标识字段 | "user_id" |
| `time_col` | 申请时间字段 | "apply_time" |
| `feature_cols` | 候选特征字段列表 | [...] |
| `exclude_cols` | 明确不可用字段 | [...] |

## 分阶段执行框架

每阶段产出对应文件，关键决策写入 `decision_log.csv`。

| 阶段 | 目标 | 核心产出 | 进入下一阶段条件 |
|------|------|----------|------------------|
| 0. 业务配置 | 固化口径、假设、成功标准 | `business_config.json`, `environment.json` | 所有口径已确认 |
| 1. 字段审计 | 排除贷后/结果/泄露字段 | `field_audit.csv` | 无泄露风险 |
| 2. 覆盖率分析 | 三方数据覆盖率与分布质量 | `coverage_report.csv` | 关键字段覆盖率 ≥70% |
| 3. 准入与反欺诈硬拒 | 黑名单/欺诈信号/合规强制规则（HIGH置信） | `hard_reject_rules.csv` | 所有硬拒规则有明确法规或业务依据 |
| 4. 专家规则设计 | 单变量阈值与规则评分卡 | `expert_rules_raw.csv`, `rule_scorecard.csv` | 所有规则有业务解释和阈值 |
| 5. 规则效果前置估计 | 基于假设坏账率估计效果（含敏感性） | `rule_simulation.csv`, `sensitivity_analysis.csv` | 效果在业务可接受范围，或已识别需调整规则 |
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

**注意拒绝推断偏差（Reject Inference）：** 冷启动阶段灰度通过的样本并非总体随机样本，灰度结束后的首版模型开发必须评估拒绝偏差，不能直接将灰度期表现样本视为全量代表。

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
                          expected_bad_rate, external_data_sources,
                          gray_traffic_ratio=0.05, observation_window='FPD30',
                          id_col='id', time_col='apply_time',
                          feature_cols=None, exclude_cols=None):
    return {
        'product_type': product_type,
        'target_market': target_market,
        'loan_amount_range': loan_amount_range,
        'loan_tenor': loan_tenor,
        'expected_bad_rate': expected_bad_rate,
        'external_data_sources': external_data_sources,
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
    'overdue', 'dpd', 'due_date', 'm0', 'm1', 'm2', 'ever_30',
    'collection', 'write_off', 'repay', 'repayment', 'settle',
    'default', 'delinquency',
    '逾期', '催收', '还款', '核销', '坏账', '违约',
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
    """计算每个字段的覆盖率、唯一值数、Top1集中度，并标记是否可作为硬拒依据。"""
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
    构建硬拒规则：黑名单命中、合规限制、欺诈信号。
    这些规则为 HIGH 置信，必须在所有其他规则之前执行。

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
            'confidence': 'HIGH',
            'business_rationale': '黑名单/欺诈信号命中，硬性拒绝',
            'source': 'blacklist',
        })
    for r in (compliance_rules or []):
        rules.append({**r, 'action': 'reject', 'confidence': 'HIGH'})
    return pd.DataFrame(rules) if rules else pd.DataFrame(
        columns=['rule_id', 'feature', 'direction', 'threshold',
                 'action', 'confidence', 'business_rationale', 'source'])


# ---------- 阶段 4：专家规则设计 ----------

def apply_rule(df, rule):
    """对 DataFrame 应用单条规则，返回布尔掩码（True=命中/拒绝）。NaN 视为未命中。"""
    feature = rule['feature']
    direction = rule['direction']
    threshold = rule['threshold']
    if feature not in df.columns:
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
    # NaN is treated as non-hit (False): missing data never triggers a reject rule.
    # Callers that require explicit handling of missing values should impute before
    # calling this function or track coverage separately via coverage_report().
    return ops[direction].fillna(False)


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
    对申请人进行规则评分。
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
    result = pd.DataFrame({'rule_score': scores, 'rule_hit_count': hit_counts})
    return result


# ---------- 阶段 5：规则效果前置估计 ----------

def simulate_rule_no_y(df, mask, assumed_base_bad_rate,
                       hit_bad_rate_multiplier=2.0, pass_bad_rate_multiplier=0.85,
                       rule_id='', segment='ALL'):
    """
    基于分段假设的前置模拟（无 Y 标签）。
    命中人群坏账率 = base × hit_multiplier（被拒群体风险更高）
    通过人群坏账率 = base × pass_multiplier（通过群体风险更低）
    captured_bad_ratio: 规则命中的坏账占总假设坏账比例（规则区分能力代理指标）
    bad_rate_improvement: 策略通过后坏账率相对基准的下降幅度
    """
    total = len(df)
    hit_count = int(mask.sum())
    pass_count = total - hit_count
    hit_bad_rate = min(assumed_base_bad_rate * hit_bad_rate_multiplier, 1.0)
    pass_bad_rate = min(assumed_base_bad_rate * pass_bad_rate_multiplier, 1.0)
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
    示例：{'fpd7_rate': 0.15, 'hit_rate_daily_change_pct': 0.30,
           'third_party_coverage_drop': 0.20}
    """
    return {
        'gray_ratio': gray_ratio,
        'split_method': split_method,
        'random_state': random_state,
        'id_col': id_col,
        'rollback_thresholds': rollback_thresholds or {
            'fpd7_rate_hard_stop': 0.15,
            'hit_rate_daily_change_pct': 0.30,
            'third_party_coverage_drop': 0.20,
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
        # Vectorized: convert ids to strings, hash via pandas Series apply,
        # then use modulo — avoids a Python-level loop for large DataFrames.
        hashes = df[id_col].astype(str).apply(lambda x: abs(hash(x)) % 100)
        df['is_gray'] = hashes < gray_plan['gray_ratio'] * 100
    else:
        raise ValueError('split_method must be "random" or "hash"')
    return df


def build_monitoring_plan(gray_plan, observation_window='FPD30'):
    """
    生成灰度期监控计划。
    每行为一个监控指标，含预警阈值、硬停阈值与监控频率。
    """
    rb = gray_plan.get('rollback_thresholds', {})
    fpd7_stop = rb.get('fpd7_rate_hard_stop', 0.15)
    rows = [
        {'metric': 'hit_rate',
         'description': '规则命中率（日变化）',
         'frequency': 'daily',
         'warning_threshold': rb.get('hit_rate_daily_change_pct', 0.30) * 0.7,
         'hard_stop_threshold': rb.get('hit_rate_daily_change_pct', 0.30),
         'unit': 'pct_change'},
        {'metric': 'fpd7_rate',
         'description': '7日首逾率',
         'frequency': 'weekly',
         'warning_threshold': round(fpd7_stop * 0.8, 4),
         'hard_stop_threshold': fpd7_stop,
         'unit': 'rate'},
        {'metric': observation_window.lower() + '_rate',
         'description': observation_window + ' 首逾率',
         'frequency': 'monthly',
         'warning_threshold': None,
         'hard_stop_threshold': None,
         'unit': 'rate'},
        {'metric': 'third_party_coverage',
         'description': '三方数据覆盖率（日下降幅度）',
         'frequency': 'daily',
         'warning_threshold': rb.get('third_party_coverage_drop', 0.20) * 0.5,
         'hard_stop_threshold': rb.get('third_party_coverage_drop', 0.20),
         'unit': 'drop_pct'},
        {'metric': 'approval_rate',
         'description': '通过率',
         'frequency': 'daily',
         'warning_threshold': None,
         'hard_stop_threshold': None,
         'unit': 'rate'},
        {'metric': 'fraud_hit_rate',
         'description': '欺诈/黑名单命中率',
         'frequency': 'daily',
         'warning_threshold': None,
         'hard_stop_threshold': None,
         'unit': 'rate'},
    ]
    return pd.DataFrame(rows)


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


def build_strategy_summary(config, field_audit_df, rule_df, strategy_sim, gray_plan):
    """生成策略总结 Markdown 报告（所有占位符均来自实际计算结果）。"""
    keep = int((field_audit_df['decision'] == 'keep').sum()) if field_audit_df is not None else 'N/A'
    drop = int((field_audit_df['decision'] == 'drop').sum()) if field_audit_df is not None else 'N/A'
    high = int((rule_df['confidence'] == 'HIGH').sum()) if rule_df is not None else None
    medium = int((rule_df['confidence'] == 'MEDIUM').sum()) if rule_df is not None else None
    low = int((rule_df['confidence'] == 'LOW').sum()) if rule_df is not None else None
    rule_total = (high + medium + low) if high is not None else None
    fmt = lambda v: 'N/A' if v is None else v
    hit_rate = strategy_sim.get('hit_rate', 'N/A') if strategy_sim else 'N/A'
    pass_rate = strategy_sim.get('pass_rate', 'N/A') if strategy_sim else 'N/A'
    post_br = strategy_sim.get('post_strategy_bad_rate', 'N/A') if strategy_sim else 'N/A'
    lines = [
        '# 冷启动风控策略总结报告\n',
        '## 1. 业务配置',
        '- 产品类型: {}'.format(config.get('product_type', 'N/A')),
        '- 目标市场: {}'.format(config.get('target_market', 'N/A')),
        '- 预期坏账率: {}'.format(config.get('expected_bad_rate', 'N/A')),
        '- 灰度比例: {}'.format(config.get('gray_traffic_ratio', 'N/A')),
        '- 观察窗口: {}'.format(config.get('observation_window', 'N/A')),
        '',
        '## 2. 字段审计',
        '- 可用字段: {}  剔除字段: {}'.format(keep, drop),
        '',
        '## 3. 规则清单',
        '- 规则总数: {}  HIGH: {}  MEDIUM: {}  LOW: {}'.format(
            fmt(rule_total), fmt(high), fmt(medium), fmt(low)),
        '',
        '## 4. 前置估计（中性假设）',
        '- 命中率: {}  通过率: {}  通过后坏账率: {}'.format(hit_rate, pass_rate, post_br),
        '',
        '## 5. 灰度计划',
        '- 灰度比例: {}  分流方法: {}'.format(
            gray_plan.get('gray_ratio', 'N/A'), gray_plan.get('split_method', 'N/A')),
        '- 回滚阈值: {}'.format(gray_plan.get('rollback_thresholds', {})),
        '',
        '## 6. 迭代里程碑',
        '- 里程碑1: 积累1000样本后首次规则调优',
        '- 里程碑2: 积累3000样本后评估评分卡建模可行性',
        '- 里程碑3: 积累5000+样本后启动模型开发（注意评估拒绝推断偏差）',
        '',
        '## 7. 风险提示',
        '- 所有估计基于假设，无历史表现数据，实际效果可能偏离',
        '- 三方数据覆盖率可能随时间波动，需每日监控',
        '- 灰度期间需密切监控通过率、FPD7+/FPD30+ 及欺诈命中率',
        '- 灰度样本存在拒绝推断偏差，不可直接用于全量建模',
    ]
    return '\n'.join(lines)
```

## 最终交付清单

推荐输出目录 `output/cold_start/`

| 文件 | 阶段 | 说明 |
|------|------|------|
| `business_config.json` | 0 | 业务配置与口径 |
| `environment.json` | 0 | Python 环境版本 |
| `field_audit.csv` | 1 | 字段泄露审计结果 |
| `coverage_report.csv` | 2 | 三方数据覆盖率报告 |
| `hard_reject_rules.csv` | 3 | 准入与反欺诈硬拒规则 |
| `expert_rules_raw.csv` | 4 | 原始专家规则清单 |
| `rule_scorecard.csv` | 4 | 规则评分卡权重表 |
| `rule_simulation.csv` | 5 | 单规则前置估计 |
| `sensitivity_analysis.csv` | 5 | 坏账率假设敏感性分析（含±20%场景） |
| `gray_plan.json` | 6 | 灰度分流与回滚计划 |
| `monitoring_plan.csv` | 6 | 监控指标与预警阈值 |
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
10. **禁止仅凭通过率或放款量判断灰度成功**：必须同时监控早期逾期、欺诈命中率和三方数据质量。
