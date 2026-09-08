-- ORACLE V6: immutable availability vintage for reconstructed weekly term history.
create table if not exists public.oracle_v6_term_history_vintages (
  week_start date primary key,
  last_event_date date not null,
  available_at timestamptz not null,
  availability_quality text not null check (availability_quality in ('KNOWN','ESTIMATED')),
  provenance jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create or replace function public.oracle_v6_enforce_term_history_vintage()
returns trigger
language plpgsql
set search_path=public
as $$
declare
  v_week date;
  v_last date;
  v_available timestamptz;
begin
  if new.model_version = 'FORMAL_COUNT_NULL_V1' then
    v_week := nullif(new.training_window->>'test_week','')::date;
    v_last := nullif(new.training_window->>'test_last_event_date','')::date;
    if v_week is null then
      raise exception 'FORMAL_COUNT_NULL_V1 requires training_window.test_week';
    end if;
    if v_last is null then
      select max(last_event_date) into v_last
      from public.oracle_v4_term_history_weekly
      where week_start=v_week;
    end if;
    insert into public.oracle_v6_term_history_vintages
      (week_start,last_event_date,available_at,availability_quality,provenance)
    values
      (v_week,v_last,clock_timestamp(),'KNOWN',jsonb_build_object(
        'rule','first formal-null materialization observed by database',
        'created_by','oracle_v6_enforce_term_history_vintage'
      ))
    on conflict (week_start) do nothing;

    select available_at into v_available
    from public.oracle_v6_term_history_vintages
    where week_start=v_week;

    new.as_of := v_available;
    new.training_window := jsonb_set(coalesce(new.training_window,'{}'::jsonb),'{decision_as_of}',to_jsonb(v_available),true);
    new.diagnostics := jsonb_set(coalesce(new.diagnostics,'{}'::jsonb),'{decision_as_of}',to_jsonb(v_available),true);
    new.diagnostics := jsonb_set(new.diagnostics,'{availability_quality}',to_jsonb('KNOWN'::text),true);
    new.diagnostics := jsonb_set(new.diagnostics,'{availability_rule}',to_jsonb('oracle_v6_term_history_vintages.available_at'::text),true);
  end if;
  return new;
end $$;

drop trigger if exists oracle_v6_signal_null_models_vintage_trg on public.oracle_v6_signal_null_models;
create trigger oracle_v6_signal_null_models_vintage_trg
before insert or update on public.oracle_v6_signal_null_models
for each row execute function public.oracle_v6_enforce_term_history_vintage();

create or replace function public.oracle_v6_normalize_experiment_vintage()
returns trigger
language plpgsql
set search_path=public
as $$
declare
  v_week date;
  v_available timestamptz;
begin
  if new.model_family='COUNT_NULL_MODEL' and new.model_version='FORMAL_COUNT_NULL_V1' and new.metrics ? 'test_week' then
    v_week := nullif(new.metrics->>'test_week','')::date;
    select available_at into v_available from public.oracle_v6_term_history_vintages where week_start=v_week;
    if v_available is not null then
      new.metrics := jsonb_set(new.metrics,'{decision_as_of}',to_jsonb(v_available),true);
      new.metrics := jsonb_set(new.metrics,'{availability_quality}',to_jsonb('KNOWN'::text),true);
    end if;
  end if;
  return new;
end $$;

drop trigger if exists oracle_v6_experiments_vintage_trg on public.oracle_v6_experiments;
create trigger oracle_v6_experiments_vintage_trg
before insert or update on public.oracle_v6_experiments
for each row execute function public.oracle_v6_normalize_experiment_vintage();
