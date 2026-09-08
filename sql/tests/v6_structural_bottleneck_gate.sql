\set ON_ERROR_STOP on

do $$
declare
  exp_id bigint;
  eval_at timestamptz;
  n integer;
  probs integer;
begin
  select id into exp_id
  from public.oracle_v6_experiments
  where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1'
    and invalidated_at is null
  order by created_at desc,id desc limit 1;

  select evaluation_as_of into eval_at
  from public.oracle_v6_evaluation_runs
  where experiment_id=exp_id
  order by evaluation_as_of desc,id desc limit 1;

  select count(*) into n
  from public.oracle_v6_structural_bottlenecks
  where experiment_id=exp_id and evaluation_as_of=eval_at;

  if n = 0 then
    raise exception 'No structural bottleneck candidates were materialized';
  end if;

  select count(*) into probs
  from public.oracle_v6_structural_bottlenecks
  where experiment_id=exp_id and evaluation_as_of=eval_at
    and structural_status='STRUCTURAL_CANDIDATE'
    and forecast_probability is not null;

  if probs <> 0 then
    raise exception 'STRUCTURAL_CANDIDATE rows must not contain forecast probabilities';
  end if;

  if exists (
    select 1 from public.oracle_v6_structural_bottlenecks
    where experiment_id=exp_id and evaluation_as_of=eval_at
      and (signal_available_at > evaluation_as_of or necessity_reason is null or derivation_rule is null)
  ) then
    raise exception 'Structural bottleneck PIT/provenance integrity failure';
  end if;
end $$;
