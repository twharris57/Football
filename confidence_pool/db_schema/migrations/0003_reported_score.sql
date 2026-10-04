-- The pool's official weekly score; authoritative for late cards (rule 2).

ALTER TABLE week_status ADD COLUMN reported_score INTEGER;
ALTER TABLE week_status ADD COLUMN reported_score_entered_at TEXT;
