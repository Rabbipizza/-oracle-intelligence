do $$
declare
  exp_id bigint;
  eval_ts timestamptz;
  n bigint;
  future_n bigint;
  bad_status bigint;
begin
  select id into exp_id from public.oracle_v6_experiments
   where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1'
     and invalidated_at is null order by created_at desc,id desc limit 1;
  select evaluation_as_of into eval_ts from public.oracle_v6_evaluation_runs
   where experiment_id=exp_id order by evaluation_as_of desc,id desc limit 1;
  select count(*) into n from public.oracle_v6_structural_company_exposure
   where experiment_id=exp_id and evaluation_as_of=eval_ts;
  if n=0 then raise exception 'V6 structural-company FAIL: no evidence-backed exposure links'; end if;
  select count(*) into future_n from public.oracle_v6_structural_company_exposure
   where experiment_id=exp_id and evaluation_as_of=eval_ts and evidence_available_at>evaluation_as_of;
  if future_n<>0 then raise exception 'V6 structural-company FAIL: % future evidence rows',future_n; end if;
  select count(*) into bad_status from public.oracle_v6_structural_company_exposure
   where experiment_id=exp_id and evaluation_as_of=eval_ts
     and exposure_status not in ('STRUCTURAL_EXPOSURE_CANDIDATE','EVIDENCE_BACKED_EXPOSURE');
  if bad_status<>0 then raise exception 'V6 structural-company FAIL: invalid statuses'; end if;
end $$;
select bottleneck_node,ticker,count(*) evidence_links
from public.oracle_v6_structural_company_exposure
where (experiment_id,evaluation_as_of)=(
  select e.id,r.evaluation_as_of from public.oracle_v6_experiments e
  join lateral (select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=e.id order by evaluation_as_of desc,id desc limit 1) r on true
  where e.model_family='COUNT_NULL_MODEL' and e.model_version='FORMAL_COUNT_NULL_V1' and e.invalidated_at is null
  order by e.created_at desc,e.id desc limit 1)
group by bottleneck_node,ticker order by evidence_links desc,bottleneck_node,ticker limit 30;
