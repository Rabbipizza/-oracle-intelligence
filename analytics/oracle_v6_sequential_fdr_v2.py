#!/usr/bin/env python3
import json, os
import oracle_v6_sequential_fdr as base

FORMAL_MODEL_VERSION='FORMAL_COUNT_NULL_V2_PRETEST_FAMILY'
base.FORMAL_MODEL_VERSION=FORMAL_MODEL_VERSION

if __name__=='__main__':
    print(json.dumps(base.run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
