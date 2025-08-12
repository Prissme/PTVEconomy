import asyncio
import json
import os
from db import create_pool, init_db

DATA_FILE = "balances.json"

async def migrate():
    if not os.path.exists(DATA_FILE):
        print("balances.json not found. Rien à migrer.")
        return

    pool = await create_pool()
    await init_db(pool)

    with open(DATA_FILE, "r") as f:
        data = json.load(f)

    async with pool.acquire() as conn:
        async with conn.transaction():
            for uid, bal in data.items():
                await conn.execute("""
                    INSERT INTO balances(user_id, balance) VALUES($1,$2)
                    ON CONFLICT (user_id) DO UPDATE SET balance = $2
                """, int(uid), int(bal))
    await pool.close()
    print("Migration terminée.")

if __name__ == "__main__":
    asyncio.run(migrate())