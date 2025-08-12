import asyncpg
from datetime import datetime
from typing import Optional

class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(dsn=self.dsn)

    async def get_balance(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
            return row["balance"] if row else 0

    async def update_balance(self, user_id: int, amount: int):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, balance)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET balance = users.balance + EXCLUDED.balance
            """, user_id, amount)

    async def transfer(self, giver_id: int, receiver_id: int, amount: int) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                giver = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", giver_id)
                if not giver or giver["balance"] < amount:
                    return False
                await conn.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", amount, giver_id)
                await conn.execute("""
                    INSERT INTO users (user_id, balance)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id) DO UPDATE SET balance = users.balance + EXCLUDED.balance
                """, receiver_id, amount)
                return True

    async def get_last_daily(self, user_id: int) -> Optional[datetime]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT last_daily FROM users WHERE user_id = $1", user_id)
            return row["last_daily"] if row else None

    async def set_last_daily(self, user_id: int, timestamp: datetime):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, last_daily)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET last_daily = EXCLUDED.last_daily
            """, user_id, timestamp)