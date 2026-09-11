#!/usr/bin/env python3
import json, os
import oracle_v6_discovery_pipeline as base

FORMAL_MODEL_VERSION='FORMAL_COUNT_NULL_V2_PRETEST_FAMILY'
base.FORMAL_MODEL_VERSION=FORMAL_MODEL_VERSION

if __name__=='__main__':
    alpha=float(os.environ.get('ORACLE_V6_FDR_ALPHA_ALLOCATED', os.environ.get('ORACLE_V6_FDR_ALPHA','0.05')))
    r=base.run_fdr(os.environ.get('ORACLE_SUPABASE_DB_URL',''),alpha)
    print(json.dumps({'ok':True,'experiment_id':r.experiment_id,'as_of':r.as_of.isoformat(),'family_size':r.family_size,'alpha':r.alpha,'selected_count':r.selected_count,'formal_null_model_version':FORMAL_MODEL_VERSION},sort_keys=True))
