-- P0-6: atomic epistemic integrity for Analyst Memory
-- Applied to Supabase as migration p0_6_analyst_memory_link_integrity.
-- Each relation is evaluated on link-local evidence only. Historical versions are append-only.

do $$ begin
  if not exists (select 1 from pg_type where typname='oracle_v6_epistemic_status') then
    create type public.oracle_v6_epistemic_status as enum ('HYPOTHESIS','DESCRIPTIVE_EVIDENCE','PREDICTIVE_EVIDENCE','CAUSAL_VALIDATED');
  end if;
end $$;

create table if not exists public.oracle_v6_analyst_memory_links (
  id bigint generated always as identity primary key,
  memory_id bigint not null references public.oracle_v6_analyst_memory(id) on delete cascade,
  source_node text not null,
  target_node text not null,
  relation_type text not null,
  epistemic_status public.oracle_v6_epistemic_status not null default 'HYPOTHESIS',
  status_evidence jsonb not null default '{}'::jsonb,
  created_at_run_id text,
  last_updated_run_id text,
  version_history jsonb not null default '[]'::jsonb,
  status_change_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(memory_id,source_node,target_node,relation_type)
);

create table if not exists public.oracle_v6_analyst_memory_link_versions (
  id bigint generated always as identity primary key,
  link_id bigint not null references public.oracle_v6_analyst_memory_links(id) on delete cascade,
  memory_id bigint not null references public.oracle_v6_analyst_memory(id) on delete cascade,
  source_node text not null,target_node text not null,relation_type text not null,
  epistemic_status public.oracle_v6_epistemic_status not null,
  status_evidence jsonb not null,run_id text,change_reason text,
  recorded_at timestamptz not null default now()
);

create or replace function public.oracle_v6_epistemic_rank(s public.oracle_v6_epistemic_status)
returns int language sql immutable as $$ select case s when 'HYPOTHESIS' then 1 when 'DESCRIPTIVE_EVIDENCE' then 2 when 'PREDICTIVE_EVIDENCE' then 3 when 'CAUSAL_VALIDATED' then 4 end $$;

create or replace function public.oracle_v6_memory_link_guard() returns trigger language plpgsql as $$
declare old_rank int; new_rank int; snapshot jsonb;
begin
  if tg_op='INSERT' then
    snapshot=jsonb_build_object('status',new.epistemic_status,'status_evidence',new.status_evidence,'run_id',new.created_at_run_id,'reason',coalesce(new.status_change_reason,'INITIAL_MATERIALIZATION'),'recorded_at',now());
    new.version_history=coalesce(new.version_history,'[]'::jsonb)||jsonb_build_array(snapshot); new.updated_at=now(); return new;
  end if;
  old_rank=public.oracle_v6_epistemic_rank(old.epistemic_status); new_rank=public.oracle_v6_epistemic_rank(new.epistemic_status);
  if new.epistemic_status is distinct from old.epistemic_status then
    if new.status_evidence = old.status_evidence then raise exception 'P0-6: status change requires link-local evidence; predecessor status cannot justify promotion'; end if;
    if new_rank < old_rank and nullif(btrim(coalesce(new.status_change_reason,'')),'') is null then raise exception 'P0-6: epistemic regression requires explicit status_change_reason'; end if;
    snapshot=jsonb_build_object('status',new.epistemic_status,'status_evidence',new.status_evidence,'run_id',new.last_updated_run_id,'reason',coalesce(new.status_change_reason,'EVIDENCE_UPDATE'),'recorded_at',now());
    new.version_history=coalesce(old.version_history,'[]'::jsonb)||jsonb_build_array(snapshot);
  else new.version_history=old.version_history; end if;
  new.updated_at=now(); return new;
end $$;

drop trigger if exists oracle_v6_memory_link_guard_trg on public.oracle_v6_analyst_memory_links;
create trigger oracle_v6_memory_link_guard_trg before insert or update on public.oracle_v6_analyst_memory_links for each row execute function public.oracle_v6_memory_link_guard();

create or replace function public.oracle_v6_memory_link_audit() returns trigger language plpgsql as $$
begin
  if tg_op='INSERT' or new.epistemic_status is distinct from old.epistemic_status or new.status_evidence is distinct from old.status_evidence then
    insert into public.oracle_v6_analyst_memory_link_versions(link_id,memory_id,source_node,target_node,relation_type,epistemic_status,status_evidence,run_id,change_reason)
    values(new.id,new.memory_id,new.source_node,new.target_node,new.relation_type,new.epistemic_status,new.status_evidence,coalesce(new.last_updated_run_id,new.created_at_run_id),coalesce(new.status_change_reason,case when tg_op='INSERT' then 'INITIAL_MATERIALIZATION' else 'EVIDENCE_UPDATE' end));
  end if; return new;
end $$;

drop trigger if exists oracle_v6_memory_link_audit_trg on public.oracle_v6_analyst_memory_links;
create trigger oracle_v6_memory_link_audit_trg after insert or update on public.oracle_v6_analyst_memory_links for each row execute function public.oracle_v6_memory_link_audit();