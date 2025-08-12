import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta

from db import create_pool, init_db, get_balance, update_balance, get_top, transfer_with_tax

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "691351470272020501"))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# pool will be set on startup
pool = None

COOLDOWN_FILE = "cooldowns.json"

# simple in-file cooldowns (server-side quick solution)
if os.path.exists(COOLDOWN_FILE := "cooldowns.json"):
    import json
    with open(COOLDOWN_FILE, "r") as f:
        cooldowns = json.load(f)
else:
    cooldowns = {}

def save_cooldowns():
    import json
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(cooldowns, f)

def get_cooldown(user_id):
    ts_str = cooldowns.get(str(user_id))
    if ts_str:
        return datetime.fromisoformat(ts_str)
    return None

def set_cooldown(user_id):
    cooldowns[str(user_id)] = datetime.utcnow().isoformat()
    save_cooldowns()

async def fetch_username(user_id):
    user = bot.get_user(user_id)
    if user:
        return str(user)
    try:
        user = await bot.fetch_user(user_id)
        return str(user)
    except Exception:
        return f"User ID {user_id}"

@bot.event
async def on_ready():
    global pool
    print(f"Connecté en tant que {bot.user}")
    pool = await create_pool()
    await init_db(pool)
    await bot.tree.sync()
    print("Pool DB ok, commandes synchronisées.")

@bot.command(name="balance")
async def balance_cmd(ctx):
    bal = await get_balance(pool, ctx.author.id)
    await ctx.send(f"{ctx.author.mention}, tu as {bal} PrissBucks 💵")

@bot.command(name="daily")
async def daily_cmd(ctx):
    user_id = ctx.author.id
    now = datetime.utcnow()
    last_claim = get_cooldown(user_id)

    if last_claim and now - last_claim < timedelta(hours=24):
        remaining = timedelta(hours=24) - (now - last_claim)
        heures = remaining.seconds // 3600
        minutes = (remaining.seconds % 3600) // 60
        await ctx.send(f"{ctx.author.mention}, tu as déjà récupéré ta récompense quotidienne. Reviens dans {heures}h{minutes}m ⏳")
        return

    gain = 50
    await update_balance(pool, user_id, gain)
    set_cooldown(user_id)
    await ctx.send(f"{ctx.author.mention}, tu as récupéré ta récompense quotidienne de {gain} PrissBucks 💵 !")

# Slash /give
@bot.tree.command(name="give", description="Donne des PrissBucks à un membre (taxe 2%)")
@app_commands.describe(member="Le membre qui reçoit", amount="Le montant à donner")
async def give(interaction: discord.Interaction, member: discord.Member, amount: int):
    sender = interaction.user.id
    receiver = member.id

    if amount <= 0:
        await interaction.response.send_message("Montant invalide.", ephemeral=True)
        return
    if sender == receiver:
        await interaction.response.send_message("Tu ne peux pas te donner des PrissBucks à toi-même.", ephemeral=True)
        return

    try:
        net, tax = await transfer_with_tax(pool, sender, receiver, amount, OWNER_ID, tax_rate=0.02)
    except ValueError:
        await interaction.response.send_message("Tu n’as pas assez de PrissBucks 💵.", ephemeral=True)
        return
    except Exception as e:
        await interaction.response.send_message(f"Erreur interne: {e}", ephemeral=True)
        return

    await interaction.response.send_message(f"{interaction.user.mention} a donné {net} PrissBucks 💵 à {member.mention} (taxe {tax} PrissBucks vers le propriétaire).")

# Slash /classement
@bot.tree.command(name="classement", description="Affiche le top 10 des détenteurs de PrissBucks 💵")
async def classement(interaction: discord.Interaction):
    top = await get_top(pool, limit=10)
    if not top:
        await interaction.response.send_message("Aucun PrissBucks trouvé pour le moment.", ephemeral=True)
        return

    description = ""
    for i, (uid, bal) in enumerate(top, start=1):
        username = await fetch_username(uid)
        description += f"**{i}. {username}** — {bal} PrissBucks 💵\n"

    embed = discord.Embed(title="🏆 Classement des PrissBucks", description=description, color=0xFFD700)
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_message(message):
    # Ignorer les messages du bot lui-même
    if message.author.bot:
        return
    
    user_id = message.author.id
    now = datetime.utcnow()

    last_message_time = get_cooldown(user_id)

    # Si cooldown actif et moins de 20 secondes depuis dernier message, ne rien faire
    if last_message_time and (now - last_message_time) < timedelta(seconds=20):
        pass
    else:
        update_balance(user_id, 1)  # +1 PrissBuck
        set_cooldown(user_id)

    # Pour que les commandes fonctionnent toujours !
    await bot.process_commands(message)

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN not set in environment")
    bot.run(TOKEN)