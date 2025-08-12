import discord
from discord.ext import commands
from discord import app_commands
import os
import random
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import db
import logging

# ---------------- CONFIG ----------------
logging.basicConfig(level=logging.INFO)
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- EVENTS ----------------
@bot.event
async def on_ready():
    await db.init_database()
    await bot.tree.sync()
    logging.info(f"✅ Connecté en tant que {bot.user}")

# ---------------- !balance ----------------
@bot.command(name="balance", help="Affiche ton solde.")
async def balance_cmd(ctx, member: discord.Member = None):
    user = member or ctx.author
    balance = await db.get_balance(user.id)
    await ctx.send(f"💰 **{user.display_name}** possède **{balance:,} PB**")

# ---------------- /give ----------------
@bot.tree.command(name="give", description="Donne des PrissBucks à un autre joueur.")
@app_commands.describe(member="Le joueur à qui donner", amount="Montant à donner")
async def give_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    sender_id = interaction.user.id
    receiver_id = member.id

    if amount <= 0:
        await interaction.response.send_message("⚠️ Montant invalide.", ephemeral=True)
        return

    if sender_id == receiver_id:
        await interaction.response.send_message("⚠️ Tu ne peux pas te donner à toi-même.", ephemeral=True)
        return

    sender_balance = await db.get_balance(sender_id)
    if sender_balance < amount:
        await interaction.response.send_message("❌ Pas assez de PrissBucks.", ephemeral=True)
        return

    await db.update_balance(sender_id, -amount)
    await db.update_balance(receiver_id, amount)

    await interaction.response.send_message(
        f"💸 {interaction.user.mention} a donné **{amount:,} PB** à {member.mention} !"
    )

# ---------------- /dailyspin ----------------
@bot.tree.command(name="dailyspin", description="Tourne la roue pour gagner des PrissBucks (1 fois par 24h).")
async def dailyspin_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id
    now = datetime.now(timezone.utc)

    last_claim = await db.get_last_daily(user_id)
    if last_claim and now - last_claim < timedelta(hours=24):
        hours_left = 24 - (now - last_claim).seconds // 3600
        await interaction.response.send_message(
            f"⏳ Tu dois attendre encore **{hours_left}h** avant de rejouer.",
            ephemeral=True
        )
        return

    reward = random.randint(100, 1000)
    await db.update_balance(user_id, reward)
    await db.set_last_daily(user_id, now)

    await interaction.response.send_message(
        f"🎰 **Daily Spin** : Tu as gagné **{reward:,} PB** ! 🎉"
    )

# ---------------- RUN ----------------
if __name__ == "__main__":
    bot.run(TOKEN)