-- P0-3 integration test: selected hypotheses may pass; rejected hypotheses may not.
-- The test uses a transaction and rolls back all inserted rows.

begin;

with e as (
  insert into public.oracle_v6_experiments
    (experiment_key, model_family, model_version, target_name, specification)
  values
    ('p0_3_ci_' || txid_current()::text, 'COUNT_NULL_MODEL', 'p0-3-test', 'fdr_gate_test', '{}'::jsonb)
  returning id
)
insert into public.oracle_v6_multiple_testing
  (experiment_id, hypothesis_key, raw_p_value, adjusted_p_value, method, selected, as_of, fdr_alpha, family_size)
select id, 'P0_3_SELECTED', 0.001, 0.002, 'BENJAMINI_HOCHBERG', true, '2020-01-01T00:00:00Z', 0.05, 2 from e;

insert into public.oracle_v6_multiple_testing
  (experiment_id, hypothesis_key, raw_p_value, adjusted_p_value, method, selected, as_of, fdr_alpha, family_size)
select id, 'P0_3_REJECTED', 0.50, 0.50, 'BENJAMINI_HOCHBERG', false, '2020-01-01T00:00:00Z', 0.05, 2
from public.oracle_v6_experiments
where experiment_key = 'p0_3_ci_' || txid_current()::text;

insert into public.oracle_v6_trend_probabilities
  (experiment_id, trend_key, as_of, first_detected_at, state, p_structural, model_version)
select id, 'P0_3_SELECTED', '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z', 'SIGNAL', 0.5, 'p0-3-test'
from public.oracle_v6_experiments
where experiment_key = 'p0_3_ci_' || txid_current()::text;

-- A rejected hypothesis must fail with SQLSTATE 23514. Catch and assert it.
do $$
declare
  eid bigint;
  failed_as_expected boolean := false;
begin
  select id into eid from public.oracle_v6_experiments
  where experiment_key = 'p0_3_ci_' || txid_current()::text;
  begin
    insert into public.oracle_v6_trend_probabilities
      (experiment_id, trend_key, as_of, first_detected_at, state, p_structural, model_version)
    values
      (eid, 'P0_3_REJECTED', '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z', 'SIGNAL', 0.5, 'p0-3-test');
  exception when check_violation then
    failed_as_expected := true;
  end;
  if not failed_as_expected then
    raise exception 'P0-3 failed: rejected hypothesis bypassed FDR gate';
  end if;
end $$;

rollback;
