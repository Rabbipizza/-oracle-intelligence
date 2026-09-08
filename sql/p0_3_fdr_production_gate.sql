-- P0-3 — persist FDR family metadata and enforce the FDR gate downstream.

alter table public.oracle_v6_multiple_testing
  add column if not exists as_of timestamptz,
  add column if not exists fdr_alpha double precision,
  add column if not exists family_size integer;

alter table public.oracle_v6_multiple_testing
  drop constraint if exists oracle_v6_multiple_testing_fdr_alpha_check;
alter table public.oracle_v6_multiple_testing
  add constraint oracle_v6_multiple_testing_fdr_alpha_check
  check (fdr_alpha is null or (fdr_alpha > 0 and fdr_alpha < 1));

alter table public.oracle_v6_multiple_testing
  drop constraint if exists oracle_v6_multiple_testing_family_size_check;
alter table public.oracle_v6_multiple_testing
  add constraint oracle_v6_multiple_testing_family_size_check
  check (family_size is null or family_size > 0);

create unique index if not exists oracle_v6_multiple_testing_run_uq
  on public.oracle_v6_multiple_testing(
    experiment_id,
    hypothesis_key,
    as_of,
    coalesce(method,'')
  );

alter table public.oracle_v6_trend_probabilities
  add column if not exists experiment_id bigint references public.oracle_v6_experiments(id) on delete restrict;
alter table public.oracle_v6_trend_probabilities
  alter column experiment_id set not null;

create or replace function public.oracle_v6_enforce_fdr_before_trend()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if not exists (
    select 1
    from public.oracle_v6_multiple_testing mt
    where mt.experiment_id = new.experiment_id
      and mt.hypothesis_key = new.trend_key
      and mt.as_of = new.as_of
      and mt.method = 'BENJAMINI_HOCHBERG'
      and mt.selected is true
  ) then
    raise exception 'FDR_GATE_FAILED: trend % at % has no selected Benjamini-Hochberg record for experiment %',
      new.trend_key, new.as_of, new.experiment_id
      using errcode = '23514';
  end if;
  return new;
end;
$$;

drop trigger if exists oracle_v6_trend_probabilities_fdr_gate_trg
  on public.oracle_v6_trend_probabilities;
create trigger oracle_v6_trend_probabilities_fdr_gate_trg
before insert or update of trend_key, as_of, experiment_id
on public.oracle_v6_trend_probabilities
for each row execute function public.oracle_v6_enforce_fdr_before_trend();
