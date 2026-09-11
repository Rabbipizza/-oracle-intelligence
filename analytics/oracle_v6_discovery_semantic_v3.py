#!/usr/bin/env python3
"""ORACLE V6 Discovery Semantic V3.

Keeps the validated P0-9 point-in-time reconstruction, family freezing,
formal count nulls, BH correction and sequential alpha budget unchanged.
Only the document-local candidate extraction is tightened before testing:
1) fix the naive final-s lemmatizer corruption of -ous/-us/-is words;
2) reject academic/boilerplate vocabulary that is not an investable concept;
3) keep technical multi-word concepts and technical unigrams.

This is intentionally upstream of inference. It does NOT loosen p-values,
BH/FDR thresholds or the sequential alpha budget.
"""
from __future__ import annotations
import re
import oracle_v6_simulated_historical_nulls as base

MODEL_VERSION='FORMAL_COUNT_NULL_V1_SIMULATED_DISCOVERY_V3'
EXTRACTION_VERSION='ORACLE_V6_DISCOVERY_SEMANTIC_V3'
FAMILY_RULE='SEMANTIC_ELIGIBLE_TERM_SEEN_IN_104W_PRETEST_TRAINING'

# Domain-agnostic scholarly boilerplate. These tokens describe papers/methods,
# not economic/technological phenomena. The list is fixed before evaluation.
ACADEMIC_GENERIC=set('''
abstract academic accuracy accurate analysis analytical application applications
approach approaches assessment benchmark benchmarks case cases challenge challenges
comparison comparisons comprehensive conclusion conclusions dataset datasets
empirical evaluation evaluations evidence experiment experiments experimental
framework frameworks general generalized heterogeneity heterogeneous improvement
improvements investigation investigations literature method methods methodology
modern novel objective objectives overview paper papers performance perspective
perspectives practical proposed qualitative quantitative result results review
reviews retrospective robust robustness sample samples simulation simulations
spike statistical strategy strategies study studies survey surveys systematic
technique techniques test tests theoretical theory validation validations
'''.split())

# Additional broad words that can be legitimate in prose but are too ambiguous
# as standalone investment concepts. They remain allowed inside technical phrases.
AMBIGUOUS_UNIGRAM=set('''
advanced architecture capacity computing control design development digital
efficient energy experimental future generation global growth hardware intelligent
market memory network networks optimization platform power process production
scale scaling software solution solutions system systems technology technologies
training transformation use value virtual
'''.split())


def lemma(v:str)->str:
    x=v.lower().strip("+.#'-")
    if x in base.VERBS:
        return base.VERBS[x]
    if len(x)>5 and x.endswith('ies'):
        return x[:-3]+'y'
    if len(x)>5 and re.search(r'(ches|shes|xes|zes)$',x):
        return x[:-2]
    if len(x)>5 and x.endswith('ses') and not x.endswith('sses'):
        return x[:-1]
    # Do not corrupt adjectives/nouns such as heterogeneous, continuous,
    # status, analysis. The V2 rule blindly removed every final s.
    if len(x)>4 and x.endswith('s') and not x.endswith(('ss','ous','us','is')):
        return x[:-1]
    return x


def _label(v:str)->str:
    return ' '.join(x.upper() if re.match(r'^[a-z]{1,4}\d|\d',x)
                    else x[:1].upper()+x[1:] for x in v.split())


def terms(title:str):
    ts=[lemma(x) for x in base.normalized(title).split()]
    ts=[x for x in ts if len(x)>2 and x not in base.STOP
        and not re.match(r'^(\d+|[a-f0-9]{8,})$',x)]
    out=set()

    # Standalone terms need to be plausibly technical rather than scholarly
    # boilerplate. We deliberately do not use future returns or labels here.
    for token in ts:
        if len(token)<5:
            continue
        if token in base.GENERIC or token in ACADEMIC_GENERIC or token in AMBIGUOUS_UNIGRAM:
            continue
        out.add(_label(token))

    # Multi-word candidates preserve context. Require at least one informative
    # token after generic/academic filtering so phrases like "experimental
    # results" do not enter the statistical family.
    for n in (2,3):
        for i in range(0,len(ts)-n+1):
            a=ts[i:i+n]
            informative=[x for x in a if x not in base.GENERIC
                         and x not in ACADEMIC_GENERIC]
            if not informative:
                continue
            # Reject phrases composed only of ambiguous broad tokens.
            if all(x in AMBIGUOUS_UNIGRAM for x in informative):
                continue
            v=' '.join(a)
            if 8<=len(v)<=72:
                out.add(_label(v))
            if len(out)>=36:
                break
    return sorted(out)[:36]


def run(db_url:str):
    base.lemma=lemma
    base.terms=terms
    base.MODEL_VERSION=MODEL_VERSION
    base.EXTRACTION_VERSION=EXTRACTION_VERSION
    base.FAMILY_RULE=FAMILY_RULE
    result=base.run(db_url)
    result['semantic_candidate_gate']=True
    result['semantic_gate_version']=EXTRACTION_VERSION
    result['inference_thresholds_changed']=False
    return result


if __name__=='__main__':
    import json, os
    print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
