import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncpg
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import logging

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
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
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
                    last_claim TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS message_cooldowns (
                    user_id BIGINT PRIMARY KEY,
                    last_message TIMESTAMP WITH TIME ZONE,
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
        return 0
        
    try:
        async with db_pool.acquire() as conn:
            result = await conn.fetchval('SELECT balance FROM balances WHERE user_id = $1', user_id)
            return result if result is not None else 0
    except Exception as e:
        logger.error(f"Erreur get_balance pour user {user_id}: {e}")
        return 0

async def update_balance(user_id, amount):
    """Met à jour le solde d'un utilisateur"""
    if not db_pool:
        return False
        
    try:
        async with db_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO balances (user_id, balance, updated_at) VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET 
                balance = balances.balance + $2,
                updated_at = $3
            ''', user_id, amount, datetime.now(timezone.utc))
            
            # Empêcher les balances négatives (sauf pour les déductions légitimes)
            if amount < 0:
                # Vérifier que la balance ne devient pas négative
                new_balance = await conn.fetchval('SELECT balance FROM balances WHERE user_id = $1', user_id)
                if new_balance < 0:
                    await conn.execute('UPDATE balances SET balance = 0 WHERE user_id = $1', user_id)
                    return False  # Transaction échouée car solde insuffisant
            
        return True
    except Exception as e:
        logger.error(f"Erreur update_balance pour user {user_id}, amount {amount}: {e}")
        return False

async def set_balance(user_id, amount):
    """Définit le solde exact d'un utilisateur"""
    if not db_pool:
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
                INSERT INTO daily_cooldowns (user_id, last_claim) VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET last_claim = $2
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
                INSERT INTO message_cooldowns (user_id, last_message) VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET last_message = $2
            ''', user_id, now)
        return True
    except Exception as e:
        logger.error(f"Erreur set_message_cooldown pour user {user_id}: {e}")
        return False

async def fetch_username(user_id):
    """Récupère le nom d'utilisateur"""
    try:
        user = bot.get_user(user_id)
        if user:
            return str(user)
        user = await bot.fetch_user(user_id)
        return str(user)
    except Exception as e:
        logger.error(f"Erreur fetch_username pour user {user_id}: {e}")
        return f"User ID {user_id}"

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
            time_diff = now - last_claim
            if time_diff < timedelta(hours=24):
                remaining = timedelta(hours=24) - time_diff
                heures = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                await ctx.send(f"{ctx.author.mention}, tu as déjà récupéré ta récompense quotidienne. Reviens dans **{heures}h{minutes:02d}m** ⏳")
                return

        # Donner la récompense
        gain = 50
        balance_success = await update_balance(user_id, gain)
        cooldown_success = await set_daily_cooldown(user_id)
        
        if balance_success and cooldown_success:
            new_balance = await get_balance(user_id)
            await ctx.send(f"🎉 {ctx.author.mention}, tu as récupéré ta récompense quotidienne de **{gain} PrissBucks** 💵 !\n💰 Nouveau solde: **{new_balance:,} PrissBucks**")
        else:
            await ctx.send(f"❌ {ctx.author.mention}, erreur lors de la récupération de la récompense. Réessaye plus tard.")
            logger.error(f"Erreur daily pour {user_id}: balance_success={balance_success}, cooldown_success={cooldown_success}")
            
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

        sender_bal = await get_balance(sender)
        if sender_bal < amount:
            await interaction.response.send_message(f"❌ Tu n'as que **{sender_bal:,} PrissBucks** 💵, tu ne peux pas donner **{amount:,}**.", ephemeral=True)
            return

        # Calcul des montants
        tax = max(1, int(amount * 0.02))  # taxe 2%, minimum 1
        net_amount = amount - tax

        # Effectuer les transactions dans l'ordre correct
        sender_success = await update_balance(sender, -amount)
        if not sender_success:
            await interaction.response.send_message("❌ Solde insuffisant pour effectuer cette transaction.", ephemeral=True)
            return
            
        receiver_success = await update_balance(receiver, net_amount)
        tax_success = await update_balance(OWNER_ID, tax)
        
        if receiver_success and tax_success:
            await interaction.response.send_message(
                f"✅ {interaction.user.mention} a donné **{net_amount:,} PrissBucks** 💵 à {member.mention}\n"
                f"💰 Taxe prélevée: **{tax:,} PrissBucks**"
            )
        else:
            # Annuler la transaction du sender en cas d'échec
            await update_balance(sender, amount)
            await interaction.response.send_message("❌ Erreur lors de la transaction. Transaction annulée.", ephemeral=True)
            logger.error(f"Erreur give: receiver_success={receiver_success}, tax_success={tax_success}")
            
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
            
            # Dernières activités
            recent_daily = await conn.fetchval('''
                SELECT COUNT(*) FROM daily_cooldowns 
                WHERE last_claim > $1
            ''', datetime.now(timezone.utc) - timedelta(hours=24)) or 0
            
            embed = discord.Embed(title="🔧 Debug Info", color=0x00ff00)
            embed.add_field(name="🔗 Connexion DB", value="✅ OK" if test == 1 else "❌ Erreur", inline=True)
            embed.add_field(name="👥 Utilisateurs totaux", value=f"{total_users:,}", inline=True)
            embed.add_field(name="💰 PrissBucks totaux", value=f"{total_money:,}", inline=True)
            embed.add_field(name="✅ Utilisateurs actifs", value=f"{active_users:,}", inline=True)
            embed.add_field(name="👑 Ta balance", value=f"{my_balance:,}", inline=True)
            embed.add_field(name="📅 Daily récentes (24h)", value=f"{recent_daily:,}", inline=True)
            embed.set_footer(text=f"Pool: {db_pool._con_count if hasattr(db_pool, '_con_count') else 'N/A'} connexions")
            
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

        # Si pas de cooldown ou cooldown expiré (20 secondes)
        if not last_message_time or (now - last_message_time) >= timedelta(seconds=20):
            balance_success = await update_balance(user_id, 1)  # +1 PrissBuck
            cooldown_success = await set_message_cooldown(user_id)
            
            if not (balance_success and cooldown_success):
                logger.warning(f"Échec mise à jour message pour {user_id}")
                
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
    if db_pool:
        await db_pool.close()
        logger.info("Pool de connexions fermé")

@bot.event
async def on_disconnect():
    await close_pool()

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
        print("\n🛑 Arrêt du bot...")
    except Exception as e:
        logger.error(f"Erreur critique: {e}")
    finally:
        # Fermeture propre en cas d'arrêt
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(close_pool())
            else:
                asyncio.run(close_pool())
        except Exception as e:
            logger.error(f"Erreur fermeture: {e}")