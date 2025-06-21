import aiosqlite
import datetime

DB_PATH = "data/data.db"

async def setup_database():
    print("[DB] setup_database() called, ensuring table exists")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS lottery (
            guild_id TEXT PRIMARY KEY,
            current_winner_id TEXT,
            current_winner_name TEXT,
            pref_winner_id TEXT,
            pref_winner_name TEXT,
            draw_date TEXT,
            lottery_channel_id TEXT,
            lottery_planning_date TEXT
        )
        """)
        await db.commit()

async def migrate_add_channel_column():
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("ALTER TABLE lottery ADD COLUMN lottery_channel_id TEXT")
            await db.commit()
            print("[DB] Migration: Added 'lottery_channel_id' column")
        except aiosqlite.OperationalError:
            print("[DB] Migration: Column 'lottery_channel_id' already exists")

async def set_winner(guild_id: int, member):
    print(f"[DB] set_winner() called for guild {guild_id} -> member: {member.name} ({member.id})")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT current_winner_id, current_winner_name FROM lottery WHERE guild_id = ?", (str(guild_id),)) as cursor:
            row = await cursor.fetchone()
            prev_id = row[0] if row else None
            prev_name = row[1] if row else None

        await db.execute("""
        INSERT INTO lottery (guild_id, current_winner_id, current_winner_name, pref_winner_id, pref_winner_name, draw_date)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            pref_winner_id = excluded.pref_winner_id,
            pref_winner_name = excluded.pref_winner_name,
            current_winner_id = excluded.current_winner_id,
            current_winner_name = excluded.current_winner_name,
            draw_date = excluded.draw_date
        """, (
            str(guild_id),
            str(member.id),
            member.name,
            prev_id,
            prev_name,
            datetime.datetime.utcnow().strftime("%Y-%m-%d")
        ))
        await db.commit()

async def get_current_winner(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT current_winner_id, current_winner_name FROM lottery WHERE guild_id = ?", (str(guild_id),)) as cursor:
            return await cursor.fetchone()

async def get_previous_winner(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT pref_winner_id, pref_winner_name FROM lottery WHERE guild_id = ?", (str(guild_id),)) as cursor:
            return await cursor.fetchone()

async def set_lottery_channel(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO lottery (guild_id, lottery_channel_id)
        VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            lottery_channel_id = excluded.lottery_channel_id
        """, (str(guild_id), str(channel_id)))
        await db.commit()

async def get_lottery_channel(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lottery_channel_id FROM lottery WHERE guild_id = ?", (str(guild_id),)) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row and row[0] else None

async def set_lottery_date(guild_id: int, planning_date: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO lottery (guild_id, lottery_planning_date)
        VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            lottery_planning_date = excluded.lottery_planning_date
        """, (str(guild_id), planning_date))
        await db.commit()

async def get_lottery_date(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lottery_planning_date FROM lottery WHERE guild_id = ?", (str(guild_id),)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] else None

async def delete_lottery_date(guild_id: int):
    """
    Удаляет запланированную дату розыгрыша, обнуляя поле lottery_planning_date.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE lottery SET lottery_planning_date = NULL WHERE guild_id = ?",
            (str(guild_id),)
        )
        await db.commit()
