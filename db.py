import asyncpg
import os

DATABASE_URL = os.getenv("DATABASE_URL")

async def create_pool():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return await asyncpg.create_pool(DATABASE_URL)

async def init_db(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                user_id BIGINT PRIMARY KEY,
                balance BIGINT NOT NULL DEFAULT 0
            );
        """)

async def get_balance(pool, user_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT balance FROM balances WHERE user_id=$1", int(user_id))
        return row['balance'] if row else 0

async def set_balance(pool, user_id, amount):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO balances(user_id, balance) VALUES($1,$2)
            ON CONFLICT (user_id) DO UPDATE SET balance = $2;
        """, int(user_id), int(amount))

async def update_balance(pool, user_id, delta):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO balances(user_id, balance) VALUES($1,$2)
            ON CONFLICT (user_id) DO UPDATE SET balance = balances.balance + $2;
        """, int(user_id), int(delta))

async def get_top(pool, limit=10):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, balance FROM balances ORDER BY balance DESC LIMIT $1", int(limit))
        return [(r['user_id'], r['balance']) for r in rows]

async def transfer_with_tax(pool, sender, receiver, amount, owner_id, tax_rate=0.02):
    amount = int(amount)
    tax = max(1, int(amount * tax_rate))
    net = amount - tax

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT balance FROM balances WHERE user_id=$1", int(sender))
            if not row or row['balance'] < amount:
                raise ValueError("insufficient")
            await conn.execute("UPDATE balances SET balance = balance - $1 WHERE user_id=$2", amount, int(sender))
            await conn.execute("INSERT INTO balances(user_id, balance) VALUES($1,$2) ON CONFLICT (user_id) DO UPDATE SET balance = balances.balance + $2", int(receiver), net)
            await conn.execute("INSERT INTO balances(user_id, balance) VALUES($1,$2) ON CONFLICT (user_id) DO UPDATE SET balance = balances.balance + $2", int(owner_id), tax)
    return net, tax