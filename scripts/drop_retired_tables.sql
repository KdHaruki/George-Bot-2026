-- Confirmed retired tables from the provided Neon inventory.
-- Run in Neon SQL Editor against the intended George Bot database (public schema).
-- Only retired feature data is removed. No live data or migration records are deleted.
-- One transaction and no CASCADE: an unexpected dependency aborts all changes.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '10s';

DROP TABLE IF EXISTS
    public.george_link_vitality,
    public.george_link_bonds,
    public.george_link_items,
    public.george_link_migrations,
    public.george_link_daily,
    public.george_link_equipment,
    public.george_link_battles,
    public.george_memories,
    public.george_title_settings,
    public.george_present_exchanges,
    public.george_mood,
    public.george_reminders,
    public.george_title_streaks;

COMMIT;
