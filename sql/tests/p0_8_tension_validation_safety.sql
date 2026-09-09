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
    if g.real_tension_precision < g.required_real_tension_precision then raise exception 'P0-8 FAILED: passing gate has low REAL_TENSION precision'; end if;
    if g.annotation_mode='DOUBLE_HUMAN' then
      if g.double_annotated_size < g.minimum_sample_size then raise exception 'P0-8 FAILED: passing DOUBLE_HUMAN gate lacks double annotations'; end if;
      if g.cohen_kappa < g.minimum_kappa then raise exception 'P0-8 FAILED: passing DOUBLE_HUMAN gate has low kappa'; end if;
    elsif g.annotation_mode='SINGLE_MODEL_EXPERT' then
      if coalesce(g.reference_labeled_size,0) < coalesce(g.minimum_reference_labels,g.minimum_sample_size) then raise exception 'P0-8 FAILED: passing SINGLE_MODEL_EXPERT gate lacks reference labels'; end if;
      if g.benchmark_annotation_mode <> 'SINGLE_MODEL_EXPERT' then raise exception 'P0-8 FAILED: benchmark/config annotation mode mismatch'; end if;
      if g.cohen_kappa is not null then raise exception 'P0-8 FAILED: single-model waiver must not claim inter-annotator kappa'; end if;
    else
      raise exception 'P0-8 FAILED: unsupported annotation mode %',g.annotation_mode;
    end if;
  end if;
end $$;

select config_version,annotation_mode,required_real_tension_precision,minimum_sample_size,
       sample_size,double_annotated_size,reference_labeled_size,cohen_kappa,
       real_tension_precision,real_tension_recall,real_tension_f1,benchmark_pass,downstream_allowed,failure_reason
from public.oracle_v6_tension_validation_gate;
select 'P0-8 SAFETY PASS: configured benchmark mode satisfies the enforced gate' as result;
