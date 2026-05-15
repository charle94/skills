# -*- coding: utf-8 -*-
"""combo_rules.py — multi-rule OR combination mining (stage 5.2)."""

from itertools import combinations as _combinations

import pandas as pd
from .simulation import simulate_rule


def mine_rule_combinations(df, candidate_rule_ids, rule_masks, target,
                            max_combo_size=2, top_n=20,
                            min_hit_rate=0.01, min_bad_count=10, min_lift=1.2):
    """Enumerate OR combinations of top_n candidate rules up to max_combo_size.

    Only rules that already passed filter_rule_candidates (stage 5.1 or tree)
    should be passed in as candidate_rule_ids.  This function does not re-apply
    single-rule quality filters — it applies the combo-level thresholds.

    Returns rule_combination_candidates.csv sorted by lift descending.
    """
    candidates = candidate_rule_ids[:top_n]
    rows = []
    counter = [0]
    for combo_size in range(2, max_combo_size + 1):
        for combo in _combinations(candidates, combo_size):
            counter[0] += 1
            combined = pd.Series(False, index=df.index)
            for rid in combo:
                if rid in rule_masks:
                    combined = combined | rule_masks[rid]
            sim = simulate_rule(
                df, combined, target,
                rule_id='COMBO_%05d' % counter[0], segment='ALL',
            )
            sim['combo_rule_ids'] = ','.join(combo)
            sim['combo_size'] = combo_size
            rows.append(sim)
    result = pd.DataFrame(rows)
    if len(result):
        result = result[
            (result['hit_rate'] >= min_hit_rate) &
            (result['hit_bad_count'] >= min_bad_count) &
            (result['lift'] >= min_lift)
        ].sort_values(
            ['lift', 'hit_bad_rate'], ascending=[False, False]
        ).reset_index(drop=True)
    return result
