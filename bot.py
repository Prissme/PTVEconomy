import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncpg
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

OWNER_ID = 691351470272020501  # Ton Discord ID

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Pool de connexions à la base de données
db_pool = None
db_ready = False

async def init_database():
    """Initialise la base de données et crée les tables"""
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    
    async with db_pool.acquire() as conn:
        # Créer les tables si elles n'existent pas
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS balances (
                user_id BIGINT PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS daily_cooldowns (
                user_id BIGINT PRIMARY KEY,
                last_claim TIMESTAMP
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS message_cooldowns (
                user_id BIGINT PRIMARY KEY,
                last_message TIMESTAMP
            )
        ''')

async def get_balance(user_id):
    """Récupère le solde d'un utilisateur"""
    async with db_pool.acquire() as conn:
        result = await conn.fetchval('SELECT balance FROM balances WHERE user_id = $1', user_id)
        return result if result is not None else 0

async def update_balance(user_id, amount):
    """Met à jour le solde d'un utilisateur"""
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO balances (user_id, balance) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET balance = balances.balance + $2
        ''', user_id, amount)

async def get_daily_cooldown(user_id):
    """Récupère le cooldown daily d'un utilisateur"""
    async with db_pool.acquire() as conn:
        result = await conn.fetchval('SELECT last_claim FROM daily_cooldowns WHERE user_id = $1', user_id)
        return result

async def set_daily_cooldown(user_id):
    """Définit le cooldown daily d'un utilisateur"""
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO daily_cooldowns (user_id, last_claim) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET last_claim = $2
        ''', user_id, datetime.utcnow())

async def get_message_cooldown(user_id):
    """Récupère le cooldown message d'un utilisateur"""
    async with db_pool.acquire() as conn:
        result = await conn.fetchval('SELECT last_message FROM message_cooldowns WHERE user_id = $1', user_id)
        return result

async def set_message_cooldown(user_id):
    """Définit le cooldown message d'un utilisateur"""
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO message_cooldowns (user_id, last_message) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET last_message = $2
        ''', user_id, datetime.utcnow())

async def fetch_username(user_id):
    """Récupère le nom d'utilisateur"""
    user = bot.get_user(user_id)
    if user:
        return str(user)
    try:
        user = await bot.fetch_user(user_id)
        return str(user)
    except:
        return f"User ID {user_id}"

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")
    await init_database()
    await bot.tree.sync()
    print("Base de données initialisée et commandes synchronisées !")

@bot.command(name="balance")
async def balance(ctx):
    bal = await get_balance(ctx.author.id)
    await ctx.send(f"{ctx.author.mention}, tu as {bal} PrissBucks 💵")

@bot.command(name="daily")
async def daily(ctx):
    user_id = ctx.author.id
    now = datetime.utcnow()
    last_claim = await get_daily_cooldown(user_id)

    if last_claim and now - last_claim < timedelta(hours=24):
        remaining = timedelta(hours=24) - (now - last_claim)
        heures = remaining.seconds // 3600
        minutes = (remaining.seconds % 3600) // 60
        await ctx.send(f"{ctx.author.mention}, tu as déjà récupéré ta récompense quotidienne. Reviens dans {heures}h{minutes}m ⏳")
        return

    gain = 50  # montant journalier
    await update_balance(user_id, gain)
    await set_daily_cooldown(user_id)
    await ctx.send(f"{ctx.author.mention}, tu as récupéré ta récompense quotidienne de {gain} PrissBucks 💵 !")

@bot.tree.command(name="classement", description="Affiche le top 10 des détenteurs de PrissBucks 💵")
async def classement(interaction: discord.Interaction):
    async with db_pool.acquire() as conn:
        results = await conn.fetch('SELECT user_id, balance FROM balances ORDER BY balance DESC LIMIT 10')
    
    if not results:
        await interaction.response.send_message("Aucun PrissBucks trouvé pour le moment.", ephemeral=True)
        return

    description = ""
    for i, record in enumerate(results, start=1):
        user_id = record['user_id']
        balance = record['balance']
        username = await fetch_username(user_id)
        description += f"**{i}. {username}** — {balance} PrissBucks 💵\n"

    embed = discord.Embed(title="🏆 Classement des PrissBucks", description=description, color=0xFFD700)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="give", description="Donne des PrissBucks à un membre (taxe 2%)")
@app_commands.describe(member="Le membre qui reçoit", amount="Le montant à donner")
async def give(interaction: discord.Interaction, member: discord.Member, amount: int):
    sender = interaction.user.id
    receiver = member.id
    sender_bal = await get_balance(sender)

    if amount <= 0:
        await interaction.response.send_message("Montant invalide.", ephemeral=True)
        return
    if sender == receiver:
        await interaction.response.send_message("Tu ne peux pas te donner des PrissBucks à toi-même.", ephemeral=True)
        return
    if sender_bal < amount:
        await interaction.response.send_message("Tu n'as pas assez de PrissBucks 💵.", ephemeral=True)
        return

    tax = max(1, int(amount * 0.02))  # taxe 2%, minimum 1
    net_amount = amount - tax

    await update_balance(sender, -amount)
    await update_balance(receiver, net_amount)
    await update_balance(OWNER_ID, tax)

    await interaction.response.send_message(
        f"{interaction.user.mention} a donné {net_amount} PrissBucks 💵 à {member.mention} (taxe {tax} PrissBucks vers le propriétaire)."
    )

@bot.event
async def on_message(message):
    # Ignorer les messages du bot lui-même
    if message.author.bot:
        return
    
    user_id = message.author.id
    now = datetime.utcnow()

    last_message_time = await get_message_cooldown(user_id)

    # Si cooldown actif et moins de 20 secondes depuis dernier message, ne rien faire
    if last_message_time and (now - last_message_time) < timedelta(seconds=20):
        pass
    else:
        await update_balance(user_id, 1)  # +1 PrissBuck
        await set_message_cooldown(user_id)

    # Pour que les commandes fonctionnent toujours !
    await bot.process_commands(message)

bot.run(TOKEN)