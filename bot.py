import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv
import logging
from datetime import datetime, timezone, timedelta
import random

# Import des fonctions DB
import db

# ------------------- CONFIG LOGS -------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ------------------- LOAD ENV -------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
OWNER_ID = 691351470272020501

# ------------------- DISCORD BOT -------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------- COMMANDES -------------------
@bot.tree.command(name="dailyspin", description="Tourne la roue pour gagner des PrissBucks !")
async def dailyspin(interaction: discord.Interaction):
    user_id = interaction.user.id
    now = datetime.now(timezone.utc)

    try:
        data = await db.get_dailyspin(user_id)

        # Vérif cooldown
        if data and data['last_spin']:
            elapsed = now - data['last_spin']
            if elapsed < timedelta(hours=24):
                remaining = timedelta(hours=24) - elapsed
                hours, remainder = divmod(int(remaining.total_seconds()), 3600)
                minutes = remainder // 60
                await interaction.response.send_message(
                    f"⏳ Tu dois attendre encore **{hours}h {minutes}m** avant de tourner à nouveau.",
                    ephemeral=True
                )
                return

        # Gestion streak
        streak = 1
        if data and data['last_spin']:
            if now - data['last_spin'] < timedelta(hours=48):
                streak = data['streak'] + 1

        # Récompense
        base_reward = random.randint(50, 200)
        if random.random() <= 0.05:  # 5% jackpot
            base_reward = random.randint(1000, 5000)

        bonus = streak * 20
        reward = base_reward + bonus

        # Update balance & dailyspin
        await db.add_balance(user_id, reward)
        await db.update_dailyspin(user_id, streak, now)

        # Réponse principale
        await interaction.response.send_message(
            f"🎰 {interaction.user.mention}, tu gagnes **{reward:,} PrissBucks** 💵\n"
            f"🔥 Streak actuel : **{streak}** jours (bonus {bonus} PB)"
        )

        # Annonce jackpot
        if base_reward >= 1000:
            await interaction.followup.send(
                f"🎉 {interaction.user.mention} vient de gagner **{reward:,} PrissBucks** au Daily Spin !!! 💰🔥"
            )

    except Exception as e:
        logger.error("Erreur dailyspin", exc_info=e)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Une erreur est survenue. Réessaie plus tard.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Une erreur est survenue. Réessaie plus tard.", ephemeral=True)


# ------------------- BOT READY -------------------
@bot.event
async def on_ready():
    logger.info(f"🤖 Connecté en tant que {bot.user}")
    if await db.init_database(DATABASE_URL):
        await bot.tree.sync()
        logger.info("✅ Base de données initialisée et commandes synchronisées !")

# ------------------- LANCEMENT -------------------
if __name__ == "__main__":
    if not TOKEN or not DATABASE_URL:
        logger.error("❌ TOKEN ou DATABASE_URL manquant dans .env")
        exit(1)
    bot.run(TOKEN)