-- Surface when the deadline auto-lock's last-resort "compute fresh"
-- fallback ran after one of that week's included games had already kicked
-- off -- its odds may no longer reflect the original pregame line. Persisted
-- (rather than shown once at the moment of locking) so it stays visible on
-- every later view of an already-locked week, not just the one page load
-- when the lock happened.

ALTER TABLE week_status ADD COLUMN lock_warning TEXT;
