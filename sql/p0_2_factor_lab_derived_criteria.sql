-- P0-2 — remove duplicated boolean verdicts from oracle_v5_factor_lab.
-- Source metrics remain canonical; criteria stores thresholds only.

create or replace function public.oracle_v5_factor_lab_normalize_criteria()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.criteria := coalesce(new.criteria, '{}'::jsonb)
    - 'win_rate_gt_55'
    - 'median_alpha_gt_0'
    - 'trimmed_alpha_gt_0'
    - 'min_sample_pass'
    - 'win_rate_pass'
    - 'median_alpha_pass'
    - 'trimmed_alpha_pass';
  return new;
end;
$$;

update public.oracle_v5_factor_lab
set criteria = (
  criteria
  - 'win_rate_gt_55'
  - 'median_alpha_gt_0'
  - 'trimmed_alpha_gt_0'
  - 'min_sample_pass'
  - 'win_rate_pass'
  - 'median_alpha_pass'
  - 'trimmed_alpha_pass'
) || jsonb_build_object(
  'min_sample', coalesce(nullif(criteria->>'min_sample','')::numeric, 100),
  'win_rate_gt', coalesce(nullif(criteria->>'win_rate_gt','')::numeric, 55),
  'median_alpha_gt', coalesce(nullif(criteria->>'median_alpha_gt','')::numeric, 0),
  'trimmed_alpha_gt', coalesce(nullif(criteria->>'trimmed_alpha_gt','')::numeric, 0)
);

drop trigger if exists oracle_v5_factor_lab_normalize_criteria_trg on public.oracle_v5_factor_lab;
create trigger oracle_v5_factor_lab_normalize_criteria_trg
before insert or update of criteria on public.oracle_v5_factor_lab
for each row execute function public.oracle_v5_factor_lab_normalize_criteria();

alter table public.oracle_v5_factor_lab
  drop constraint if exists oracle_v5_factor_lab_no_static_boolean_criteria;
alter table public.oracle_v5_factor_lab
  add constraint oracle_v5_factor_lab_no_static_boolean_criteria
  check (not (criteria ?| array[
    'win_rate_gt_55','median_alpha_gt_0','trimmed_alpha_gt_0',
    'min_sample_pass','win_rate_pass','median_alpha_pass','trimmed_alpha_pass'
  ]));

create or replace view public.oracle_v5_factor_lab_evaluated
with (security_invoker = true)
as
select
  f.*,
  coalesce((f.criteria->>'min_sample')::numeric, 100) as min_sample_threshold,
  coalesce((f.criteria->>'win_rate_gt')::numeric, 55) as win_rate_threshold,
  coalesce((f.criteria->>'median_alpha_gt')::numeric, 0) as median_alpha_threshold,
  coalesce((f.criteria->>'trimmed_alpha_gt')::numeric, 0) as trimmed_alpha_threshold,
  (f.sample_size >= coalesce((f.criteria->>'min_sample')::numeric, 100)) as min_sample_pass,
  (f.win_rate_vs_qqq > coalesce((f.criteria->>'win_rate_gt')::numeric, 55)) as win_rate_pass,
  (f.median_alpha_6m > coalesce((f.criteria->>'median_alpha_gt')::numeric, 0)) as median_alpha_pass,
  (f.trimmed_alpha_90pct > coalesce((f.criteria->>'trimmed_alpha_gt')::numeric, 0)) as trimmed_alpha_pass,
  (
    f.sample_size >= coalesce((f.criteria->>'min_sample')::numeric, 100)
    and f.win_rate_vs_qqq > coalesce((f.criteria->>'win_rate_gt')::numeric, 55)
    and f.median_alpha_6m > coalesce((f.criteria->>'median_alpha_gt')::numeric, 0)
    and f.trimmed_alpha_90pct > coalesce((f.criteria->>'trimmed_alpha_gt')::numeric, 0)
  ) as core_gate_pass
from public.oracle_v5_factor_lab f;
