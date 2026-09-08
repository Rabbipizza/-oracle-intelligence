\set ON_ERROR_STOP on

do $$
declare
  v_exp bigint;
  v_cutoff timestamptz;
  v_rows integer;
  v_bad_prob integer;
  v_bad_inputs integer;
begin
  select id into v_exp from public.oracle_v6_experiments
  where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1'
    and invalidated_at is null order by created_at desc,id desc limit 1;
  select evaluation_as_of into v_cutoff from public.oracle_v6_evaluation_runs
  where experiment_id=v_exp order by evaluation_as_of desc,id desc limit 1;
  if v_cutoff is null then raise exception 'V6 REVERSE DCF FAIL: no evaluation clock'; end if;

  select count(*) into v_rows from public.oracle_v6_market_expectations
  where model_version='REVERSE_DCF_IMPLIED_FCF_GROWTH_V1' and as_of=v_cutoff;

  select count(*) into v_bad_prob from public.oracle_v6_market_expectations
  where model_version='REVERSE_DCF_IMPLIED_FCF_GROWTH_V1' and as_of=v_cutoff
    and p_fundamentals_exceed_expectations is not null;

  select count(*) into v_bad_inputs from public.oracle_v6_market_expectations
  where model_version='REVERSE_DCF_IMPLIED_FCF_GROWTH_V1' and as_of=v_cutoff
    and (not (implied_fundamentals ? 'implied_constant_fcf_cagr_5y')
      or not (implied_fundamentals ? 'enterprise_value')
      or not (reverse_dcf_assumptions ? 'discount_rate'));

  if v_bad_prob<>0 then raise exception 'V6 REVERSE DCF FAIL: % rows contain uncalibrated probabilities',v_bad_prob; end if;
  if v_bad_inputs<>0 then raise exception 'V6 REVERSE DCF FAIL: % rows missing deterministic inputs/outputs',v_bad_inputs; end if;
  -- Zero rows is allowed when complete PIT input coverage is absent or the solve is out of bounds.
end $$;

select as_of,count(*) reverse_dcf_rows
from public.oracle_v6_market_expectations
where model_version='REVERSE_DCF_IMPLIED_FCF_GROWTH_V1'
group by as_of order by as_of desc limit 5;
