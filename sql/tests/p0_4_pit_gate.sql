\set ON_ERROR_STOP on

-- Materialized PIT observations must never be future-dated.
do $$
begin
  if exists (
    select 1 from public.oracle_v6_pit_observations
    where available_at > now()
  ) then
    raise exception 'P0-4 FAIL: future-dated materialized PIT observation';
  end if;
end $$;

-- Heavy sources must be reachable through the routed/keyset gateway without
-- scanning the full hybrid ledger.
do $$
declare
  n integer;
begin
  select count(*) into n
  from public.get_features_as_of_v2(now(), 'STRUCTURAL_SIGNAL', null, null, null, 5);
  if n < 1 then raise exception 'P0-4 FAIL: STRUCTURAL_SIGNAL gateway empty'; end if;

  select count(*) into n
  from public.get_features_as_of_v2(now(), 'RAW_DOCUMENT', null, null, null, 5);
  if n < 1 then raise exception 'P0-4 FAIL: RAW_DOCUMENT gateway empty'; end if;
end $$;

-- Historical fundamental snapshots reconstructed after the fact may never be
-- backdated to as_of_date. Their availability is their actual created_at.
do $$
begin
  if exists (
    select 1
    from public.oracle_v5_fundamental_snapshots f
    where f.available_at is distinct from f.created_at
  ) then
    raise exception 'P0-4 FAIL: reconstructed fundamentals are backdated';
  end if;
end $$;

select 'P0-4 PASS' as result;
