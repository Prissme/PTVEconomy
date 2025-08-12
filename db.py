import asyncpg
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

db_pool: asyncpg.pool.Pool = None


# ------------------- INIT DB -------------------
async def init_database(DATABASE_URL: str):
    """Initialise la connexion et crée les tables si elles n'existent pas."""
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
            command_timeout=60
        )
        logger.info("✅ Pool DB créé")

        async with db_pool.acquire() as conn:
            # Table balances
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS balances (
                    user_id BIGINT PRIMARY KEY,
                    balance BIGINT DEFAULT 0 CHECK (balance >= 0),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_balances_balance ON balances(balance DESC)')

            # Table dailyspin
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS dailyspin (
                    user_id BIGINT PRIMARY KEY,
                    streak INTEGER DEFAULT 0,
                    last_spin TIMESTAMP WITH TIME ZONE
                )
            ''')
        return True
    except Exception as e:
        logger.error("Erreur init DB", exc_info=e)
        return False


# ------------------- BALANCE UTILS -------------------
async def get_balance(user_id: int) -> int:
    """Retourne la balance actuelle d'un joueur."""
    if not db_pool:
        return 0
    try:
        async with db_pool.acquire() as conn:
            bal = await conn.fetchval('SELECT balance FROM balances WHERE user_id=$1', user_id)
            return max(0, bal) if bal is not None else 0
    except Exception as e:
        logger.error("Erreur get_balance", exc_info=e)
        return 0


async def add_balance(user_id: int, amount: int) -> bool:
    """Ajoute (ou retire si négatif) un montant à la balance."""
    if not db_pool:
        return False
    try:
        now = datetime.now(timezone.utc)
        async with db_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO balances (user_id, balance, updated_at)
                VALUES ($1, GREATEST(0, $2), $3)
                ON CONFLICT (user_id) DO UPDATE
                SET balance = GREATEST(0, balances.balance + $2),
                    updated_at = $3
            ''', user_id, amount, now)
        return True
    except Exception as e:
        logger.error("Erreur add_balance", exc_info=e)
        return False


# ------------------- DAILYSPIN UTILS -------------------
async def get_dailyspin(user_id: int):
    """Récupère les infos dailyspin (streak, last_spin)."""
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            return await conn.fetchrow(
                'SELECT streak, last_spin FROM dailyspin WHERE user_id=$1',
                user_id
            )
    except Exception as e:
        logger.error("Erreur get_dailyspin", exc_info=e)
        return None


async def update_dailyspin(user_id: int, streak: int, last_spin):
    """Met à jour le streak et la date du dernier spin."""
    if not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO dailyspin (user_id, streak, last_spin)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE
                SET streak = $2, last_spin = $3
            ''', user_id, streak, last_spin)
        return True
    except Exception as e:
        logger.error("Erreur update_dailyspin", exc_info=e)
        return False