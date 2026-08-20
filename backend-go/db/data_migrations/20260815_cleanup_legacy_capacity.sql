-- Destructive development cleanup for Supabase Postgres capacity pressure.
--
-- Scope:
--   - public.rb_inventory_parts
--   - public.ldraw_file_references
--
-- These are legacy/public auxiliary import tables. They are not the Go
-- component_repo authority, and this script must not modify component_repo or
-- storage schemas. The target database must be confirmed by the operator before
-- execution.
--
-- Expected preflight on 2026-08-15:
--   public.rb_inventory_parts     ~1,497,951 rows / 128 MB
--   public.ldraw_file_references    ~431,347 rows / 122 MB
--
-- API and Worker startup must never run this script.

\set ON_ERROR_STOP on
\pset pager off

\echo 'legacy capacity cleanup: target database'
select current_database() as database, current_user as db_user;

\echo 'legacy capacity cleanup: before'
select n.nspname as schema_name,
       c.relname as table_name,
       c.reltuples::bigint as estimated_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) as total_size,
       pg_total_relation_size(c.oid) as bytes
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname in ('rb_inventory_parts', 'ldraw_file_references')
order by c.relname;

select 'rb_inventory_parts' as table_name, count(*) as exact_rows
from public.rb_inventory_parts
union all
select 'ldraw_file_references' as table_name, count(*) as exact_rows
from public.ldraw_file_references
order by table_name;

begin;

truncate table
  public.rb_inventory_parts,
  public.ldraw_file_references;

commit;

analyze public.rb_inventory_parts;
analyze public.ldraw_file_references;

\echo 'legacy capacity cleanup: after'
select n.nspname as schema_name,
       c.relname as table_name,
       c.reltuples::bigint as estimated_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) as total_size,
       pg_total_relation_size(c.oid) as bytes
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname in ('rb_inventory_parts', 'ldraw_file_references')
order by c.relname;

select 'rb_inventory_parts' as table_name, count(*) as exact_rows
from public.rb_inventory_parts
union all
select 'ldraw_file_references' as table_name, count(*) as exact_rows
from public.ldraw_file_references
order by table_name;

