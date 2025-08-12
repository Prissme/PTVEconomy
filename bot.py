import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncpg
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import logging
import asyncio

# Configuration des logs
logging.basicConfig(level=logging.INFO)
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
    """Initialise la base de données et crée les tables"""
    global db_pool
    
    try:
        db_pool = await asyncpg.create_pool(
            DATABASE_URL, 
            min_size=1, 
            max_size=10,
            command_timeout=30,
            server_settings={
                'application_name': 'PrissBucks_Bot',
                'timezone': 'UTC'
            }
        )
        logger.info("Pool de connexions créé avec succès")
        
        async with db_pool.acquire() as conn:
            # Créer les tables si elles n'existent pas
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS balances (
                    user_id BIGINT PRIMARY KEY,
                    balance INTEGER DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS daily_cooldowns (
                    user_id BIGINT PRIMARY KEY,
                    last_claim TIMESTAMP WITH TIME ZONE NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS message_cooldowns (
                    user_id BIGINT PRIMARY KEY,
                    last_message TIMESTAMP WITH TIME ZONE NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            
            # Créer des index pour optimiser les performances
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_balances_balance ON balances(balance DESC)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_daily_cooldowns_last_claim ON daily_cooldowns(last_claim)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_message_cooldowns_last_message ON message_cooldowns(last_message)')
            
            logger.info("Tables créées/vérifiées avec succès")
        
        return True
        
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation de la base de données: {e}")
        return False

async def get_balance(user_id):
    """Récupère le solde d'un utilisateur"""
    if not db_pool:
        logger.error("Pool de base de données non disponible")
        return 0
        
    try:
        async with db_pool.acquire() as conn:
            result = await conn.fetchval('SELECT balance FROM balances WHERE user_id = $1', user_id)
            return result if result is not None else 0
    except Exception as e:
        logger.error(f"Erreur get_balance pour user {user_id}: {e}")
        return 0

async def update_balance(user_id, amount):
    """Met à jour le solde d'un utilisateur avec transaction sécurisée"""
    if not db_pool:
        logger.error("Pool de base de données non disponible")
        return False
        
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                # Vérifier le solde actuel si on retire de l'argent
                if amount < 0:
                    current_balance = await conn.fetchval('SELECT balance FROM balances WHERE user_id = $1', user_id)
                    if current_balance is None:
                        current_balance = 0
                    
                    if current_balance + amount < 0:
                        logger.warning(f"Solde insuffisant pour user {user_id}: {current_balance} + {amount}")
                        return False
                
                # Mettre à jour ou insérer
                await conn.execute('''
                    INSERT INTO balances (user_id, balance, updated_at) 
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id) DO UPDATE SET 
                        balance = balances.balance + $2,
                        updated_at = $3
                ''', user_id, amount, datetime.now(timezone.utc))
                
                # Vérifier que la balance finale n'est pas négative
                final_balance = await conn.fetchval('SELECT balance FROM balances WHERE user_id = $1', user_id)
                if final_balance < 0:
                    await conn.execute('UPDATE balances SET balance = 0 WHERE user_id = $1', user_id)
                    logger.warning(f"Balance négative corrigée pour user {user_id}")
                
        return True
    except Exception as e:
        logger.error(f"Erreur update_balance pour user {user_id}, amount {amount}: {e}")
        return False

async def set_balance(user_id, amount):
    """Définit le solde exact d'un utilisateur"""
    if not db_pool:
        logger.error("Pool de base de données non disponible")
        return False
        
    try:
        async with db_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO balances (user_id, balance, updated_at) VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET 
                balance = $2,
                updated_at = $3
            ''', user_id, max(0, amount), datetime.now(timezone.utc))
        return True
    except Exception as e:
        logger.error(f"Erreur set_balance pour user {user_id}, amount {amount}: {e}")
        return False

async def get_daily_cooldown(user_id):
    """Récupère le cooldown daily d'un utilisateur"""
    if not db_pool:
        return None
        
    try:
        async with db_pool.acquire() as conn:
            result = await conn.fetchval('SELECT last_claim FROM daily_cooldowns WHERE user_id = $1', user_id)
            return result
    except Exception as e:
        logger.error(f"Erreur get_daily_cooldown pour user {user_id}: {e}")
        return None

async def set_daily_cooldown(user_id):
    """Définit le cooldown daily d'un utilisateur"""
    if not db_pool:
        return False
        
    try:
        async with db_pool.acquire() as conn:
            now = datetime.now(timezone.utc)
            await conn.execute('''
                INSERT INTO daily_cooldowns (user_id, last_claim) VALUES ($1, $2::timestamptz)
                ON CONFLICT (user_id) DO UPDATE SET last_claim = $2::timestamptz
            ''', user_id, now)
        return True
    except Exception as e:
        logger.error(f"Erreur set_daily_cooldown pour user {user_id}: {e}")
        return False

async def get_message_cooldown(user_id):
    """Récupère le cooldown message d'un utilisateur"""
    if not db_pool:
        return None
        
    try:
        async with db_pool.acquire() as conn:
            result = await conn.fetchval('SELECT last_message FROM message_cooldowns WHERE user_id = $1', user_id)
            return result
    except Exception as e:
        logger.error(f"Erreur get_message_cooldown pour user {user_id}: {e}")
        return None

async def set_message_cooldown(user_id):
    """Définit le cooldown message d'un utilisateur"""
    if not db_pool:
        return False
        
    try:
        async with db_pool.acquire() as conn:
            now = datetime.now(timezone.utc)
            await conn.execute('''
                INSERT INTO message_cooldowns (user_id, last_message) VALUES ($1, $2::timestamptz)
                ON CONFLICT (user_id) DO UPDATE SET last_message = $2::timestamptz
            ''', user_id, now)
        return True
    except Exception as e:
        logger.error(f"Erreur set_message_cooldown pour user {user_id}: {e}")
        return False

async def fetch_username(user_id):
    """Récupère le nom d'utilisateur avec gestion d'erreur améliorée"""
    try:
        user = bot.get_user(user_id)
        if user:
            return str(user)
        
        # Essayer de récupérer l'utilisateur depuis l'API Discord
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

@bot.command(name="daily")
async def daily(ctx):
    """Récompense quotidienne"""
    try:
        user_id = ctx.author.id
        now = datetime.now(timezone.utc)
        
        # Vérifier le cooldown
        last_claim = await get_daily_cooldown(user_id)

        if last_claim:
            # Convertir en UTC si nécessaire
            if last_claim.tzinfo is None:
                last_claim = last_claim.replace(tzinfo=timezone.utc)
            else:
                last_claim = last_claim.astimezone(timezone.utc)
                
            time_diff = now - last_claim
            if time_diff < timedelta(hours=24):
                remaining = timedelta(hours=24) - time_diff
                heures = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                await ctx.send(f"{ctx.author.mention}, tu as déjà récupéré ta récompense quotidienne. Reviens dans **{heures}h{minutes:02d}m** ⏳")
                return

        # Donner la récompense avec transaction
        gain = 50
        
        if not db_pool:
            await ctx.send("❌ Service temporairement indisponible. Réessaye dans quelques instants.")
            return
            
        try:
            async with db_pool.acquire() as conn:
                async with conn.transaction():
                    # Mettre à jour la balance
                    await conn.execute('''
                        INSERT INTO balances (user_id, balance, updated_at) VALUES ($1, $2, $3)
                        ON CONFLICT (user_id) DO UPDATE SET 
                        balance = balances.balance + $2,
                        updated_at = $3
                    ''', user_id, gain, now)
                    
                    # Définir le cooldown avec timezone explicite
                    await conn.execute('''
                        INSERT INTO daily_cooldowns (user_id, last_claim) VALUES ($1, $2::timestamptz)
                        ON CONFLICT (user_id) DO UPDATE SET last_claim = $2::timestamptz
                    ''', user_id, now)
                    
                    # Récupérer la nouvelle balance
                    new_balance = await conn.fetchval('SELECT balance FROM balances WHERE user_id = $1', user_id)
                    
            await ctx.send(f"🎉 {ctx.author.mention}, tu as récupéré ta récompense quotidienne de **{gain} PrissBucks** 💵 !\n💰 Nouveau solde: **{new_balance:,} PrissBucks**")
            
        except Exception as e:
            logger.error(f"Erreur transaction daily pour {user_id}: {e}")
            await ctx.send(f"❌ {ctx.author.mention}, erreur lors de la récupération de la récompense. Réessaye plus tard.")
            
    except Exception as e:
        logger.error(f"Erreur commande daily: {e}")
        await ctx.send("❌ Erreur lors de la récupération de la récompense.")

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
                    sender_balance = await conn.fetchval('SELECT balance FROM balances WHERE user_id = $1', sender)
                    if sender_balance is None:
                        sender_balance = 0
                    
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

@bot.command(name="debug")
async def debug(ctx):
    """Commande de debug (owner seulement)"""
    if ctx.author.id != OWNER_ID:
        await ctx.send("❌ Cette commande est réservée au propriétaire.")
        return
    
    try:
        if not db_pool:
            await ctx.send("❌ Pool de base de données non initialisé")
            return
        
        async with db_pool.acquire() as conn:
            # Test de connexion
            test = await conn.fetchval('SELECT 1')
            
            # Statistiques générales
            total_users = await conn.fetchval('SELECT COUNT(*) FROM balances') or 0
            total_money = await conn.fetchval('SELECT COALESCE(SUM(balance), 0) FROM balances') or 0
            active_users = await conn.fetchval('SELECT COUNT(*) FROM balances WHERE balance > 0') or 0
            
            # Ta balance
            my_balance = await conn.fetchval('SELECT balance FROM balances WHERE user_id = $1', OWNER_ID) or 0
            
            # Dernières activités (24h)
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
            recent_daily = await conn.fetchval('''
                SELECT COUNT(*) FROM daily_cooldowns 
                WHERE last_claim > $1::timestamptz
            ''', cutoff_time) or 0
            
            embed = discord.Embed(title="🔧 Debug Info", color=0x00ff00)
            embed.add_field(name="🔗 Connexion DB", value="✅ OK" if test == 1 else "❌ Erreur", inline=True)
            embed.add_field(name="👥 Utilisateurs totaux", value=f"{total_users:,}", inline=True)
            embed.add_field(name="💰 PrissBucks totaux", value=f"{total_money:,}", inline=True)
            embed.add_field(name="✅ Utilisateurs actifs", value=f"{active_users:,}", inline=True)
            embed.add_field(name="👑 Ta balance", value=f"{my_balance:,}", inline=True)
            embed.add_field(name="📅 Daily récentes (24h)", value=f"{recent_daily:,}", inline=True)
            
            # Info sur le pool
            pool_info = "N/A"
            if hasattr(db_pool, '_holders'):
                pool_info = f"{len(db_pool._holders)} connexions"
            embed.set_footer(text=f"Pool: {pool_info}")
            
            await ctx.send(embed=embed)
            
    except Exception as e:
        logger.error(f"Erreur debug: {e}")
        await ctx.send(f"❌ Erreur debug: {e}")

@bot.command(name="add_money")
async def add_money(ctx, member: discord.Member, amount: int):
    """Ajoute de l'argent à un utilisateur (owner seulement)"""
    if ctx.author.id != OWNER_ID:
        await ctx.send("❌ Cette commande est réservée au propriétaire.")
        return
        
    try:
        success = await update_balance(member.id, amount)
        if success:
            new_balance = await get_balance(member.id)
            await ctx.send(f"✅ **{amount:,} PrissBucks** ajoutés à {member.mention}. Nouveau solde: **{new_balance:,} PrissBucks**")
        else:
            await ctx.send("❌ Erreur lors de l'ajout de l'argent.")
    except Exception as e:
        logger.error(f"Erreur add_money: {e}")
        await ctx.send(f"❌ Erreur: {e}")

@bot.command(name="set_money")
async def set_money(ctx, member: discord.Member, amount: int):
    """Définit le solde exact d'un utilisateur (owner seulement)"""
    if ctx.author.id != OWNER_ID:
        await ctx.send("❌ Cette commande est réservée au propriétaire.")
        return
        
    try:
        success = await set_balance(member.id, amount)
        if success:
            await ctx.send(f"✅ Solde de {member.mention} défini à **{amount:,} PrissBucks**")
        else:
            await ctx.send("❌ Erreur lors de la modification du solde.")
    except Exception as e:
        logger.error(f"Erreur set_money: {e}")
        await ctx.send(f"❌ Erreur: {e}")

@bot.command(name="clean_db")
async def clean_db(ctx):
    """Nettoie la base de données (owner seulement) - VERSION CORRIGÉE"""
    if ctx.author.id != OWNER_ID:
        await ctx.send("❌ Cette commande est réservée au propriétaire.")
        return
    
    try:
        if not db_pool:
            await ctx.send("❌ Pool de base de données non initialisé")
            return
        
        async with db_pool.acquire() as conn:
            # Compter d'abord, puis supprimer
            count_daily = await conn.fetchval('SELECT COUNT(*) FROM daily_cooldowns WHERE last_claim IS NULL')
            count_msg = await conn.fetchval('SELECT COUNT(*) FROM message_cooldowns WHERE last_message IS NULL')
            count_balance = await conn.fetchval('SELECT COUNT(*) FROM balances WHERE balance IS NULL OR balance < 0')
            
            # Supprimer les entrées problématiques
            await conn.execute('DELETE FROM daily_cooldowns WHERE last_claim IS NULL')
            await conn.execute('DELETE FROM message_cooldowns WHERE last_message IS NULL')
            await conn.execute('DELETE FROM balances WHERE balance IS NULL')
            
            # Corriger les balances négatives
            await conn.execute('UPDATE balances SET balance = 0 WHERE balance < 0')
            
        await ctx.send(f"✅ Nettoyage terminé:\n- {count_daily or 0} daily cooldowns supprimés\n- {count_msg or 0} message cooldowns supprimés\n- {count_balance or 0} balances problématiques corrigées")
            
    except Exception as e:
        logger.error(f"Erreur clean_db: {e}")
        await ctx.send(f"❌ Erreur: {e}")

@bot.event
async def on_message(message):
    # Ignorer les messages du bot lui-même
    if message.author.bot or not db_pool:
        await bot.process_commands(message)
        return
    
    user_id = message.author.id
    now = datetime.now(timezone.utc)

    try:
        last_message_time = await get_message_cooldown(user_id)

        # Gestion de la timezone si nécessaire
        cooldown_expired = True
        if last_message_time:
            if last_message_time.tzinfo is None:
                last_message_time = last_message_time.replace(tzinfo=timezone.utc)
            elif last_message_time.tzinfo != timezone.utc:
                last_message_time = last_message_time.astimezone(timezone.utc)
            
            cooldown_expired = (now - last_message_time) >= timedelta(seconds=20)

        # Si pas de cooldown ou cooldown expiré (20 secondes)
        if cooldown_expired:
            # Utiliser une transaction pour éviter les race conditions
            try:
                async with db_pool.acquire() as conn:
                    async with conn.transaction():
                        # Vérifier à nouveau le cooldown dans la transaction
                        last_msg = await conn.fetchval(
                            'SELECT last_message FROM message_cooldowns WHERE user_id = $1', 
                            user_id
                        )
                        
                        if last_msg:
                            if last_msg.tzinfo is None:
                                last_msg = last_msg.replace(tzinfo=timezone.utc)
                            elif last_msg.tzinfo != timezone.utc:
                                last_msg = last_msg.astimezone(timezone.utc)
                            
                            if (now - last_msg) < timedelta(seconds=20):
                                # Cooldown encore actif, ne pas donner de récompense
                                await bot.process_commands(message)
                                return
                        
                        # Ajouter PrissBuck et mettre à jour cooldown
                        await conn.execute('''
                            INSERT INTO balances (user_id, balance, updated_at) VALUES ($1, 1, $2)
                            ON CONFLICT (user_id) DO UPDATE SET 
                            balance = balances.balance + 1,
                            updated_at = $2
                        ''', user_id, now)
                        
                        await conn.execute('''
                            INSERT INTO message_cooldowns (user_id, last_message) VALUES ($1, $2::timestamptz)
                            ON CONFLICT (user_id) DO UPDATE SET last_message = $2::timestamptz
                        ''', user_id, now)
                        
            except Exception as e:
                logger.error(f"Erreur transaction message pour user {user_id}: {e}")
                
    except Exception as e:
        logger.error(f"Erreur on_message pour user {user_id}: {e}")

    # Pour que les commandes fonctionnent toujours !
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    """Gestionnaire d'erreurs pour les commandes"""
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argument manquant: `{error.param}`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argument invalide. Vérifie la syntaxe de la commande.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"❌ Commande en cooldown. Réessaye dans {error.retry_after:.1f}s")
    else:
        logger.error(f"Erreur commande {ctx.command}: {error}")
        await ctx.send("❌ Une erreur inattendue est survenue.")

# Gestionnaire de fermeture propre
async def close_pool():
    """Ferme proprement le pool de connexions"""
    if db_pool:
        try:
            await db_pool.close()
            logger.info("Pool de connexions fermé proprement")
        except Exception as e:
            logger.error(f"Erreur fermeture pool: {e}")

@bot.event
async def on_disconnect():
    """Événement de déconnexion"""
    logger.info("Bot déconnecté")

async def shutdown():
    """Fonction de fermeture propre"""
    logger.info("Arrêt du bot en cours...")
    await close_pool()
    await bot.close()

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
            # Essayer de fermer le pool s'il existe encore
            if db_pool and not db_pool._closed:
                asyncio.get_event_loop().run_until_complete(close_pool())
        except Exception as e:
            logger.error(f"Erreur fermeture finale: {e}")
        
        print("🔴 Bot arrêté")