\set ON_ERROR_STOP on

do $$
declare
  v_exp bigint;
  v_cutoff timestamptz;
  v_rows integer;
  v_bad_decision integer;
  v_bad_numeric integer;
  v_bad_gaps integer;
begin
  select id into v_exp
  from public.oracle_v6_experiments
  where model_family='COUNT_NULL_MODEL'
    and model_version='FORMAL_COUNT_NULL_V1'
    and invalidated_at is null
  order by created_at desc,id desc limit 1;

  select evaluation_as_of into v_cutoff
  from public.oracle_v6_evaluation_runs
  where experiment_id=v_exp
  order by evaluation_as_of desc,id desc limit 1;

  if v_exp is null or v_cutoff is null then
    raise exception 'V6 DECISION FAIL: no current evaluation clock';
  end if;

  select count(*) into v_rows
  from public.oracle_v6_decisions
  where model_version='DECISION_PREREQUISITE_GATE_V1' and as_of=v_cutoff;

  select count(*) into v_bad_decision
  from public.oracle_v6_decisions
  where model_version='DECISION_PREREQUISITE_GATE_V1' and as_of=v_cutoff and decision<>'NO_ACTION';

  select count(*) into v_bad_numeric
  from public.oracle_v6_decisions
  where model_version='DECISION_PREREQUISITE_GATE_V1' and as_of=v_cutoff
    and (p_structural is not null or p_bottleneck is not null or p_economic_capture is not null
      or p_fundamentals_exceed_expectations is not null or expected_residual_return is not null);

  select count(*) into v_bad_gaps
  from public.oracle_v6_decisions
  where model_version='DECISION_PREREQUISITE_GATE_V1' and as_of=v_cutoff
    and jsonb_array_length(data_gaps)<1;

  if v_rows=0 then raise exception 'V6 DECISION FAIL: no current NO_ACTION rows'; end if;
  if v_bad_decision<>0 then raise exception 'V6 DECISION FAIL: % current rows are actionable',v_bad_decision; end if;
  if v_bad_numeric<>0 then raise exception 'V6 DECISION FAIL: % current rows contain uncalibrated numeric outputs',v_bad_numeric; end if;
  if v_bad_gaps<>0 then raise exception 'V6 DECISION FAIL: % current rows missing data gaps',v_bad_gaps; end if;
end $$;

select as_of,decision,count(*) rows
from public.oracle_v6_decisions
where model_version='DECISION_PREREQUISITE_GATE_V1'
  and as_of=(select max(evaluation_as_of) from public.oracle_v6_evaluation_runs)
group by as_of,decision;
