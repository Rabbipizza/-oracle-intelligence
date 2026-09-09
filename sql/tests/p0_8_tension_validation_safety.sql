\set ON_ERROR_STOP on

do $$
declare g record; blocked boolean:=false;
begin
  select * into g from public.oracle_v6_tension_validation_gate limit 1;
  if g.config_version is null then raise exception 'P0-8 FAILED: validation config/gate missing'; end if;

  if coalesce(g.downstream_allowed,false)=false then
    begin
      insert into public.oracle_v6_bottleneck_forecasts(bottleneck_key,as_of,horizon_months,probability,model_version)
      values('P0-8:TEST',now(),3,0.5,'P0_8_GATE_TEST');
    exception when others then
      if sqlerrm like 'P0-8:%' then blocked:=true; else raise; end if;
    end;
    if not blocked then raise exception 'P0-8 FAILED: unvalidated tension reached bottleneck_forecasts'; end if;
  else
    if g.sample_size < g.minimum_sample_size then raise exception 'P0-8 FAILED: passing gate has insufficient sample'; end if;
    if g.double_annotated_size < g.minimum_sample_size then raise exception 'P0-8 FAILED: passing gate lacks double annotations'; end if;
    if g.cohen_kappa < g.minimum_kappa then raise exception 'P0-8 FAILED: passing gate has low kappa'; end if;
    if g.real_tension_precision < g.required_real_tension_precision then raise exception 'P0-8 FAILED: passing gate has low REAL_TENSION precision'; end if;
  end if;
end $$;

select config_version,required_real_tension_precision,minimum_kappa,minimum_sample_size,
       sample_size,double_annotated_size,cohen_kappa,real_tension_precision,benchmark_pass,downstream_allowed,failure_reason
from public.oracle_v6_tension_validation_gate;
select 'P0-8 SAFETY PASS: downstream is blocked unless benchmark closure criteria pass' as result;