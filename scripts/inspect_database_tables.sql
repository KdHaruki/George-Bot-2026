-- Neon SQL Editor: read-only inventory of Bot tables. Does not read row contents.
SELECT schemaname AS schema_name,
       tablename AS table_name,
       pg_size_pretty(pg_total_relation_size(
           format('%I.%I', schemaname, tablename)::regclass)) AS total_size
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  AND left(tablename, 7) = 'george_'
ORDER BY schemaname, tablename;
