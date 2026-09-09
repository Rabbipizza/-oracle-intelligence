\set ON_ERROR_STOP on
begin;

do $$
declare m bigint; l1 bigint; l2 bigint; s2 public.oracle_v6_epistemic_status;
begin
  select id into m from public.oracle_v6_analyst_memory order by id limit 1;
  if m is null then raise exception 'P0-6 test requires at least one analyst memory'; end if;

  insert into public.oracle_v6_analyst_memory_links(memory_id,source_node,target_node,relation_type,epistemic_status,status_evidence,created_at_run_id,last_updated_run_id,status_change_reason)
  values(m,'TEST:P0-6:A','TEST:P0-6:B','TEST_LINK','CAUSAL_VALIDATED','{"proof":"direct causal test evidence"}'::jsonb,'P0-6-TEST','P0-6-TEST','TEST_SETUP')
  returning id into l1;

  insert into public.oracle_v6_analyst_memory_links(memory_id,source_node,target_node,relation_type,epistemic_status,status_evidence,created_at_run_id,last_updated_run_id,status_change_reason)
  values(m,'TEST:P0-6:B','TEST:P0-6:C','TEST_LINK','HYPOTHESIS','{"proof":"NONE"}'::jsonb,'P0-6-TEST','P0-6-TEST','TEST_SETUP')
  returning id into l2;

  select epistemic_status into s2 from public.oracle_v6_analyst_memory_links where id=l2;
  if s2 <> 'HYPOTHESIS' then raise exception 'P0-6 FAILED: downstream link inherited predecessor confidence: %',s2; end if;

  begin
    update public.oracle_v6_analyst_memory_links
       set epistemic_status='DESCRIPTIVE_EVIDENCE', last_updated_run_id='P0-6-TEST'
     where id=l2;
    raise exception 'P0-6 FAILED: promotion without link-local evidence was accepted';
  exception when raise_exception then
    if sqlerrm like 'P0-6 FAILED:%' then raise; end if;
  end;
end $$;

rollback;

select 'P0-6 PASS: link confidence is independent and promotion requires link-local evidence' as result;