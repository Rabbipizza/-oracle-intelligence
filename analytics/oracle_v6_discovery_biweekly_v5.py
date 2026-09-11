#!/usr/bin/env python3
"""ORACLE V6 Discovery V5: semantic concepts + biweekly acceleration.

Rationale: ORACLE is not HFT. A one-week observation is too sparse for a
trend-acceleration detector. V5 keeps 104 weeks of PRE-TEST history but groups
it into 52 non-overlapping 2-week bins, and compares a 2-week test block to
that historical null. No future data enters the test. Sequential alpha and BH
remain unchanged in base.run().
"""
from __future__ import annotations
import json, math, os
from collections import defaultdict
from datetime import timedelta
from dataclasses import dataclass
from scipy.stats import chi2, nbinom, poisson
import oracle_v6_simulated_historical_nulls as base
import oracle_v6_discovery_semantic_v3 as sem

MODEL_VERSION='FORMAL_COUNT_NULL_BIWEEKLY_V1_SIMULATED_DISCOVERY_V5'
EXTRACTION_VERSION='ORACLE_V6_DISCOVERY_BIWEEKLY_V5'
FAMILY_RULE='SEMANTIC_PRETEST_MIN3_DOCS_MIN2_BINS_52x2W'
TRAIN_WEEKS=104
BIN_WEEKS=2
N_BINS=52
MIN_TRAIN_DOCS=3
MIN_ACTIVE_BINS=2

@dataclass(frozen=True)
class Fit:
    family:str; expected:float; variance:float; dispersion:float
    p_value:float; z_score:float; diagnostics:dict

def _sample_variance(xs,mean):
    return 0.0 if len(xs)<2 else sum((x-mean)**2 for x in xs)/(len(xs)-1)

def fit_bins(train,observed):
    n=len(train)
    if n!=N_BINS: raise ValueError(f'expected {N_BINS} biweekly bins, got {n}')
    total=int(sum(train)); mean=total/n; var=_sample_variance(train,mean)
    zero=sum(1 for x in train if x==0)/n
    if mean>0:
        disp_idx=(n-1)*var/mean; disp_p=float(chi2.sf(disp_idx,n-1))
    else:
        disp_idx=0.0; disp_p=1.0
    if total<base.SPARSE_TOTAL_THRESHOLD:
        a=base.PRIOR_SHAPE+total; b=base.PRIOR_RATE+n
        expected=a/b; pred=expected+a/(b*b); prob=b/(b+1.0)
        p=float(nbinom.sf(observed-1,a,prob)) if observed>0 else 1.0
        fam='GAMMA_POISSON_SPARSE_52x2W'; dispersion=pred/max(expected,1e-12)
        extra={'posterior_shape':a,'posterior_rate':b}
    elif var>mean and disp_p<base.DISPERSION_ALPHA:
        alpha=max((var-mean)/max(mean*mean,1e-12),1e-10)
        size=1.0/alpha; prob=size/(size+mean)
        expected=mean; pred=mean+alpha*mean*mean
        p=float(nbinom.sf(observed-1,size,prob)) if observed>0 else 1.0
        fam='NEGATIVE_BINOMIAL_52x2W'; dispersion=pred/max(expected,1e-12)
        extra={'nb_alpha':alpha,'nb_size':size,'nb_probability':prob}
    else:
        expected=mean; pred=max(mean,1e-12)
        p=float(poisson.sf(observed-1,mean)) if observed>0 else 1.0
        fam='POISSON_52x2W'; dispersion=1.0; extra={}
    p=min(1.0,max(1e-300,p)); z=(observed-expected)/math.sqrt(max(pred,1e-12))
    return Fit(fam,float(expected),float(pred),float(dispersion),p,float(z),{
        'formal_p_value':True,'point_in_time':True,'strict_pre_test_training':True,
        'training_bins':n,'bin_weeks':BIN_WEEKS,'training_weeks':TRAIN_WEEKS,
        'training_total':total,'training_mean_per_2w':mean,'training_variance':var,
        'zero_fraction':zero,'dispersion_test_p':disp_p,'dispersion_index':disp_idx,
        'model_selection_rule':'sparse_gamma_poisson_else_dispersion_nb_else_poisson',**extra})

def family_at(occ,cutoff_dt,test_week):
    test_block_start=test_week-timedelta(weeks=1)
    train_start=test_block_start-timedelta(weeks=TRAIN_WEEKS)
    test_end=min(test_week+timedelta(days=6),cutoff_dt.date())
    by=defaultdict(lambda:defaultdict(set))
    for event,term,doc_id,avail in occ:
        if avail>cutoff_dt or event<train_start or event>test_end: continue
        w=event-timedelta(days=event.weekday()); by[term][w].add(doc_id)
    train_weeks=[train_start+timedelta(weeks=i) for i in range(TRAIN_WEEKS)]
    payload=[]
    for key,h in sorted(by.items()):
        weekly=[len(h.get(w,set())) for w in train_weeks]
        bins=[weekly[i]+weekly[i+1] for i in range(0,TRAIN_WEEKS,2)]
        train_docs=sum(bins); active=sum(1 for x in bins if x>0)
        if train_docs<MIN_TRAIN_DOCS or active<MIN_ACTIVE_BINS: continue
        observed=len(h.get(test_block_start,set()))+len(h.get(test_week,set()))
        fit=fit_bins(bins,observed)
        payload.append({
            'signal_key':key,'null_family':fit.family,'observed_value':observed,
            'expected_value':fit.expected,'dispersion':fit.dispersion,
            'surprise_z':fit.z_score,'p_value':fit.p_value,
            'training_window':{
                'weeks':TRAIN_WEEKS,'bins':N_BINS,'bin_weeks':BIN_WEEKS,
                'train_start':train_start.isoformat(),
                'train_end':(test_block_start-timedelta(weeks=1)).isoformat(),
                'test_block_start':test_block_start.isoformat(),
                'test_week':test_week.isoformat(),'test_end':test_end.isoformat(),
                'cutoff':cutoff_dt.isoformat(),'clock_mode':'simulated_historical',
                'family_rule':FAMILY_RULE,'min_train_docs':MIN_TRAIN_DOCS,
                'min_active_bins':MIN_ACTIVE_BINS,'train_docs':train_docs,
                'active_bins':active},
            'diagnostics':{**fit.diagnostics,'recomputed_at_cutoff':True,
                'all_history_baseline_reused':False,'extraction_version':EXTRACTION_VERSION,
                'family_rule':FAMILY_RULE,'family_membership_depends_on_test_observation':False,
                'semantic_candidate_gate':True,'biweekly_acceleration_test':True}
        })
    return payload

def run(db_url):
    base.lemma=sem.lemma; base.terms=sem.terms; base.family_at=family_at
    base.MODEL_VERSION=MODEL_VERSION; base.EXTRACTION_VERSION=EXTRACTION_VERSION
    base.FAMILY_RULE=FAMILY_RULE
    r=base.run(db_url)
    r.update({'semantic_candidate_gate':True,'biweekly_acceleration_test':True,
              'bin_weeks':2,'training_bins':52,'inference_thresholds_changed':False})
    return r

if __name__=='__main__':
    print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
