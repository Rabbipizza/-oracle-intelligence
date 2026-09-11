#!/usr/bin/env python3
"""ORACLE V6 Discovery V4: semantic + pre-test persistence gate.

The statistical machinery remains unchanged. Candidate-family membership is
based only on the 104-week PRE-TEST window. A candidate must have appeared in
at least 3 distinct source documents and in at least 2 distinct weeks before T.
This removes one-off lexical hypotheses without conditioning on N(t).
"""
from __future__ import annotations
import json, os
from collections import defaultdict
from datetime import timedelta
import oracle_v6_simulated_historical_nulls as base
import oracle_v6_discovery_semantic_v3 as sem

MODEL_VERSION='FORMAL_COUNT_NULL_V1_SIMULATED_DISCOVERY_V4'
EXTRACTION_VERSION='ORACLE_V6_DISCOVERY_PERSISTENT_V4'
FAMILY_RULE='SEMANTIC_TERM_PRETEST_MIN3_DOCS_MIN2_WEEKS_104W'
MIN_TRAIN_DOCS=3
MIN_TRAIN_WEEKS=2


def family_at(occ,cutoff_dt,test_week):
    train_start=test_week-timedelta(weeks=base.WINDOW_WEEKS)
    test_end=min(test_week+timedelta(days=6),cutoff_dt.date())
    by=defaultdict(lambda:defaultdict(set))
    for event,term,doc_id,avail in occ:
        if avail>cutoff_dt or event<train_start or event>test_end:
            continue
        w=event-timedelta(days=event.weekday())
        by[term][w].add(doc_id)
    weeks=[train_start+timedelta(weeks=i) for i in range(base.WINDOW_WEEKS)]
    payload=[]
    for key,h in sorted(by.items()):
        train=[len(h.get(w,set())) for w in weeks]
        train_docs=sum(train)
        train_weeks=sum(1 for x in train if x>0)
        # Family membership uses PRE-TEST history only. Test-week observation
        # never affects eligibility, preserving the P0-9 anti-selection rule.
        if train_docs<MIN_TRAIN_DOCS or train_weeks<MIN_TRAIN_WEEKS:
            continue
        observed=len(h.get(test_week,set()))
        fit=base._fit_count_null(train,observed)
        payload.append({
            'signal_key':key,'null_family':fit.family,'observed_value':observed,
            'expected_value':fit.expected,'dispersion':fit.dispersion,
            'surprise_z':fit.z_score,'p_value':fit.p_value,
            'training_window':{
                'weeks':base.WINDOW_WEEKS,'train_start':train_start.isoformat(),
                'train_end':(test_week-timedelta(weeks=1)).isoformat(),
                'test_week':test_week.isoformat(),'test_end':test_end.isoformat(),
                'cutoff':cutoff_dt.isoformat(),'clock_mode':'simulated_historical',
                'source_filter':'arXiv available_at_simulated<=T',
                'family_rule':FAMILY_RULE,'min_train_docs':MIN_TRAIN_DOCS,
                'min_train_weeks':MIN_TRAIN_WEEKS,
                'train_docs':train_docs,'train_active_weeks':train_weeks,
            },
            'diagnostics':{
                **fit.diagnostics,'point_in_time':True,
                'clock_mode':'simulated_historical','recomputed_at_cutoff':True,
                'all_history_baseline_reused':False,
                'extraction_version':EXTRACTION_VERSION,
                'family_rule':FAMILY_RULE,
                'family_membership_depends_on_test_observation':False,
                'pretest_persistence_gate':True,
            }
        })
    return payload


def run(db_url:str):
    base.lemma=sem.lemma
    base.terms=sem.terms
    base.family_at=family_at
    base.MODEL_VERSION=MODEL_VERSION
    base.EXTRACTION_VERSION=EXTRACTION_VERSION
    base.FAMILY_RULE=FAMILY_RULE
    result=base.run(db_url)
    result.update({
        'semantic_candidate_gate':True,
        'pretest_persistence_gate':True,
        'min_train_docs':MIN_TRAIN_DOCS,
        'min_train_weeks':MIN_TRAIN_WEEKS,
        'inference_thresholds_changed':False,
    })
    return result


if __name__=='__main__':
    print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
