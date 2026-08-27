-- Phase 3a: record the pool's officially reported score for a locked week,
-- entered manually once the commissioner posts results (a future PDF/score-
-- sheet import may auto-populate this later -- see PROJECT_PLAN_CONFIDENCE_POOL.md).
--
-- This is the only way rule 2's late-card penalty (10 points below the
-- field's lowest card) ever gets reflected here -- this single-user app has
-- no visibility into other entrants' scores, so it can't compute that
-- penalty itself. Once present, reported_score is authoritative for a late
-- week; for an on-time week it doubles as a sanity check against the app's
-- own computed score (see picks_core.check_reported_score).

ALTER TABLE week_status ADD COLUMN reported_score INTEGER;
ALTER TABLE week_status ADD COLUMN reported_score_entered_at TEXT;
