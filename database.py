"""
Database schema and seeding for ASAN Macro trade data.
Stores regional/sectoral trade flows for RAG and tool-augmented LLM analysis.
"""
import sqlite3
from pathlib import Path
from config import DB_PATH, get_db_path

SCHEMA_SQL = """
-- Trade flows (region/sector/time)
CREATE TABLE IF NOT EXISTS trade_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    quarter INTEGER,
    reporter_region TEXT NOT NULL,
    partner_region TEXT NOT NULL,
    sector TEXT NOT NULL,
    flow_type TEXT NOT NULL,
    value_usd REAL,
    volume_kg REAL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- RAG: stored summaries/chunks for retrieval (optional augmentation)
CREATE TABLE IF NOT EXISTS rag_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    content TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trade_reporter ON trade_flows(reporter_region);
CREATE INDEX IF NOT EXISTS idx_trade_partner ON trade_flows(partner_region);
CREATE INDEX IF NOT EXISTS idx_trade_sector ON trade_flows(sector);
CREATE INDEX IF NOT EXISTS idx_trade_year ON trade_flows(year);
"""

# Sample data: BRICS vs US/China decoupling narrative (synthetic but realistic)
SAMPLE_TRADE = [
    (2022, 1, "Brazil", "China", "Minerals", "export", 4.2e9),
    (2023, 1, "Brazil", "China", "Minerals", "export", 3.8e9),
    (2024, 1, "Brazil", "India", "Minerals", "export", 1.1e9),
    (2022, 1, "India", "Russia", "Energy", "import", 2.5e9),
    (2023, 1, "India", "Russia", "Energy", "import", 8.1e9),
    (2024, 1, "India", "Russia", "Energy", "import", 9.2e9),
    (2022, 1, "South Africa", "China", "Minerals", "export", 3.0e9),
    (2023, 1, "South Africa", "China", "Minerals", "export", 2.7e9),
    (2023, 1, "South Africa", "India", "Minerals", "export", 0.8e9),
    (2022, 1, "China", "USA", "Electronics", "export", 120e9),
    (2023, 1, "China", "USA", "Electronics", "export", 98e9),
    (2024, 1, "China", "USA", "Electronics", "export", 85e9),
    (2022, 1, "Vietnam", "USA", "Textiles", "export", 12e9),
    (2023, 1, "Vietnam", "USA", "Textiles", "export", 15e9),
    (2024, 1, "Vietnam", "USA", "Textiles", "export", 18e9),
    (2022, 1, "Mexico", "USA", "Manufacturing", "export", 220e9),
    (2023, 1, "Mexico", "USA", "Manufacturing", "export", 250e9),
    (2024, 1, "Mexico", "USA", "Manufacturing", "export", 280e9),
]

SAMPLE_RAG_CHUNKS = [
    ("trade_bulletin", "BRICS intra-trade in minerals and energy has risen sharply 2022-2024, with India-Russia energy trade and Brazil-India minerals trade growing.", '{"regions": ["BRICS"], "sectors": ["Minerals", "Energy"]}'),
    ("trade_bulletin", "US-China electronics trade has declined in nominal terms 2022-2024, consistent with decoupling and supply chain diversification.", '{"regions": ["USA", "China"], "sectors": ["Electronics"]}'),
    ("trade_bulletin", "Vietnam and Mexico have gained as alternative manufacturing and textiles suppliers to the US, with exports to USA rising.", '{"regions": ["Vietnam", "Mexico", "USA"], "sectors": ["Textiles", "Manufacturing"]}'),
    ("trade_bulletin", "Middle economies are forming stronger South-South trade links while reducing reliance on single dominant partners.", '{"theme": "decoupling"}'),
]


def init_db(db_path: Path = None):
    db_path = Path(db_path) if db_path else get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def seed_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trade_flows")
    if cur.fetchone()[0] > 0:
        return
    for row in SAMPLE_TRADE:
        cur.execute(
            "INSERT INTO trade_flows (year, quarter, reporter_region, partner_region, sector, flow_type, value_usd) VALUES (?,?,?,?,?,?,?)",
            row,
        )
    for source, content, meta in SAMPLE_RAG_CHUNKS:
        cur.execute(
            "INSERT INTO rag_chunks (source, content, metadata_json) VALUES (?,?,?)",
            (source, content, meta),
        )
    conn.commit()


def ensure_db():
    """Create and seed database if needed."""
    conn = init_db()
    seed_db(conn)
    conn.close()


def clear_trade_flows():
    """Remove all rows from trade_flows (e.g. before loading dynamic data only)."""
    conn = sqlite3.connect(str(get_db_path()))
    conn.execute("DELETE FROM trade_flows")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    ensure_db()
    print("Database ready at", DB_PATH)
