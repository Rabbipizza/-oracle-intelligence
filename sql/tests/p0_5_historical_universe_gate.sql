\set ON_ERROR_STOP on

-- All 291 current names must be represented in historical listings.
do $$
declare
  current_rows integer;
  covered_rows integer;
  delisted_rows integer;
  ticker_change_rows integer;
  merger_rows integer;
  atvi_before integer;
  atvi_after integer;
  inst_before integer;
  inst_after integer;
begin
  select current_universe_rows, current_universe_covered,
         delisting_rows, ticker_change_rows, merger_rows
    into current_rows, covered_rows, delisted_rows, ticker_change_rows, merger_rows
  from public.oracle_v6_universe_gate;

  if current_rows <> covered_rows then
    raise exception 'P0-5 FAIL: current universe coverage %/%', covered_rows, current_rows;
  end if;
  if delisted_rows < 1 then
    raise exception 'P0-5 FAIL: no verified delisting rows';
  end if;
  if ticker_change_rows < 2 then
    raise exception 'P0-5 FAIL: ticker-change history missing';
  end if;
  if merger_rows < 1 then
    raise exception 'P0-5 FAIL: merger history missing';
  end if;

  select count(*) into atvi_before from public.oracle_v6_universe_as_of('2023-10-12') where ticker='ATVI';
  select count(*) into atvi_after  from public.oracle_v6_universe_as_of('2023-10-13') where ticker='ATVI';
  select count(*) into inst_before from public.oracle_v6_universe_as_of('2024-11-12') where ticker='INST';
  select count(*) into inst_after  from public.oracle_v6_universe_as_of('2024-11-13') where ticker='INST';

  if atvi_before <> 1 or atvi_after <> 0 then
    raise exception 'P0-5 FAIL: ATVI temporal transition incorrect before=% after=%', atvi_before, atvi_after;
  end if;
  if inst_before <> 1 or inst_after <> 0 then
    raise exception 'P0-5 FAIL: INST temporal transition incorrect before=% after=%', inst_before, inst_after;
  end if;
end $$;

select * from public.oracle_v6_universe_gate;
