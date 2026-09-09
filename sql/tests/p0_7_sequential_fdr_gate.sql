\set ON_ERROR_STOP on

do $$
declare cfg record; spent double precision; eph bigint; leaked bigint;
begin
  select * into cfg from public.oracle_v6_sequential_fdr_config where config_version='ONLINE_ALPHA_SPENDING_BH_V1' and active=true;
  if cfg.config_version is null then raise exception 'P0-7 FAILED: active sequential FDR config missing'; end if;

  select coalesce(max(cumulative_allocated_alpha),0) into spent from public.oracle_v6_sequential_run_budget;
  if spent > cfg.target_alpha + 1e-10 then raise exception 'P0-7 FAILED: cumulative alpha % exceeds target %',spent,cfg.target_alpha; end if;

  select count(*) into eph from public.oracle_v6_signal_lifecycle where lifecycle_state='EPHEMERAL_SIGNAL';
  if eph < 1 then raise exception 'P0-7 FAILED: no real signal reclassified EPHEMERAL_SIGNAL'; end if;

  select count(*) into leaked
  from public.oracle_v6_trend_universe u
  join public.oracle_v6_signal_lifecycle l on l.trend_key=u.trend_key
  where u.trend_origin='STATISTICAL_DISCOVERY' and l.lifecycle_state='EPHEMERAL_SIGNAL';
  if leaked <> 0 then raise exception 'P0-7 FAILED: % ephemeral signals leaked into trend universe',leaked; end if;

  select count(*) into leaked
  from public.oracle_v6_graph_edges g
  join public.oracle_v6_signal_lifecycle l
    on g.source_node='LEXICAL_SIGNAL:'||l.trend_key
  where g.generated_by_model='SEMANTIC_BRIDGE_V1' and l.lifecycle_state='EPHEMERAL_SIGNAL';
  if leaked <> 0 then raise exception 'P0-7 FAILED: % ephemeral signals leaked into semantic bridge',leaked; end if;
end $$;

select config_version,target_alpha,gamma_rule,min_replication_days,min_new_document_ratio,min_new_documents,min_qualifying_replications,candidate_replications
from public.oracle_v6_sequential_fdr_config where active=true;
select sequence_index,allocated_alpha,cumulative_allocated_alpha,family_size,document_count from public.oracle_v6_sequential_run_budget order by sequence_index desc limit 5;
select lifecycle_state,count(*) from public.oracle_v6_signal_lifecycle group by lifecycle_state order by lifecycle_state;
select 'P0-7 PASS' as result;