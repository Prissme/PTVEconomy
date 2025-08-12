import discord
from discord.ext import commands
from datetime import datetime, timezone
import random
import os
from dotenv import load_dotenv
import db  # ton fichier db.py

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)

database = db.Database(dsn=DATABASE_URL)

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")
    await database.connect()

@bot.command(name='balance')
async def balance_cmd(ctx):
    user_id = ctx.author.id
    bal = await database.get_balance(user_id)
    await ctx.send(f"{ctx.author.mention}, ton solde est de {bal} pièces.")

@bot.command(name='give')
async def give_cmd(ctx, member: discord.Member, amount: int):
    giver_id = ctx.author.id
    receiver_id = member.id
    if amount <= 0:
        await ctx.send("Le montant doit être positif.")
        return
    success = await database.transfer(giver_id, receiver_id, amount)
    if success:
        await ctx.send(f"{ctx.author.mention} a donné {amount} pièces à {member.mention}.")
    else:
        await ctx.send("Tu n'as pas assez de pièces.")

@bot.command(name='dailyspin')
async def dailyspin_cmd(ctx):
    user_id = ctx.author.id
    now = datetime.now(timezone.utc)  # datetime aware UTC

    last_daily = await database.get_last_daily(user_id)
    if last_daily:
        delta = now - last_daily
        if delta.total_seconds() < 86400:
            await ctx.send("Tu as déjà fait ton spin quotidien aujourd'hui. Réessaie plus tard !")
            return

    reward = random.randint(10, 100)
    await database.update_balance(user_id, reward)
    await database.set_last_daily(user_id, now)
    await ctx.send(f"🎉 {ctx.author.mention}, tu as gagné {reward} pièces avec ton spin quotidien !")

bot.run(TOKEN)