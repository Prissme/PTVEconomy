import asyncio
import json
import os
from dotenv import load_dotenv
from db import create_pool, init_db

# Charger les variables d'environnement
load_dotenv()

DATA_FILE = "balances.json"

async def migrate():
    """Migre les données du fichier JSON vers la base de données PostgreSQL"""
    print("🔄 Début de la migration...")
    
    # Vérifier si le fichier de données existe
    if not os.path.exists(DATA_FILE):
        print(f"❌ {DATA_FILE} introuvable. Rien à migrer.")
        return

    # Récupérer l'URL de la base de données
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ ERROR: DATABASE_URL non trouvé dans les variables d'environnement")
        print("Assurez-vous que votre fichier .env contient: DATABASE_URL=postgresql://...")
        return

    try:
        # Créer le pool de connexions et initialiser la BDD
        print("📡 Connexion à la base de données...")
        pool = await create_pool(database_url)
        await init_db(pool)

        # Lire les données du fichier JSON
        print(f"📖 Lecture du fichier {DATA_FILE}...")
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not data:
            print("⚠️  Le fichier JSON est vide.")
            await pool.close()
            return

        print(f"📊 {len(data)} utilisateurs trouvés dans le fichier JSON")

        # Migrer les données
        migrated_count = 0
        failed_count = 0
        
        async with pool.acquire() as conn:
            async with conn.transaction():
                for uid, bal in data.items():
                    try:
                        # Valider les données
                        user_id = int(uid)
                        balance = int(bal)
                        
                        # Insérer ou mettre à jour dans la base
                        await conn.execute("""
                            INSERT INTO users(user_id, balance) VALUES($1,$2)
                            ON CONFLICT (user_id) DO UPDATE SET balance = EXCLUDED.balance
                        """, user_id, balance)
                        
                        migrated_count += 1
                        
                        if migrated_count % 100 == 0:
                            print(f"✅ {migrated_count} utilisateurs migrés...")
                            
                    except (ValueError, TypeError) as e:
                        print(f"❌ Erreur pour l'utilisateur {uid}: {e}")
                        failed_count += 1
                        continue

        await pool.close()
        
        print(f"🎉 Migration terminée !")
        print(f"✅ {migrated_count} utilisateurs migrés avec succès")
        if failed_count > 0:
            print(f"❌ {failed_count} utilisateurs ont échoué")
            
        # Optionnel : sauvegarder l'ancien fichier
        backup_file = f"{DATA_FILE}.backup"
        os.rename(DATA_FILE, backup_file)
        print(f"💾 Ancien fichier sauvegardé vers {backup_file}")

    except Exception as e:
        print(f"💥 Erreur critique lors de la migration: {e}")
        return

async def verify_migration():
    """Vérifie que la migration s'est bien passée"""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL non trouvé")
        return

    try:
        pool = await create_pool(database_url)
        async with pool.acquire() as conn:
            result = await conn.fetchrow("SELECT COUNT(*) as count, SUM(balance) as total FROM users")
            print(f"📈 Vérification: {result['count']} utilisateurs, total: {result['total']} pièces")
        await pool.close()
    except Exception as e:
        print(f"❌ Erreur lors de la vérification: {e}")

if __name__ == "__main__":
    print("🚀 Script de migration du bot économie")
    print("=" * 50)
    
    try:
        asyncio.run(migrate())
        
        # Demander si on veut vérifier
        verify = input("\n🔍 Voulez-vous vérifier la migration ? (y/n): ").lower().strip()
        if verify in ['y', 'yes', 'oui', 'o']:
            asyncio.run(verify_migration())
            
    except KeyboardInterrupt:
        print("\n❌ Migration interrompue par l'utilisateur")
    except Exception as e:
        print(f"💥 Erreur fatale: {e}")
    
    print("\n👋 Terminé !")