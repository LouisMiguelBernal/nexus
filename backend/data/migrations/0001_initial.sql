-- 0001_initial: the schema as it stood before migrations existed.
--
-- Every statement is IF NOT EXISTS so this applies cleanly to both an empty
-- file and the live nexus.db, which already carries these tables. Running it
-- against the live database is a no-op that only records the version.

CREATE TABLE IF NOT EXISTS zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    price_center REAL NOT NULL,
    price_low REAL NOT NULL,
    price_high REAL NOT NULL,
    zone_type TEXT NOT NULL,
    tier TEXT NOT NULL,
    score REAL NOT NULL,
    exchanges TEXT NOT NULL,
    exchange_count INTEGER NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    persistent INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS zone_watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    price_center REAL NOT NULL,
    tier TEXT NOT NULL,
    zone_type TEXT NOT NULL,
    status TEXT DEFAULT 'watching',
    alert_on_approach INTEGER DEFAULT 1,
    alert_on_hit INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,
    symbol TEXT,
    message TEXT NOT NULL,
    data TEXT,
    sent_telegram INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trade_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL,
    exit_price REAL,
    leverage INTEGER DEFAULT 1,
    size_usd REAL,
    pnl_usd REAL,
    pnl_pct REAL,
    zone_tier TEXT,
    zone_type TEXT,
    macro_status TEXT,
    notes TEXT,
    entry_time TIMESTAMP,
    exit_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_text TEXT NOT NULL,
    signals_json TEXT,
    generated_at REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Rolling snapshots of derivative metrics (OBI, tape speed, liquidation
-- imbalance). Written every few seconds; trimmed by the periodic pruner.
CREATE TABLE IF NOT EXISTS metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    metric TEXT NOT NULL,   -- obi | tape | liq
    t REAL NOT NULL,        -- unix seconds
    value REAL,             -- primary scalar (e.g. obi, tps, imbalance)
    extra TEXT              -- JSON blob for secondary fields
);

CREATE INDEX IF NOT EXISTS idx_zones_symbol ON zones(symbol);
CREATE INDEX IF NOT EXISTS idx_zones_tier ON zones(tier);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_journal_symbol ON trade_journal(symbol);
CREATE INDEX IF NOT EXISTS idx_metrics_sym_t ON metric_snapshots(symbol, metric, t);
