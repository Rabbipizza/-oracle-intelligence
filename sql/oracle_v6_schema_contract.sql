-- Deterministic fingerprint for the ORACLE V6 schema only.
-- Covers columns/defaults/nullability, constraints, indexes and RLS.
with tables as (
  select c.oid, n.nspname, c.relname, c.relrowsecurity
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public'
    and c.relkind = 'r'
    and c.relname like 'oracle_v6_%'
), objects as (
  select 'T|' || t.relname || '|RLS=' || t.relrowsecurity::text as line from tables t
  union all
  select 'C|' || t.relname || '|' || a.attnum::text || '|' || a.attname || '|' ||
         pg_catalog.format_type(a.atttypid,a.atttypmod) || '|NN=' || a.attnotnull::text ||
         '|D=' || coalesce(pg_get_expr(ad.adbin,ad.adrelid),'')
  from tables t
  join pg_attribute a on a.attrelid=t.oid and a.attnum>0 and not a.attisdropped
  left join pg_attrdef ad on ad.adrelid=a.attrelid and ad.adnum=a.attnum
  union all
  select 'K|' || t.relname || '|' || con.conname || '|' || con.contype::text || '|' || pg_get_constraintdef(con.oid,true)
  from tables t join pg_constraint con on con.conrelid=t.oid
  union all
  select 'I|' || t.relname || '|' || ci.relname || '|' || pg_get_indexdef(i.indexrelid)
  from tables t join pg_index i on i.indrelid=t.oid join pg_class ci on ci.oid=i.indexrelid
), normalized as (
  select regexp_replace(line, 'USING btree ', '', 'g') as line from objects
)
select md5(string_agg(line, E'\n' order by line)) as oracle_v6_schema_fingerprint
from normalized;
