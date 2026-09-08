-- P0-2 regression tests. Fail fast with exceptions.

do $$
declare
  bad_count integer;
begin
  select count(*) into bad_count
  from public.oracle_v5_factor_lab
  where criteria ?| array[
    'win_rate_gt_55','median_alpha_gt_0','trimmed_alpha_gt_0',
    'min_sample_pass','win_rate_pass','median_alpha_pass','trimmed_alpha_pass'
  ];
  if bad_count <> 0 then
    raise exception 'P0-2 failed: % rows retain static boolean criteria', bad_count;
  end if;
end $$;

do $$
declare
  bad_count integer;
begin
  select count(*) into bad_count
  from public.oracle_v5_factor_lab_evaluated
  where min_sample_pass is distinct from (sample_size >= min_sample_threshold)
     or win_rate_pass is distinct from (win_rate_vs_qqq > win_rate_threshold)
     or median_alpha_pass is distinct from (median_alpha_6m > median_alpha_threshold)
     or trimmed_alpha_pass is distinct from (trimmed_alpha_90pct > trimmed_alpha_threshold)
     or core_gate_pass is distinct from (
       sample_size >= min_sample_threshold
       and win_rate_vs_qqq > win_rate_threshold
       and median_alpha_6m > median_alpha_threshold
       and trimmed_alpha_90pct > trimmed_alpha_threshold
     );
  if bad_count <> 0 then
    raise exception 'P0-2 failed: % evaluated rows diverge from raw metrics', bad_count;
  end if;
end $$;

begin;
update public.oracle_v5_factor_lab
set criteria = criteria || '{"win_rate_gt_55":true}'::jsonb
where factor_name = (select factor_name from public.oracle_v5_factor_lab order by factor_name limit 1);

do $$
declare
  bad_count integer;
begin
  select count(*) into bad_count
  from public.oracle_v5_factor_lab
  where criteria ? 'win_rate_gt_55';
  if bad_count <> 0 then
    raise exception 'P0-2 failed: trigger allowed a forbidden static boolean';
  end if;
end $$;
rollback;
