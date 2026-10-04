-- Persisted caveat when an auto-lock computed odds after a kickoff.

ALTER TABLE week_status ADD COLUMN lock_warning TEXT;
