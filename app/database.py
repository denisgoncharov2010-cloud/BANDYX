
import aiosqlite
from pathlib import Path

DB_PATH = Path("bandyx.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS clubs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                logo TEXT
            )
        """)

        cursor = await db.execute("PRAGMA table_info(clubs)")
        club_columns = [row[1] for row in await cursor.fetchall()]
        if "logo" not in club_columns:
            await db.execute("ALTER TABLE clubs ADD COLUMN logo TEXT")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                position TEXT NOT NULL,
                price INTEGER NOT NULL,
                club_id INTEGER,
                photo TEXT,
                active INTEGER DEFAULT 1,
                FOREIGN KEY (club_id) REFERENCES clubs(id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS rounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                is_open INTEGER DEFAULT 0
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL,
                home_club_id INTEGER NOT NULL,
                away_club_id INTEGER NOT NULL,
                match_date TEXT,
                home_score INTEGER,
                away_score INTEGER,
                status TEXT DEFAULT 'scheduled',
                FOREIGN KEY (round_id) REFERENCES rounds(id),
                FOREIGN KEY (home_club_id) REFERENCES clubs(id),
                FOREIGN KEY (away_club_id) REFERENCES clubs(id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS selections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                round_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                FOREIGN KEY (player_id) REFERENCES players(id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS player_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                goals INTEGER DEFAULT 0,
                assists INTEGER DEFAULT 0,
                conceded INTEGER DEFAULT 0,
                penalties_saved INTEGER DEFAULT 0,
                team_result TEXT DEFAULT 'draw'
            )
        """)

        await db.commit()
