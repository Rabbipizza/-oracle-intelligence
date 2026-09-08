\set ON_ERROR_STOP on

-- All 291 current names must be represented in historical listings.
do $$
declare
  v_current_rows integer;
  v_covered_rows integer;
  v_delisted_rows integer;
  v_ticker_change_rows integer;
  v_merger_rows integer;
  v_atvi_before integer;
  v_atvi_after integer;
  v_inst_before integer;
  v_inst_after integer;
begin
  select g.current_universe_rows, g.current_universe_covered,
         g.delisting_rows, g.ticker_change_rows, g.merger_rows
    into v_current_rows, v_covered_rows, v_delisted_rows, v_ticker_change_rows, v_merger_rows
  from public.oracle_v6_universe_gate g;

  if v_current_rows <> v_covered_rows then
    raise exception 'P0-5 FAIL: current universe coverage %/%', v_covered_rows, v_current_rows;
  end if;
  if v_delisted_rows < 1 then
    raise exception 'P0-5 FAIL: no verified delisting rows';
  end if;
  if v_ticker_change_rows < 2 then
    raise exception 'P0-5 FAIL: ticker-change history missing';
  end if;
  if v_merger_rows < 1 then
    raise exception 'P0-5 FAIL: merger history missing';
  end if;

  select count(*) into v_atvi_before from public.oracle_v6_universe_as_of('2023-10-12') where ticker='ATVI';
  select count(*) into v_atvi_after  from public.oracle_v6_universe_as_of('2023-10-13') where ticker='ATVI';
  select count(*) into v_inst_before from public.oracle_v6_universe_as_of('2024-11-12') where ticker='INST';
  select count(*) into v_inst_after  from public.oracle_v6_universe_as_of('2024-11-13') where ticker='INST';

  if v_atvi_before <> 1 or v_atvi_after <> 0 then
    raise exception 'P0-5 FAIL: ATVI temporal transition incorrect before=% after=%', v_atvi_before, v_atvi_after;
  end if;
  if v_inst_before <> 1 or v_inst_after <> 0 then
    raise exception 'P0-5 FAIL: INST temporal transition incorrect before=% after=%', v_inst_before, v_inst_after;
  end if;
end $$;

select * from public.oracle_v6_universe_gate;
