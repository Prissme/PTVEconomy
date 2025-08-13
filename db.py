import asyncpg
from datetime import datetime
from typing import Optional, List, Dict, Tuple

async def create_pool(dsn: str = None):
    """Crée un pool de connexions à la base de données"""
    if not dsn:
        raise ValueError("DSN is required to create database pool")
    return await asyncpg.create_pool(dsn=dsn)

async def init_db(pool):
    """Initialise les tables de la base de données"""
    async with pool.acquire() as conn:
        # Table users existante
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance BIGINT DEFAULT 0,
                last_daily TIMESTAMP WITH TIME ZONE
            )
        ''')
        
        # Nouvelle table pour les items du shop
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS shop_items (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                price BIGINT NOT NULL,
                type VARCHAR(50) NOT NULL,
                data JSON,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        ''')
        
        # Nouvelle table pour les achats des utilisateurs
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_purchases (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                item_id INTEGER REFERENCES shop_items(id),
                purchase_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                price_paid BIGINT NOT NULL
            )
        ''')
        
        # Index pour optimiser les requêtes
        await conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_user_purchases_user_id ON user_purchases(user_id)
        ''')
        await conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_user_purchases_item_id ON user_purchases(item_id)
        ''')
        
        print("✅ Tables créées/vérifiées (avec système shop)")

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

    # ==================== MÉTHODES ÉCONOMIE EXISTANTES ====================

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

    # ==================== NOUVELLES MÉTHODES SHOP ====================

    async def get_shop_items(self, active_only: bool = True) -> List[Dict]:
        """Récupère la liste des items du shop"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        import json
        async with self.pool.acquire() as conn:
            query = """
                SELECT id, name, description, price, type, data, is_active, created_at
                FROM shop_items
            """
            if active_only:
                query += " WHERE is_active = TRUE"
            query += " ORDER BY price ASC"
            
            rows = await conn.fetch(query)
            items = []
            for row in rows:
                item = dict(row)
                # Convertir le JSON string en dictionnaire Python
                if item['data'] and isinstance(item['data'], str):
                    try:
                        item['data'] = json.loads(item['data'])
                    except json.JSONDecodeError:
                        item['data'] = {}
                items.append(item)
            return items

    async def get_shop_item(self, item_id: int) -> Optional[Dict]:
        """Récupère un item spécifique du shop"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        import json
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, name, description, price, type, data, is_active, created_at
                FROM shop_items 
                WHERE id = $1
            """, item_id)
            
            if not row:
                return None
                
            item = dict(row)
            # Convertir le JSON string en dictionnaire Python
            if item['data'] and isinstance(item['data'], str):
                try:
                    item['data'] = json.loads(item['data'])
                except json.JSONDecodeError:
                    item['data'] = {}
            return item

    async def add_shop_item(self, name: str, description: str, price: int, item_type: str, data: Dict) -> int:
        """Ajoute un item au shop"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        import json
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO shop_items (name, description, price, type, data)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, name, description, price, item_type, json.dumps(data))
            return row["id"]

    async def update_shop_item(self, item_id: int, **kwargs) -> bool:
        """Met à jour un item du shop"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        if not kwargs:
            return False
            
        # Construire la requête dynamiquement
        set_clause = ", ".join([f"{key} = ${i+2}" for i, key in enumerate(kwargs.keys())])
        values = [item_id] + list(kwargs.values())
        
        async with self.pool.acquire() as conn:
            result = await conn.execute(f"""
                UPDATE shop_items 
                SET {set_clause} 
                WHERE id = $1
            """, *values)
            return result != "UPDATE 0"

    async def deactivate_shop_item(self, item_id: int) -> bool:
        """Désactive un item du shop"""
        return await self.update_shop_item(item_id, is_active=False)

    async def has_purchased_item(self, user_id: int, item_id: int) -> bool:
        """Vérifie si un utilisateur a déjà acheté un item"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 1 FROM user_purchases 
                WHERE user_id = $1 AND item_id = $2
                LIMIT 1
            """, user_id, item_id)
            return row is not None

    async def purchase_item(self, user_id: int, item_id: int) -> Tuple[bool, str]:
        """Effectue l'achat d'un item (transaction atomique)"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        import json
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Vérifier que l'item existe et est actif
                item_row = await conn.fetchrow("""
                    SELECT id, name, price, type, data 
                    FROM shop_items 
                    WHERE id = $1 AND is_active = TRUE
                """, item_id)
                
                if not item_row:
                    return False, "Item inexistant ou inactif"
                
                # Convertir les données en dictionnaire Python
                item = dict(item_row)
                if item['data'] and isinstance(item['data'], str):
                    try:
                        item['data'] = json.loads(item['data'])
                    except json.JSONDecodeError:
                        item['data'] = {}
                
                # Vérifier si l'utilisateur a déjà acheté cet item (pour les rôles)
                if item["type"] == "role":
                    existing = await conn.fetchrow("""
                        SELECT 1 FROM user_purchases 
                        WHERE user_id = $1 AND item_id = $2
                    """, user_id, item_id)
                    if existing:
                        return False, "Tu possèdes déjà cet item"
                
                # Vérifier le solde de l'utilisateur
                user_balance = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
                current_balance = user_balance["balance"] if user_balance else 0
                
                if current_balance < item["price"]:
                    return False, f"Solde insuffisant (tu as {current_balance:,}, il faut {item['price']:,})"
                
                # Débiter le compte
                await conn.execute("""
                    UPDATE users SET balance = balance - $1 WHERE user_id = $2
                """, item["price"], user_id)
                
                # Enregistrer l'achat
                await conn.execute("""
                    INSERT INTO user_purchases (user_id, item_id, price_paid)
                    VALUES ($1, $2, $3)
                """, user_id, item_id, item["price"])
                
                return True, f"Achat de '{item['name']}' réussi !"

    async def get_user_purchases(self, user_id: int) -> List[Dict]:
        """Récupère la liste des achats d'un utilisateur"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        import json
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT up.id, up.purchase_date, up.price_paid,
                       si.name, si.description, si.type, si.data
                FROM user_purchases up
                JOIN shop_items si ON up.item_id = si.id
                WHERE up.user_id = $1
                ORDER BY up.purchase_date DESC
            """, user_id)
            
            purchases = []
            for row in rows:
                purchase = dict(row)
                # Convertir le JSON string en dictionnaire Python
                if purchase['data'] and isinstance(purchase['data'], str):
                    try:
                        purchase['data'] = json.loads(purchase['data'])
                    except json.JSONDecodeError:
                        purchase['data'] = {}
                purchases.append(purchase)
            return purchases

    async def get_shop_stats(self) -> Dict:
        """Récupère les statistiques du shop"""
        if not self.pool:
            raise RuntimeError("Database not connected")
            
        async with self.pool.acquire() as conn:
            # Statistiques générales
            stats = await conn.fetchrow("""
                SELECT 
                    COUNT(DISTINCT up.user_id) as unique_buyers,
                    COUNT(up.id) as total_purchases,
                    COALESCE(SUM(up.price_paid), 0) as total_revenue
                FROM user_purchases up
            """)
            
            # Top des items les plus vendus
            top_items = await conn.fetch("""
                SELECT si.name, COUNT(up.id) as purchases, SUM(up.price_paid) as revenue
                FROM user_purchases up
                JOIN shop_items si ON up.item_id = si.id
                GROUP BY si.id, si.name
                ORDER BY purchases DESC
                LIMIT 5
            """)
            
            return {
                "unique_buyers": stats["unique_buyers"],
                "total_purchases": stats["total_purchases"],
                "total_revenue": stats["total_revenue"],
                "top_items": [dict(row) for row in top_items]
            }