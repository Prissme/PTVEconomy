import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

OWNER_ID = 691351470272020501  # Ton Discord ID

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "balances.json"
DAILY_COOLDOWN_FILE = "daily_cooldowns.json"
MESSAGE_COOLDOWN_FILE = "message_cooldowns.json"

# Chargement des données
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        balances = json.load(f)
else:
    balances = {}

if os.path.exists(DAILY_COOLDOWN_FILE):
    with open(DAILY_COOLDOWN_FILE, "r") as f:
        daily_cooldowns = json.load(f)
else:
    daily_cooldowns = {}

if os.path.exists(MESSAGE_COOLDOWN_FILE):
    with open(MESSAGE_COOLDOWN_FILE, "r") as f:
        message_cooldowns = json.load(f)
else:
    message_cooldowns = {}

def save_balances():
    with open(DATA_FILE, "w") as f:
        json.dump(balances, f)

def save_daily_cooldowns():
    with open(DAILY_COOLDOWN_FILE, "w") as f:
        json.dump(daily_cooldowns, f)

def save_message_cooldowns():
    with open(MESSAGE_COOLDOWN_FILE, "w") as f:
        json.dump(message_cooldowns, f)

def get_balance(user_id):
    return balances.get(str(user_id), 0)

def update_balance(user_id, amount):
    balances[str(user_id)] = get_balance(user_id) + amount
    save_balances()

def get_daily_cooldown(user_id):
    ts_str = daily_cooldowns.get(str(user_id))
    if ts_str:
        return datetime.fromisoformat(ts_str)
    return None

def set_daily_cooldown(user_id):
    daily_cooldowns[str(user_id)] = datetime.utcnow().isoformat()
    save_daily_cooldowns()

def get_message_cooldown(user_id):
    ts_str = message_cooldowns.get(str(user_id))
    if ts_str:
        return datetime.fromisoformat(ts_str)
    return None

def set_message_cooldown(user_id):
    message_cooldowns[str(user_id)] = datetime.utcnow().isoformat()
    save_message_cooldowns()

async def fetch_username(user_id):
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
    await bot.tree.sync()  # sync slash commands

@bot.event
async def on_message(message):
    # Ignorer les messages du bot lui-même
    if message.author.bot:
        return
    
    user_id = message.author.id
    now = datetime.utcnow()

    last_message_time = get_message_cooldown(user_id)

    # Si cooldown actif et moins de 20 secondes depuis dernier message, ne rien faire
    if last_message_time and (now - last_message_time) < timedelta(seconds=20):
        pass
    else:
        update_balance(user_id, 1)  # +1 PrissBuck
        set_message_cooldown(user_id)

    # Pour que les commandes fonctionnent toujours !
    await bot.process_commands(message)

@bot.command(name="balance")
async def balance(ctx):
    bal = get_balance(ctx.author.id)
    await ctx.send(f"{ctx.author.mention}, tu as {bal} PrissBucks 💵")

@bot.command(name="daily")
async def daily(ctx):
    user_id = ctx.author.id
    now = datetime.utcnow()
    last_claim = get_daily_cooldown(user_id)

    if last_claim and now - last_claim < timedelta(hours=24):
        remaining = timedelta(hours=24) - (now - last_claim)
        heures = remaining.seconds // 3600
        minutes = (remaining.seconds % 3600) // 60
        await ctx.send(f"{ctx.author.mention}, tu as déjà récupéré ta récompense quotidienne. Reviens dans {heures}h{minutes}m ⏳")
        return

    gain = 50  # montant journalier
    update_balance(user_id, gain)
    set_daily_cooldown(user_id)
    await ctx.send(f"{ctx.author.mention}, tu as récupéré ta récompense quotidienne de {gain} PrissBucks 💵 !")

# Slash command /classement
@bot.tree.command(name="classement", description="Affiche le top 10 des détenteurs de PrissBucks 💵")
async def classement(interaction: discord.Interaction):
    if not balances:
        await interaction.response.send_message("Aucun PrissBucks trouvé pour le moment.", ephemeral=True)
        return

    sorted_balances = sorted(balances.items(), key=lambda item: item[1], reverse=True)
    top_10 = sorted_balances[:10]

    description = ""
    for i, (user_id_str, bal) in enumerate(top_10, start=1):
        user_id = int(user_id_str)
        username = await fetch_username(user_id)
        description += f"**{i}. {username}** — {bal} PrissBucks 💵\n"

    embed = discord.Embed(title="🏆 Classement des PrissBucks", description=description, color=0xFFD700)
    await interaction.response.send_message(embed=embed)

# Slash command /give
@bot.tree.command(name="give", description="Donne des PrissBucks à un membre (taxe 2%)")
@app_commands.describe(member="Le membre qui reçoit", amount="Le montant à donner")
async def give(interaction: discord.Interaction, member: discord.Member, amount: int):
    sender = interaction.user.id
    receiver = member.id
    sender_bal = get_balance(sender)

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

    update_balance(sender, -amount)
    update_balance(receiver, net_amount)
    update_balance(OWNER_ID, tax)

    await interaction.response.send_message(
        f"{interaction.user.mention} a donné {net_amount} PrissBucks 💵 à {member.mention} (taxe {tax} PrissBucks vers le propriétaire)."
    )

bot.run(TOKEN)