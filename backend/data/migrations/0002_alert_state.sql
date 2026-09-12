-- 0002_alert_state: dedupe and cooldown state for the alert dispatcher.
--
-- The zone-approach alert re-fired every 60s for as long as price stayed
-- within 0.5% of a zone, because nothing remembered that it had already been
-- sent. The dispatcher keys on (alert_type, symbol, bucket) and refuses to
-- re-send inside the type's cooldown.

CREATE TABLE IF NOT EXISTS alert_state (
    dedupe_key TEXT PRIMARY KEY,   -- "<alert_type>:<symbol>:<bucket>"
    alert_type TEXT NOT NULL,
    symbol TEXT,
    last_sent_at REAL NOT NULL,    -- unix seconds
    send_count INTEGER NOT NULL DEFAULT 1,
    last_payload TEXT              -- JSON of the most recent alert
);

CREATE INDEX IF NOT EXISTS idx_alert_state_sent ON alert_state(last_sent_at);
