import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncpg
from dotenv import load_dotenv
from datetime import datetime, timezone
import logging
import asyncio

# Configuration des logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

OWNER_ID = 691351470272020501  # Ton Discord ID

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Pool de connexions à la base de données
db_pool = None

async def init_database():
    """Initialise la base de données"""
    global db_pool
    
    try:
        db_pool = await asyncpg.create_pool(
            DATABASE_URL, 
            min_size=1, 
            max_size=10,
            command_timeout=60
        )
        logger.info("Pool de connexions créé avec succès")
        
        async with db_pool.acquire() as conn:
            # Créer la table des balances uniquement
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS balances (
                    user_id BIGINT PRIMARY KEY,
                    balance BIGINT DEFAULT 0 CHECK (balance >= 0),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            
            # Index pour optimiser les performances
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_balances_balance ON balances(balance DESC)')
            
            # Nettoyer les données corrompues
            await conn.execute('UPDATE balances SET balance = 0 WHERE balance < 0')
            
            logger.info("Table créée/vérifiée avec succès")
        
        return True
        
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation de la base de données: {e}")
        return False

async def get_balance(user_id):
    """Récupère le solde d'un utilisateur"""
    if not db_pool:
        return 0
        
    try:
        async with db_pool.acquire() as conn:
            result = await conn.fetchval('SELECT balance FROM balances WHERE user_id = $1', user_id)
            return max(0, result) if result is not None else 0
    except Exception as e:
        logger.error(f"Erreur get_balance pour user {user_id}: {e}")
        return 0

async def update_balance(user_id, amount):
    """Met à jour le solde d'un utilisateur"""
    if not db_pool:
        return False
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                # Vérifier le solde actuel si on retire de l'argent
                if amount < 0:
                    current_balance = await conn.fetchval(
                        'SELECT COALESCE(balance, 0) FROM balances WHERE user_id = $1 FOR UPDATE', 
                        user_id
                    ) or 0
                    
                    if current_balance + amount < 0:
                        return False
                
                # Mettre à jour ou insérer
                now = datetime.now(timezone.utc)
                await conn.execute('''
                    INSERT INTO balances (user_id, balance, updated_at) 
                    VALUES ($1, GREATEST(0, $2), $3)
                    ON CONFLICT (user_id) DO UPDATE SET 
                        balance = GREATEST(0, balances.balance + EXCLUDED.balance),
                        updated_at = EXCLUDED.updated_at
                ''', user_id, amount, now)
                
        return True
                
    except Exception as e:
        logger.error(f"Erreur update_balance pour user {user_id}, amount {amount}: {e}")
        return False

async def fetch_username(user_id):
    """Récupère le nom d'utilisateur"""
    try:
        user = bot.get_user(user_id)
        if user:
            return str(user)
        
        user = await bot.fetch_user(user_id)
        if user:
            return str(user)
        
        return f"Utilisateur inconnu ({user_id})"
    except discord.NotFound:
        return f"Utilisateur introuvable ({user_id})"
    except Exception as e:
        logger.error(f"Erreur fetch_username pour user {user_id}: {e}")
        return f"Erreur utilisateur ({user_id})"

@bot.event
async def on_ready():
    print(f"🤖 Connecté en tant que {bot.user}")
    try:
        success = await init_database()
        if success:
            await bot.tree.sync()
            print("✅ Base de données initialisée et commandes synchronisées !")
        else:
            print("❌ Erreur lors de l'initialisation de la base de données")
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation: {e}")

@bot.command(name="balance")
async def balance(ctx, member: discord.Member = None):
    """Affiche le solde d'un utilisateur"""
    try:
        target = member if member else ctx.author
        bal = await get_balance(target.id)
        
        if target == ctx.author:
            await ctx.send(f"{ctx.author.mention}, tu as **{bal:,} PrissBucks** 💵")
        else:
            await ctx.send(f"{target.mention} a **{bal:,} PrissBucks** 💵")
    except Exception as e:
        logger.error(f"Erreur commande balance: {e}")
        await ctx.send("❌ Erreur lors de la récupération du solde.")

@bot.tree.command(name="classement", description="Affiche le top 10 des détenteurs de PrissBucks 💵")
async def classement(interaction: discord.Interaction):
    """Affiche le classement des utilisateurs"""
    try:
        if not db_pool:
            await interaction.response.send_message("❌ Base de données non disponible.", ephemeral=True)
            return
            
        async with db_pool.acquire() as conn:
            results = await conn.fetch('''
                SELECT user_id, balance FROM balances 
                WHERE balance > 0 
                ORDER BY balance DESC 
                LIMIT 10
            ''')
        
        if not results:
            await interaction.response.send_message("Aucun PrissBucks trouvé pour le moment.", ephemeral=True)
            return

        description = ""
        medals = ["🥇", "🥈", "🥉"]
        
        for i, record in enumerate(results, start=1):
            user_id = record['user_id']
            balance = record['balance']
            username = await fetch_username(user_id)
            medal = medals[i-1] if i <= 3 else f"**{i}.**"
            description += f"{medal} {username} — **{balance:,} PrissBucks** 💵\n"

        embed = discord.Embed(
            title="🏆 Classement des PrissBucks", 
            description=description, 
            color=0xFFD700,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Mise à jour automatique")
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        logger.error(f"Erreur classement: {e}")
        await interaction.response.send_message("❌ Erreur lors de la récupération du classement.", ephemeral=True)

@bot.tree.command(name="give", description="Donne des PrissBucks à un membre (taxe 2%)")
@app_commands.describe(member="Le membre qui reçoit", amount="Le montant à donner")
async def give(interaction: discord.Interaction, member: discord.Member, amount: int):
    """Transférer des PrissBucks à un autre utilisateur"""
    try:
        sender = interaction.user.id
        receiver = member.id
        
        # Vérifications
        if amount <= 0:
            await interaction.response.send_message("❌ Le montant doit être positif.", ephemeral=True)
            return
        if amount > 1000000:  # Limite de sécurité
            await interaction.response.send_message("❌ Le montant est trop élevé (max: 1,000,000).", ephemeral=True)
            return
        if sender == receiver:
            await interaction.response.send_message("❌ Tu ne peux pas te donner des PrissBucks à toi-même.", ephemeral=True)
            return
        if member.bot:
            await interaction.response.send_message("❌ Tu ne peux pas donner des PrissBucks à un bot.", ephemeral=True)
            return

        if not db_pool:
            await interaction.response.send_message("❌ Service temporairement indisponible.", ephemeral=True)
            return

        # Calcul des montants
        tax = max(1, int(amount * 0.02))  # taxe 2%, minimum 1
        net_amount = amount - tax

        try:
            async with db_pool.acquire() as conn:
                async with conn.transaction():
                    # Vérifier le solde du sender
                    sender_balance = await conn.fetchval(
                        'SELECT COALESCE(balance, 0) FROM balances WHERE user_id = $1 FOR UPDATE', 
                        sender
                    ) or 0
                    
                    if sender_balance < amount:
                        await interaction.response.send_message(
                            f"❌ Tu n'as que **{sender_balance:,} PrissBucks** 💵, tu ne peux pas donner **{amount:,}**.", 
                            ephemeral=True
                        )
                        return
                    
                    now = datetime.now(timezone.utc)
                    
                    # Déduire du sender
                    await conn.execute('''
                        INSERT INTO balances (user_id, balance, updated_at) VALUES ($1, $2, $3)
                        ON CONFLICT (user_id) DO UPDATE SET 
                        balance = balances.balance - $4,
                        updated_at = $3
                    ''', sender, -amount, now, amount)
                    
                    # Ajouter au receiver
                    await conn.execute('''
                        INSERT INTO balances (user_id, balance, updated_at) VALUES ($1, $2, $3)
                        ON CONFLICT (user_id) DO UPDATE SET 
                        balance = balances.balance + $2,
                        updated_at = $3
                    ''', receiver, net_amount, now)
                    
                    # Ajouter la taxe à l'owner
                    await conn.execute('''
                        INSERT INTO balances (user_id, balance, updated_at) VALUES ($1, $2, $3)
                        ON CONFLICT (user_id) DO UPDATE SET 
                        balance = balances.balance + $2,
                        updated_at = $3
                    ''', OWNER_ID, tax, now)
                    
            # Transaction réussie
            await interaction.response.send_message(
                f"✅ {interaction.user.mention} a donné **{net_amount:,} PrissBucks** 💵 à {member.mention}\n"
                f"💰 Taxe prélevée: **{tax:,} PrissBucks**"
            )
                    
        except Exception as e:
            logger.error(f"Erreur transaction give: {e}")
            await interaction.response.send_message("❌ Erreur lors de la transaction.", ephemeral=True)
            
    except Exception as e:
        logger.error(f"Erreur give: {e}")
        await interaction.response.send_message("❌ Erreur lors de la transaction.", ephemeral=True)

@bot.event
async def on_command_error(ctx, error):
    """Gestionnaire d'erreurs pour les commandes"""
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argument manquant: `{error.param}`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argument invalide. Vérifie la syntaxe de la commande.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Membre introuvable. Assure-toi que le membre est sur ce serveur.")
    else:
        logger.error(f"Erreur commande {ctx.command}: {error}")
        await ctx.send("❌ Une erreur inattendue est survenue.")

@bot.event 
async def on_application_command_error(interaction: discord.Interaction, error):
    """Gestionnaire d'erreurs pour les slash commands"""
    logger.error(f"Erreur slash command {interaction.command}: {error}")
    if not interaction.response.is_done():
        await interaction.response.send_message(
            "❌ Une erreur inattendue est survenue.", 
            ephemeral=True
        )

# Gestionnaire de fermeture propre
async def close_pool():
    """Ferme proprement le pool de connexions"""
    if db_pool and not db_pool._closed:
        try:
            await db_pool.close()
            logger.info("Pool de connexions fermé proprement")
        except Exception as e:
            logger.error(f"Erreur fermeture pool: {e}")

if __name__ == "__main__":
    if not TOKEN:
        print("❌ TOKEN Discord manquant dans le fichier .env")
        exit(1)
    if not DATABASE_URL:
        print("❌ DATABASE_URL manquante dans le fichier .env")
        exit(1)
        
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du bot demandé...")
    except Exception as e:
        logger.error(f"Erreur critique: {e}")
    finally:
        # Fermeture propre
        try:
            if db_pool and not db_pool._closed:
                asyncio.get_event_loop().run_until_complete(close_pool())
        except Exception as e:
            logger.error(f"Erreur fermeture finale: {e}")
        
        print("🔴 Bot arrêté")