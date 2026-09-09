\set ON_ERROR_STOP on

do $$
declare g record;
begin
  select * into g from public.oracle_v6_tension_validation_gate limit 1;
  if coalesce(g.downstream_allowed,false)=false then
    raise exception 'P0-8 OPEN: benchmark has not met double-annotation, kappa and REAL_TENSION precision thresholds';
  end if;
end $$;
select * from public.oracle_v6_tension_validation_gate;
select 'P0-8 CLOSED' as result;