-- Initial trade block, as managers listed it on 2026-10-06. Runs once per database, so
-- entries later pruned or removed stay gone. OR IGNORE keeps any entry already listed.

INSERT OR IGNORE INTO trade_block (sleeper_id, roster_id, added_date) VALUES
    -- Christler
    ('8183', 1, '2026-10-06'),   -- Brock Purdy
    ('11564', 1, '2026-10-06'),  -- Drake Maye
    ('12489', 1, '2026-10-06'),  -- RJ Harvey
    ('8112', 1, '2026-10-06'),   -- Drake London
    ('11620', 1, '2026-10-06'),  -- Rome Odunze
    ('7525', 1, '2026-10-06'),   -- DeVonta Smith
    ('8130', 1, '2026-10-06'),   -- Trey McBride
    -- Quickdrawshaw
    ('5850', 2, '2026-10-06'),   -- Josh Jacobs
    ('5045', 2, '2026-10-06'),   -- Courtland Sutton
    -- D0nutman
    ('1166', 5, '2026-10-06'),   -- Kirk Cousins
    ('13272', 5, '2026-10-06'),  -- Carson Beck
    ('6768', 5, '2026-10-06'),   -- Tua Tagovailoa
    ('8161', 5, '2026-10-06'),   -- Malik Willis
    ('5892', 5, '2026-10-06'),   -- David Montgomery
    ('8408', 5, '2026-10-06'),   -- Jordan Mason
    ('10229', 5, '2026-10-06'),  -- Rashee Rice
    ('8131', 5, '2026-10-06'),   -- Isaiah Likely
    -- Boojwah
    ('6797', 6, '2026-10-06'),   -- Justin Herbert
    ('12534', 6, '2026-10-06'),  -- Kyle Monangai
    ('11584', 6, '2026-10-06'),  -- Bucky Irving
    ('5022', 6, '2026-10-06'),   -- Dallas Goedert
    -- ThePugArmy
    ('12507', 7, '2026-10-06');  -- Omarion Hampton
