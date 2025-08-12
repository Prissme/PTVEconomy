import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncpg
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
import logging
import asyncio
import random

# ------------------- CONFIG -------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

OWNER_ID = int(os.getenv("OWNER_ID", "691351470272020501"))  # fallback vers ton ID
DAILY_COOLDOWN_HOURS = 24
JACKPOT_ANNOUNCE_THRESHOLD = 1000  # annonce publique si gain >=

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

db_pool: asyncpg.pool.Pool | None = None

# ------------------- DATABASE INIT -------------------
async def init_database():
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
            command_timeout=60
        )
        logger.info("Pool de connexions créé")

        async with db_pool.acquire() as conn:
            # table balances
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS balances (
                    user_id BIGINT PRIMARY KEY,
                    balance BIGINT DEFAULT 0 CHECK (balance >= 0),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_balances_balance ON balances(balance DESC)')

            # table dailyspin
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS dailyspin (
                    user_id BIGINT PRIMARY KEY,
                    streak INTEGER DEFAULT 0,
                    last_spin TIMESTAMP WITH TIME ZONE
                )
            ''')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_dailyspin_last_spin ON dailyspin(last_spin)')

            # réparation simple
            await conn.execute('UPDATE balances SET balance = 0 WHERE balance < 0')

        return True
    except Exception as e:
        logger.error(f"Erreur init_database: {e}")
        return False

# ------------------- HELPERS -------------------
async def fetch_username(user_id: int) -> str:
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        return str(user)
    except Exception:
        return f"Utilisateur ({user_id})"

async def get_balance(user_id: int) -> int:
    if not db_pool:
        return 0
    try:
        async with db_pool.acquire() as conn:
            bal = await conn.fetchval('SELECT balance FROM balances WHERE user_id=$1', user_id)
            return max(0, bal) if bal is not None else 0
    except Exception as e:
        logger.error(f"Erreur get_balance({user_id}): {e}")
        return 0

async def change_balance_atomic(user_id: int, delta: int, conn: asyncpg.Connection, now: datetime):
    """
    Applique delta (peut être négatif) au solde d'un utilisateur de façon idempotente.
    Utiliser dans une transaction existante (conn).
    """
    # On utilise INSERT ... ON CONFLICT DO UPDATE pour créer la ligne si besoin
    await conn.execute('''
        INSERT INTO balances (user_id, balance, updated_at)
        VALUES ($1, GREATEST(0, $2), $3)
        ON CONFLICT (user_id) DO UPDATE
        SET balance = GREATEST(0, balances.balance + EXCLUDED.balance),
            updated_at = $3
    ''', user_id, delta, now)

# ------------------- COMMANDES PREFIX (legacy) -------------------
@bot.command(name="balance")
async def balance_cmd(ctx, member: discord.Member = None):
    """Affiche le solde d'un utilisateur (commande prefix)."""
    try:
        target = member or ctx.author
        bal = await get_balance(target.id)
        if target == ctx.author:
            await ctx.send(f"{ctx.author.mention}, tu as **{bal:,} PrissBucks** 💵")
        else:
            await ctx.send(f"{target.mention} a **{bal:,} PrissBucks** 💵")
    except Exception as e:
        logger.error(f"Erreur commande !balance: {e}")
        await ctx.send("❌ Erreur lors de la récupération du solde.")

# ------------------- SLASH COMMANDS -------------------
@bot.tree.command(name="classement", description="Affiche le top 10 des détenteurs de PrissBucks 💵")
async def classement(interaction: discord.Interaction):
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
        for i, rec in enumerate(results, start=1):
            username = await fetch_username(rec['user_id'])
            medal = medals[i-1] if i <= 3 else f"**{i}.**"
            description += f"{medal} {username} — **{rec['balance']:,} PrissBucks** 💵\n"

        embed = discord.Embed(
            title="🏆 Classement des PrissBucks",
            description=description,
            color=0xFFD700,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Mise à jour automatique")
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        logger.error(f"Erreur /classement: {e}")
        await interaction.response.send_message("❌ Erreur lors de la récupération du classement.", ephemeral=True)

@bot.tree.command(name="give", description="Donne des PrissBucks à un membre (taxe 2%)")
@app_commands.describe(member="Le membre qui reçoit", amount="Le montant à donner")
async def give(interaction: discord.Interaction, member: discord.Member, amount: int):
    try:
        sender = interaction.user.id
        receiver = member.id

        # validations
        if amount <= 0:
            await interaction.response.send_message("❌ Le montant doit être positif.", ephemeral=True)
            return
        if amount > 1_000_000:
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

        tax = max(1, int(amount * 0.02))
        net_amount = amount - tax
        now = datetime.now(timezone.utc)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                # Vérifier le solde du sender (lock)
                sender_balance = await conn.fetchval(
                    'SELECT COALESCE(balance,0) FROM balances WHERE user_id=$1 FOR UPDATE',
                    sender
                ) or 0

                if sender_balance < amount:
                    await interaction.response.send_message(
                        f"❌ Tu n'as que **{sender_balance:,} PrissBucks** 💵, tu ne peux pas donner **{amount:,}**.",
                        ephemeral=True
                    )
                    return

                # Appliquer les changements atomiquement
                await change_balance_atomic(sender, -amount, conn, now)
                await change_balance_atomic(receiver, net_amount, conn, now)
                if tax > 0:
                    await change_balance_atomic(OWNER_ID, tax, conn, now)

        await interaction.response.send_message(
            f"✅ {interaction.user.mention} a donné **{net_amount:,} PrissBucks** 💵 à {member.mention}\n"
            f"💰 Taxe prélevée: **{tax:,} PrissBucks**"
        )
    except Exception as e:
        logger.error(f"Erreur /give: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Erreur lors de la transaction.", ephemeral=True)

# ------------------- DAILY SPIN -------------------
@bot.tree.command(name="dailyspin", description="Tourne la roue quotidienne pour gagner des PrissBucks !")
async def dailyspin(interaction: discord.Interaction):
    """
    - Cooldown 24h
    - Streak : bonus +20 PB par jour consécutif
    - Jackpot rare (annonce publique)
    - Stocke last_spin et streak dans dailyspin
    """
    user_id = interaction.user.id
    now = datetime.now(timezone.utc)

    if not db_pool:
        await interaction.response.send_message("❌ Base de données non disponible.", ephemeral=True)
        return

    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow('SELECT streak, last_spin FROM dailyspin WHERE user_id=$1 FOR UPDATE', user_id)

                # cooldown check
                if row and row['last_spin']:
                    elapsed = now - row['last_spin']
                    if elapsed < timedelta(hours=DAILY_COOLDOWN_HOURS):
                        remaining = timedelta(hours=DAILY_COOLDOWN_HOURS) - elapsed
                        hours = remaining.seconds // 3600
                        minutes = (remaining.seconds // 60) % 60
                        await interaction.response.send_message(
                            f"⏳ Tu dois attendre encore **{hours}h {minutes}m** avant de tourner à nouveau.", ephemeral=True
                        )
                        return

                # déterminer streak
                streak = 1
                if row and row['last_spin']:
                    if now - row['last_spin'] <= timedelta(hours=DAILY_COOLDOWN_HOURS * 2):
                        # s'il vient dans la plage 24-48h, on considère consécutif (tolérance légère)
                        streak = row['streak'] + 1
                    else:
                        streak = 1

                # calcul récompense
                # base aléatoire avec renforcement intermittent
                roll = random.random()
                if roll <= 0.03:  # 3% jackpot
                    base_reward = random.randint(1000, 5000)
                elif roll <= 0.15:  # 12% prize mid
                    base_reward = random.randint(300, 999)
                else:
                    base_reward = random.randint(50, 299)

                reward = base_reward + (streak * 20)  # bonus streak

                # appliquer au solde
                await change_balance_atomic(user_id, reward, conn, now)

                # update dailyspin table
                await conn.execute('''
                    INSERT INTO dailyspin (user_id, streak, last_spin)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id) DO UPDATE
                    SET streak = $2, last_spin = $3
                ''', user_id, streak, now)

        # annonce publique si gros gain
        if reward >= JACKPOT_ANNOUNCE_THRESHOLD:
            try:
                # essayer d'envoyer dans le canal où la commande a été exécutée
                channel = interaction.channel
                if channel:
                    await channel.send(f"🎉 {interaction.user.mention} vient de gagner **{reward:,} PrissBucks** au Daily Spin !!! 💰🔥")
            except Exception as e:
                logger.warning(f"Impossible d'annoncer le jackpot: {e}")

        await interaction.response.send_message(
            f"🎰 {interaction.user.mention}, tu gagnes **{reward:,} PrissBucks** 💵\n"
            f"🔥 Streak actuel : **{streak}** jours (bonus {streak*20} PB)"
        )
    except Exception as e:
        logger.error(f"Erreur /dailyspin: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Erreur lors du Daily Spin.", ephemeral=True)

# ------------------- STREAKS LEADERBOARD -------------------
@bot.tree.command(name="streaks", description="Top 10 des meilleurs streaks au Daily Spin")
async def streaks(interaction: discord.Interaction):
    try:
        if not db_pool:
            await interaction.response.send_message("❌ Base de données non disponible.", ephemeral=True)
            return
        async with db_pool.acquire() as conn:
            results = await conn.fetch('''
                SELECT user_id, streak, last_spin FROM dailyspin
                WHERE streak > 0
                ORDER BY streak DESC, last_spin DESC
                LIMIT 10
            ''')
        if not results:
            await interaction.response.send_message("Aucun streak enregistré pour le moment.", ephemeral=True)
            return

        desc = ""
        medals = ["🥇", "🥈", "🥉"]
        for i, r in enumerate(results, start=1):
            name = await fetch_username(r['user_id'])
            medal = medals[i-1] if i <= 3 else f"**{i}.**"
            last = r['last_spin'].strftime("%Y-%m-%d %H:%M UTC") if r['last_spin'] else "—"
            desc += f"{medal} {name} — **{r['streak']}** jours (dernier spin: {last})\n"

        embed = discord.Embed(title="🔥 Top Streaks Daily Spin", description=desc, color=0x1ABC9C, timestamp=datetime.now(timezone.utc))
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        logger.error(f"Erreur /streaks: {e}")
        await interaction.response.send_message("❌ Erreur lors de la récupération des streaks.", ephemeral=True)

# ------------------- ERREUR HANDLERS -------------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argument manquant: `{error.param}`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argument invalide. Vérifie la syntaxe de la commande.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Membre introuvable. Assure-toi que le membre est sur ce serveur.")
    else:
        logger.error(f"Unhandled command error: {error}")
        await ctx.send("❌ Une erreur inattendue est survenue.")

@bot.event
async def on_application_command_error(interaction: discord.Interaction, error):
    logger.error(f"Unhandled app command error: {error}")
    if not interaction.response.is_done():
        await interaction.response.send_message("❌ Une erreur inattendue est survenue.", ephemeral=True)

# ------------------- START / SHUTDOWN -------------------
async def close_pool():
    global db_pool
    if db_pool and not db_pool._closed:
        try:
            await db_pool.close()
            logger.info("Pool fermé proprement")
        except Exception as e:
            logger.error(f"Erreur fermeture pool: {e}")

@bot.event
async def on_ready():
    logger.info(f"Connected as {bot.user} (ID: {bot.user.id})")
    ok = await init_database()
    if ok:
        try:
            await bot.tree.sync()
            logger.info("Commandes synchronisées")
        except Exception as e:
            logger.error(f"Erreur sync tree: {e}")
    else:
        logger.error("Initialisation DB échouée")

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
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(close_pool())
        except Exception as e:
            logger.error(f"Erreur fermeture finale: {e}")
        print("🔴 Bot arrêté")