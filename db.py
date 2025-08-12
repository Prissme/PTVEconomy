import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL manquant dans .env")

_pool = None

async def init_database():
    """Initialise la base PostgreSQL et crée la table si elle n'existe pas."""
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL)

    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS economy (
                user_id BIGINT PRIMARY KEY,
                balance BIGINT DEFAULT 0,
                last_daily TIMESTAMP
            )
        """)

async def get_balance(user_id: int) -> int:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT balance FROM economy WHERE user_id = $1", user_id)
        return row["balance"] if row else 0

async def update_balance(user_id: int, amount: int):
    """Ajoute ou retire un montant du solde."""
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO economy (user_id, balance)
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET balance = economy.balance + $2
        """, user_id, amount)

async def set_last_daily(user_id: int, timestamp):
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO economy (user_id, balance, last_daily)
            VALUES ($1, 0, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET last_daily = $2
        """, user_id, timestamp)

async def get_last_daily(user_id: int):
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT last_daily FROM economy WHERE user_id = $1", user_id)
        return row["last_daily"] if row else None