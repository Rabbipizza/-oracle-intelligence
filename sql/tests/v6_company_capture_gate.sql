\set ON_ERROR_STOP on

do $$
declare
  v_exp bigint;
  v_cutoff timestamptz;
  v_rows integer;
  v_bad_prob integer;
  v_empty_evidence integer;
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
    raise exception 'V6 COMPANY CAPTURE FAIL: no active evaluation run';
  end if;

  select count(*) into v_rows
  from public.oracle_v6_company_capture
  where model_version='COMPANY_CAPTURE_EVIDENCE_GATE_V1' and as_of=v_cutoff;

  select count(*) into v_bad_prob
  from public.oracle_v6_company_capture c
  where c.model_version='COMPANY_CAPTURE_EVIDENCE_GATE_V1'
    and c.as_of=v_cutoff
    and (c.capture_probability is not null
      or c.revenue_exposure is not null
      or c.expected_incremental_revenue is not null
      or c.expected_incremental_margin is not null
      or c.pricing_power_probability is not null
      or c.deliverable_capacity_probability is not null
      or c.expected_incremental_fcf is not null
      or c.capex_required is not null);

  select count(*) into v_empty_evidence
  from public.oracle_v6_company_capture c
  where c.model_version='COMPANY_CAPTURE_EVIDENCE_GATE_V1'
    and c.as_of=v_cutoff
    and jsonb_array_length(c.evidence_ids)=0;

  if v_rows=0 then raise exception 'V6 COMPANY CAPTURE FAIL: no current evidence-supported candidates'; end if;
  if v_bad_prob<>0 then raise exception 'V6 COMPANY CAPTURE FAIL: % current rows contain uncalibrated fields',v_bad_prob; end if;
  if v_empty_evidence<>0 then raise exception 'V6 COMPANY CAPTURE FAIL: % current rows have empty SEC evidence',v_empty_evidence; end if;
end $$;

select as_of,trend_key,count(*) candidate_pairs,count(distinct ticker) tickers
from public.oracle_v6_company_capture
where model_version='COMPANY_CAPTURE_EVIDENCE_GATE_V1'
  and as_of=(select max(evaluation_as_of) from public.oracle_v6_evaluation_runs)
group by as_of,trend_key
order by candidate_pairs desc,trend_key;
