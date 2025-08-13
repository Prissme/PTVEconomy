import asyncio
import os
from dotenv import load_dotenv
from db import create_pool, init_db

# Charger les variables d'environnement
load_dotenv()

async def init_shop():
    """Initialise la boutique avec les items de base"""
    print("🚀 Initialisation de la boutique...")
    
    # Récupérer l'URL de la base de données
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ ERROR: DATABASE_URL non trouvé dans les variables d'environnement")
        return

    try:
        # Créer le pool de connexions et initialiser la BDD
        print("📡 Connexion à la base de données...")
        pool = await create_pool(database_url)
        await init_db(pool)

        # Demander l'ID du rôle Premium
        print("\n" + "="*50)
        print("🎭 CONFIGURATION DU RÔLE PREMIUM")
        print("="*50)
        print("Pour ajouter le rôle Premium au shop, vous devez :")
        print("1. Créer un rôle 'Premium' sur votre serveur Discord")
        print("2. Faire clic droit sur le rôle → Copier l'ID")
        print("3. Entrer l'ID ci-dessous")
        print()
        
        while True:
            role_id_input = input("🆔 Entrez l'ID du rôle Premium (ou 'skip' pour ignorer): ").strip()
            
            if role_id_input.lower() == 'skip':
                print("⏭️ Création du rôle Premium ignorée.")
                break
            
            try:
                role_id = int(role_id_input)
                
                # Vérifier si l'item existe déjà
                async with pool.acquire() as conn:
                    existing = await conn.fetchrow("""
                        SELECT id FROM shop_items 
                        WHERE data->>'role_id' = $1 AND type = 'role'
                    """, str(role_id))
                    
                    if existing:
                        print(f"⚠️ Ce rôle est déjà dans la boutique (ID: {existing['id']})")
                        overwrite = input("Voulez-vous le remplacer ? (y/n): ").lower().strip()
                        if overwrite not in ['y', 'yes', 'oui', 'o']:
                            continue
                        
                        # Désactiver l'ancien
                        await conn.execute("UPDATE shop_items SET is_active = FALSE WHERE id = $1", existing['id'])
                
                # Ajouter le nouveau rôle Premium
                async with pool.acquire() as conn:
                    item_id = await conn.fetchval("""
                        INSERT INTO shop_items (name, description, price, type, data)
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING id
                    """, 
                    "Rôle Premium", 
                    "🌟 Accès exclusif aux channels VIP, couleur dorée et privilèges spéciaux ! Rejoins l'élite du serveur.", 
                    10000, 
                    "role", 
                    {"role_id": role_id}
                    )
                
                print(f"✅ Rôle Premium ajouté avec succès ! (ID: {item_id})")
                print(f"💰 Prix: 10,000 PrissBucks")
                print(f"🎭 Role ID: {role_id}")
                break
                
            except ValueError:
                print("❌ ID invalide ! Entrez un nombre valide.")
            except Exception as e:
                print(f"❌ Erreur: {e}")

        # Optionnel: Ajouter d'autres items de base
        print("\n" + "="*50)
        print("🎁 ITEMS SUPPLÉMENTAIRES")
        print("="*50)
        
        other_items = input("Voulez-vous ajouter d'autres rôles au shop ? (y/n): ").lower().strip()
        
        if other_items in ['y', 'yes', 'oui', 'o']:
            await add_custom_items(pool)

        # Afficher le résumé
        await show_shop_summary(pool)
        
        await pool.close()
        print("\n🎉 Initialisation terminée avec succès !")
        
    except Exception as e:
        print(f"💥 Erreur critique: {e}")

async def add_custom_items(pool):
    """Ajoute des items personnalisés"""
    print("Vous pouvez ajouter d'autres rôles maintenant...")
    
    while True:
        print("\n" + "-"*30)
        name = input("📛 Nom du rôle (ou 'done' pour terminer): ").strip()
        if name.lower() == 'done':
            break
            
        description = input("📝 Description: ").strip()
        
        try:
            price = int(input("💰 Prix en PrissBucks: ").strip())
            role_id = int(input("🆔 ID du rôle Discord: ").strip())
        except ValueError:
            print("❌ Prix ou ID invalide !")
            continue
        
        try:
            async with pool.acquire() as conn:
                item_id = await conn.fetchval("""
                    INSERT INTO shop_items (name, description, price, type, data)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id
                """, name, description, price, "role", {"role_id": role_id})
            
            print(f"✅ {name} ajouté ! (ID: {item_id})")
            
        except Exception as e:
            print(f"❌ Erreur lors de l'ajout: {e}")

async def show_shop_summary(pool):
    """Affiche un résumé de la boutique"""
    print("\n" + "="*50)
    print("📊 RÉSUMÉ DE LA BOUTIQUE")
    print("="*50)
    
    async with pool.acquire() as conn:
        items = await conn.fetch("""
            SELECT id, name, price, type, is_active, data
            FROM shop_items
            ORDER BY price ASC
        """)
        
        if not items:
            print("📦 Aucun item dans la boutique.")
            return
            
        active_items = [item for item in items if item['is_active']]
        inactive_items = [item for item in items if not item['is_active']]
        
        if active_items:
            print(f"✅ Items actifs ({len(active_items)}):")
            for item in active_items:
                icon = "🎭" if item['type'] == 'role' else "📦"
                status = "✅" if item['is_active'] else "❌"
                print(f"  {icon} [{item['id']}] {item['name']} - {item['price']:,} 💰")
        
        if inactive_items:
            print(f"\n❌ Items inactifs ({len(inactive_items)}):")
            for item in inactive_items:
                icon = "🎭" if item['type'] == 'role' else "📦"
                print(f"  {icon} [{item['id']}] {item['name']} - {item['price']:,} 💰")

async def verify_setup():
    """Vérifie que le setup est correct"""
    print("\n🔍 Vérification de la configuration...")
    
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL manquant")
        return False
        
    try:
        pool = await create_pool(database_url)
        async with pool.acquire() as conn:
            # Vérifier les tables
            tables = await conn.fetch("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('users', 'shop_items', 'user_purchases')
            """)
            
            table_names = [table['table_name'] for table in tables]
            
            if len(table_names) == 3:
                print("✅ Toutes les tables sont présentes")
            else:
                print(f"⚠️ Tables manquantes: {set(['users', 'shop_items', 'user_purchases']) - set(table_names)}")
            
            # Compter les items
            count = await conn.fetchval("SELECT COUNT(*) FROM shop_items WHERE is_active = TRUE")
            print(f"📊 {count} item(s) actif(s) dans la boutique")
            
        await pool.close()
        return True
        
    except Exception as e:
        print(f"❌ Erreur de vérification: {e}")
        return False

if __name__ == "__main__":
    print("🛍️ Script d'initialisation de la boutique")
    print("=" * 50)
    
    try:
        # Vérification initiale
        if not asyncio.run(verify_setup()):
            print("❌ Configuration incorrecte, arrêt du script.")
            exit(1)
        
        # Initialisation
        asyncio.run(init_shop())
        
        print("\n" + "="*50)
        print("🎯 PROCHAINES ÉTAPES:")
        print("1. Démarrer votre bot Discord")
        print("2. Tester avec !shop pour voir la boutique")
        print("3. Donner des PrissBucks aux testeurs avec !addmoney")
        print("4. Tester un achat avec !buy 1")
        print("=" * 50)
        
    except KeyboardInterrupt:
        print("\n❌ Initialisation interrompue par l'utilisateur")
    except Exception as e:
        print(f"💥 Erreur fatale: {e}")
    
    print("\n👋 Script terminé !")
