\set ON_ERROR_STOP on
DO $$
DECLARE
  latest_eval timestamptz;
  snapshot_rows int;
  trend_rows int;
  bad_rows int;
BEGIN
  select max(evaluation_as_of) into latest_eval from public.oracle_v6_evaluation_runs;
  select count(*) into snapshot_rows from public.oracle_v6_demographic_snapshots where available_at<=latest_eval;
  select count(*) into trend_rows from public.oracle_v6_demographic_trends where evaluation_as_of=latest_eval and trend_family='DEMOGRAPHY';
  select count(*) into bad_rows from public.oracle_v6_demographic_trends where evaluation_as_of=latest_eval and (trend_family<>'DEMOGRAPHY' or status<>'STRUCTURAL_TREND_LIVE_CONTEXT');
  if bad_rows<>0 then raise exception 'V6 DEMOGRAPHY TREND FAIL: invalid family/status rows=%',bad_rows; end if;
  if snapshot_rows>0 and trend_rows=0 then raise exception 'V6 DEMOGRAPHY TREND FAIL: demographic observations exist but no demographic trend was materialized'; end if;
END $$;
