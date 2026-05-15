#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_report.py — generate strategy_summary.md from run artifacts.

Usage: python3 scripts/render_report.py --output-dir runs/my_run
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pandas as pd
from lib.io_utils import now_text


def load_csv_safe(path, n=None):
    try:
        return pd.read_csv(path, nrows=n)
    except Exception:
        return pd.DataFrame()


def load_json_safe(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def render_report(output_dir):
    out = output_dir

    # ---- helpers ----
    def p(path):
        return os.path.join(out, path)

    # Load artifacts
    run_cfg   = load_json_safe(p('run_config.json'))
    env       = load_json_safe(p('environment.json'))
    profile   = load_csv_safe(p('sample_profile.csv'))
    split_log = load_csv_safe(p('sample_split_log.csv'))
    field_audit = load_csv_safe(p('field_audit.csv'))
    leakage   = load_csv_safe(p('leakage_audit.csv'))
    dq        = load_csv_safe(p('data_quality.csv'))
    feat_qual = load_csv_safe(p('feature_quality.csv'))
    psi_table = load_csv_safe(p('psi_table.csv'))
    mono      = load_csv_safe(p('monotonicity_check.csv'))
    drop_df   = load_csv_safe(p('feature_drop_reason.csv'))
    sv_rules  = load_csv_safe(p('single_rule_candidates.csv'))
    sv_eval   = load_csv_safe(p('single_var_rule_eval.csv'))
    dt_rules  = load_csv_safe(p('decision_tree_rules.csv'))
    combo     = load_csv_safe(p('rule_combination_candidates.csv'))
    strat_rules = load_csv_safe(p('strategy_rules.csv'))
    rule_sim  = load_csv_safe(p('rule_simulation.csv'))
    wf_comp   = load_csv_safe(p('waterfall_comparison.csv'))
    evidence  = load_csv_safe(p('confidence_evidence.csv'))
    monitor   = load_csv_safe(p('monitoring_plan.csv'))

    run_id = run_cfg.get('run_id', os.path.basename(out))
    target = run_cfg.get('target', '—')

    lines = [
        '# 信贷风控策略分析报告',
        '',
        '> 生成时间：%s  run_id: `%s`' % (now_text(), run_id),
        '',
    ]

    # 1. 样本口径
    lines += ['## 1. 样本口径', '']
    lines.append('- **目标变量**: `%s` (1=bad, 0=good)' % target)
    if run_cfg.get('time_col'):
        lines.append('- **时间列**: `%s`' % run_cfg['time_col'])
    if not profile.empty:
        all_row = profile[profile['segment'] == 'ALL']
        if len(all_row):
            lines.append('- **全量样本**: %d 行，坏账率 %.2f%%' % (
                int(all_row.iloc[0]['sample_count']),
                float(all_row.iloc[0]['bad_rate']) * 100,
            ))
    if not split_log.empty:
        lines.append('')
        lines.append('| 样本集 | 样本数 | 坏账率 | 切分方式 |')
        lines.append('|---|---|---|---|')
        for _, row in split_log.iterrows():
            lines.append('| %s | %d | %.2f%% | %s |' % (
                row['sample_type'], int(row['sample_count']),
                float(row['bad_rate']) * 100, row['split_method'],
            ))
    lines.append('')

    # 2. 字段审计
    lines += ['## 2. 字段审计结论', '']
    if not leakage.empty:
        lines.append('**泄露/风险字段（已剔除）：**')
        lines.append('')
        lines.append('| 字段 | 类型 | 关键词命中 |')
        lines.append('|---|---|---|')
        for _, row in leakage.head(20).iterrows():
            lines.append('| %s | %s | %s |' % (
                row.get('feature', ''), row.get('leakage_flag', ''),
                row.get('keyword_hit', ''),
            ))
    else:
        lines.append('- 无泄露字段。')
    lines.append('')

    # 3. 数据质量
    lines += ['## 3. 数据质量结论', '']
    if not dq.empty:
        total_feat = len(dq)
        constant = int((dq['is_constant'] == True).sum())  # noqa: E712
        high_miss = int((dq['missing_rate'] >= 0.9).sum())
        lines.append('- 候选变量: %d 个' % total_feat)
        lines.append('- 常量变量剔除: %d 个' % constant)
        lines.append('- 缺失率≥90%%剔除: %d 个' % high_miss)
    if not drop_df.empty:
        drop_summary = drop_df.groupby('drop_stage').size().reset_index(name='count')
        lines.append('')
        for _, row in drop_summary.iterrows():
            lines.append('- `%s`: %d 个' % (row['drop_stage'], row['count']))
    lines.append('')

    # 4. 变量有效性
    lines += ['## 4. 变量有效性（TOP 15）', '']
    if not feat_qual.empty:
        top_feats = feat_qual.head(15)
        lines.append('| 变量 | IV | KS | AUC |')
        lines.append('|---|---|---|---|')
        for _, row in top_feats.iterrows():
            lines.append('| %s | %.4f | %.4f | %.4f |' % (
                row['feature'], float(row['iv']),
                float(row['ks']) if pd.notna(row['ks']) else 0.0,
                float(row['auc']) if pd.notna(row['auc']) else 0.0,
            ))
    if not psi_table.empty:
        unstable = psi_table[psi_table['psi_level'] == 'unstable']
        if len(unstable):
            lines.append('')
            lines.append('**PSI 不稳定变量（已剔除）：**')
            for _, row in unstable.iterrows():
                lines.append('- `%s` PSI=%.4f' % (row['feature'], float(row['train_oot_psi'])))
    lines.append('')

    # 5. 单变量规则
    lines += ['## 5. 单变量候选规则', '']
    if not sv_rules.empty:
        top_sv = sv_rules[sv_rules['lift'] >= 1.5].head(10)
        lines.append('| rule_id | 变量 | 分箱 | lift | bad_rate | hit_rate |')
        lines.append('|---|---|---|---|---|---|')
        for _, row in top_sv.iterrows():
            lines.append('| %s | %s | %s | %.3f | %.2f%% | %.2f%% |' % (
                row['rule_id'], row.get('feature', ''),
                row.get('bin_label', ''), float(row['lift']),
                float(row['bad_rate']) * 100, float(row['hit_rate']) * 100,
            ))
    lines.append('')

    # 6. 组合规则
    lines += ['## 6. 多规则组合候选', '']
    if not combo.empty:
        top_combo = combo.head(5)
        lines.append('| rule_id | 组合规则 | lift | bad_rate | hit_rate |')
        lines.append('|---|---|---|---|---|')
        for _, row in top_combo.iterrows():
            lines.append('| %s | %s | %.3f | %.2f%% | %.2f%% |' % (
                row.get('rule_id', ''), row.get('combo_rule_ids', ''),
                float(row['lift']),
                float(row.get('hit_bad_rate', row.get('bad_rate', 0))) * 100,
                float(row['hit_rate']) * 100,
            ))
    else:
        lines.append('- 无满足阈值的组合规则。')
    lines.append('')

    # 7. 决策树规则
    lines += ['## 7. 决策树候选规则', '']
    if not dt_rules.empty:
        high = dt_rules[dt_rules.get('confidence', pd.Series(dtype=str)) == 'HIGH']
        lines.append('- 总规则: %d 条，HIGH 置信: %d 条' % (len(dt_rules), len(high)))
        top_dt = dt_rules.head(5)
        lines.append('')
        lines.append('| rule_id | 规则描述 | lift | confidence |')
        lines.append('|---|---|---|---|')
        for _, row in top_dt.iterrows():
            lines.append('| %s | %s | %.3f | %s |' % (
                row['rule_id'],
                str(row.get('rule_readable', ''))[:60],
                float(row['lift']),
                row.get('confidence', ''),
            ))
    lines.append('')

    # 8. 瀑布流
    lines += ['## 8. 瀑布流评估', '']
    if not wf_comp.empty:
        for seg in ['train', 'oot']:
            seg_wf = wf_comp[wf_comp['segment'] == seg] if 'segment' in wf_comp.columns else pd.DataFrame()
            if not seg_wf.empty:
                lines.append('**%s**' % seg)
                lines.append('')
                lines.append('| 步骤 | 规则 | 增量命中率 | 增量坏样本捕获率 |')
                lines.append('|---|---|---|---|')
                for _, row in seg_wf.iterrows():
                    lines.append('| %d | %s | %.2f%% | %.2f%% |' % (
                        int(row['waterfall_step']),
                        row['added_rule_id'],
                        float(row.get('incremental_hit_rate', 0)) * 100,
                        float(row.get('incremental_captured_bad_rate', 0)) * 100,
                    ))
                lines.append('')

    # 9. 策略模拟
    lines += ['## 9. 策略模拟', '']
    if not rule_sim.empty:
        train_sim = rule_sim[rule_sim['segment'] == 'train']
        oot_sim = rule_sim[rule_sim['segment'] == 'oot']
        lines.append('| rule_id | segment | lift | bad_rate | pass_bad_rate |')
        lines.append('|---|---|---|---|---|')
        for seg_df in [train_sim, oot_sim]:
            for _, row in seg_df.head(5).iterrows():
                lines.append('| %s | %s | %.3f | %.2f%% | %.2f%% |' % (
                    row['rule_id'], row['segment'],
                    float(row.get('lift', 0)),
                    float(row.get('hit_bad_rate', 0)) * 100,
                    float(row.get('pass_bad_rate', 0)) * 100,
                ))
    lines.append('')

    # 10. 上线建议
    lines += ['## 10. 上线建议', '']
    if not evidence.empty:
        high_conf = evidence[evidence['confidence'] == 'HIGH']
        lines.append('**HIGH 置信度证据（可上线规则）：**')
        if len(high_conf):
            for obj_id in high_conf['object_id'].unique():
                ev_rows = evidence[
                    (evidence['object_id'] == obj_id) &
                    (evidence['confidence'] == 'HIGH')
                ]
                lines.append('')
                lines.append('- `%s`' % obj_id)
                for _, row in ev_rows.iterrows():
                    lines.append(
                        '  - %s: train=%.4f test=%.4f oot=%.4f (evidence_id: `%s`)'
                        % (
                            row['metric_name'],
                            float(row['train_value']),
                            float(row['test_value']),
                            float(row['oot_value']),
                            row['evidence_id'],
                        )
                    )
        else:
            lines.append('- 无 HIGH 置信度规则；建议灰度观察后评估。')
    lines.append('')

    # 11. 监控计划
    lines += ['## 11. 监控计划', '']
    if not monitor.empty:
        rules_in_plan = monitor['rule_id'].unique().tolist()
        lines.append('监控规则：%s' % ', '.join(['`%s`' % r for r in rules_in_plan]))
        lines.append('')
        lines.append('| rule_id | 指标 | 频率 | 预警规则 |')
        lines.append('|---|---|---|---|')
        for _, row in monitor.drop_duplicates(
            subset=['rule_id', 'metric']
        ).head(20).iterrows():
            lines.append('| %s | %s | %s | %s |' % (
                row['rule_id'], row['metric'],
                row['frequency'], row['alert_rule'],
            ))
    lines.append('')

    # 12. 风险提示
    lines += [
        '## 12. 风险提示',
        '',
        '- 本报告基于历史样本，模型/规则可能不适用于样本期外的客群或渠道变化。',
        '- 请结合字段审计结论，确认变量在上线时可稳定供应。',
        '- 如缺乏 OOT 样本，跨期验证结论存在局限，建议上线后加密监控频率。',
        '',
    ]

    report_path = os.path.join(out, 'strategy_summary.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('[OK] strategy_summary.md written to:', report_path)
    return report_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    render_report(args.output_dir)


if __name__ == '__main__':
    main()
