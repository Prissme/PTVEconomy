import asyncpg
from datetime import datetime
from typing import Optional

async def create_pool(dsn: str = None):
    """Crée un pool de connexions à la base de données"""
    if not dsn:
        raise ValueError("DSN is required to create database pool")
    return await asyncpg.create_pool(dsn=dsn)

async def init_db(pool):
    """Initialise les tables de la base de données"""
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance BIGINT DEFAULT 0,
                last_daily TIMESTAMP WITH TIME ZONE
            )
        ''')
        print("✅ Tables créées/vérifiées")

class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Se connecte à la base de données et initialise les tables"""
        self.pool = await create_pool(dsn=self.dsn)
        await init_db(self.pool)

    async def close(self):
        """Ferme le pool de connexions"""
        if self.pool:
            await self.pool.close()

    async def get_balance(self, user_id: int) -> int:
        """Récupère le solde d'un utilisateur"""
        if not self.pool:
            raise RuntimeError("Database not connected")
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
            return row["balance"] if row else 0

    async def update_balance(self, user_id: int, amount: int):
        """Met à jour le solde d'un utilisateur (ajoute le montant)"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, balance)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET balance = users.balance + EXCLUDED.balance
            """, user_id, amount)

    async def set_balance(self, user_id: int, amount: int):
        """Définit le solde exact d'un utilisateur"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, balance)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET balance = EXCLUDED.balance
            """, user_id, amount)

    async def transfer(self, giver_id: int, receiver_id: int, amount: int) -> bool:
        """Transfère des pièces entre deux utilisateurs"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        if amount <= 0:
            return False
            
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Vérifier le solde du donneur
                giver = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", giver_id)
                if not giver or giver["balance"] < amount:
                    return False
                
                # Effectuer le transfert
                await conn.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", amount, giver_id)
                await conn.execute("""
                    INSERT INTO users (user_id, balance)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id) DO UPDATE SET balance = users.balance + EXCLUDED.balance
                """, receiver_id, amount)
                return True

    async def get_last_daily(self, user_id: int) -> Optional[datetime]:
        """Récupère la dernière fois que l'utilisateur a fait son daily"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT last_daily FROM users WHERE user_id = $1", user_id)
            return row["last_daily"] if row else None

    async def set_last_daily(self, user_id: int, timestamp: datetime):
        """Met à jour la dernière fois que l'utilisateur a fait son daily"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, last_daily)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET last_daily = EXCLUDED.last_daily
            """, user_id, timestamp)

    async def get_top_users(self, limit: int = 10) -> list:
        """Récupère le classement des utilisateurs les plus riches"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id, balance 
                FROM users 
                WHERE balance > 0 
                ORDER BY balance DESC 
                LIMIT $1
            """, limit)
            return [(row["user_id"], row["balance"]) for row in rows]