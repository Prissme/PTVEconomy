import discord
from discord.ext import commands
from datetime import datetime, timezone
import random
import os
from dotenv import load_dotenv
import asyncio
import logging
import db

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Charger les variables d'environnement
load_dotenv()

# Variables d'environnement
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")
PREFIX = os.getenv("PREFIX", "!")

# Vérification des variables critiques
if not TOKEN:
    logger.error("❌ DISCORD_TOKEN manquant dans le fichier .env")
    exit(1)

if not DATABASE_URL:
    logger.error("❌ DATABASE_URL manquant dans le fichier .env")
    exit(1)

# Configuration des intents
intents = discord.Intents.default()
intents.message_content = True  # Nécessaire pour les commandes préfixées
intents.guilds = True
intents.guild_messages = True

# Initialisation du bot
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
database = db.Database(dsn=DATABASE_URL)

@bot.event
async def on_ready():
    """Événement déclenché quand le bot est prêt"""
    logger.info(f"✅ {bot.user} est connecté et prêt !")
    logger.info(f"📊 Connecté à {len(bot.guilds)} serveur(s)")
    
    try:
        await database.connect()
        logger.info("✅ Base de données connectée avec succès")
    except Exception as e:
        logger.error(f"❌ Erreur de connexion à la base de données: {e}")

@bot.event
async def on_command_error(ctx, error):
    """Gestion globale des erreurs de commandes"""
    if isinstance(error, commands.CommandNotFound):
        return  # Ignorer les commandes inexistantes
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ **Argument manquant !**\nUtilise `{PREFIX}help` pour voir l'aide.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ **Argument invalide !**\nUtilise `{PREFIX}help` pour voir l'aide.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏰ **Cooldown !** Réessaye dans {error.retry_after:.1f} secondes.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ **Tu n'as pas les permissions nécessaires !**")
    else:
        logger.error(f"Erreur non gérée dans {ctx.command}: {error}")
        await ctx.send("❌ **Une erreur inattendue s'est produite.**")

# ==================== COMMANDES ÉCONOMIE ====================

@bot.command(name='balance', aliases=['bal', 'money'])
async def balance_cmd(ctx, member: discord.Member = None):
    """Affiche le solde d'un utilisateur"""
    target = member or ctx.author
    
    try:
        balance = await database.get_balance(target.id)
        
        embed = discord.Embed(
            title="💰 Solde",
            description=f"**{target.display_name}** possède **{balance:,}** pièces",
            color=0x00ff00 if balance > 0 else 0xff9900
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Erreur balance pour {target.id}: {e}")
        await ctx.send("❌ **Erreur lors de la récupération du solde.**")

@bot.command(name='give', aliases=['pay', 'transfer'])
@commands.cooldown(1, 5, commands.BucketType.user)  # 1 fois par 5 secondes
async def give_cmd(ctx, member: discord.Member, amount: int):
    """Donne des pièces à un autre utilisateur"""
    giver = ctx.author
    receiver = member
    
    # Validations
    if amount <= 0:
        await ctx.send("❌ **Le montant doit être positif !**")
        return
        
    if giver.id == receiver.id:
        await ctx.send("❌ **Tu ne peux pas te donner des pièces à toi-même !**")
        return
        
    if receiver.bot:
        await ctx.send("❌ **Tu ne peux pas donner des pièces à un bot !**")
        return

    try:
        # Vérifier le solde avant le transfert
        giver_balance = await database.get_balance(giver.id)
        if giver_balance < amount:
            await ctx.send(f"❌ **Solde insuffisant !**\nTu as {giver_balance:,} pièces mais tu essayes de donner {amount:,} pièces.")
            return

        # Effectuer le transfert
        success = await database.transfer(giver.id, receiver.id, amount)
        
        if success:
            embed = discord.Embed(
                title="💸 Transfert réussi !",
                description=f"**{giver.display_name}** a donné **{amount:,}** pièces à **{receiver.display_name}**",
                color=0x00ff00
            )
            embed.set_footer(text=f"Nouveau solde de {giver.display_name}: {giver_balance - amount:,} pièces")
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ **Échec du transfert. Solde insuffisant.**")
            
    except Exception as e:
        logger.error(f"Erreur give {giver.id} -> {receiver.id}: {e}")
        await ctx.send("❌ **Erreur lors du transfert.**")

@bot.command(name='dailyspin', aliases=['daily', 'spin'])
@commands.cooldown(1, 86400, commands.BucketType.user)  # 1 fois par jour
async def dailyspin_cmd(ctx):
    """Récupère tes pièces quotidiennes"""
    user_id = ctx.author.id
    now = datetime.now(timezone.utc)

    try:
        # Vérifier le dernier daily
        last_daily = await database.get_last_daily(user_id)
        
        if last_daily:
            delta = now - last_daily
            if delta.total_seconds() < 86400:
                remaining = 86400 - delta.total_seconds()
                hours = int(remaining // 3600)
                minutes = int((remaining % 3600) // 60)
                
                embed = discord.Embed(
                    title="⏰ Daily déjà récupéré !",
                    description=f"Tu pourras récupérer ton daily dans **{hours}h {minutes}min**",
                    color=0xff9900
                )
                await ctx.send(embed=embed)
                return

        # Générer la récompense
        base_reward = random.randint(50, 150)
        bonus_chance = random.randint(1, 100)
        
        # Chance de bonus (10% de chance)
        if bonus_chance <= 10:
            bonus = random.randint(50, 200)
            total_reward = base_reward + bonus
            bonus_text = f"\n🎉 **BONUS:** +{bonus} pièces !"
        else:
            total_reward = base_reward
            bonus_text = ""

        # Mettre à jour la base de données
        await database.update_balance(user_id, total_reward)
        await database.set_last_daily(user_id, now)

        # Afficher le résultat
        embed = discord.Embed(
            title="🎰 Daily Spin !",
            description=f"**{ctx.author.display_name}** a gagné **{total_reward:,}** pièces !{bonus_text}",
            color=0x00ff00
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.set_footer(text="Reviens demain pour ton prochain daily !")
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Erreur dailyspin pour {user_id}: {e}")
        await ctx.send("❌ **Erreur lors du daily spin.**")

@bot.command(name='leaderboard', aliases=['top', 'rich', 'lb'])
async def leaderboard_cmd(ctx, limit: int = 10):
    """Affiche le classement des plus riches"""
    if limit > 20:
        limit = 20
    elif limit < 1:
        limit = 10

    try:
        top_users = await database.get_top_users(limit)
        
        if not top_users:
            await ctx.send("❌ **Aucun utilisateur trouvé dans le classement.**")
            return

        embed = discord.Embed(
            title="🏆 Classement des plus riches",
            color=0xffd700
        )

        description = ""
        for i, (user_id, balance) in enumerate(top_users, 1):
            try:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                username = user.display_name if user else f"Utilisateur {user_id}"
            except:
                username = f"Utilisateur {user_id}"

            # Emojis pour le podium
            if i == 1:
                emoji = "🥇"
            elif i == 2:
                emoji = "🥈"
            elif i == 3:
                emoji = "🥉"
            else:
                emoji = f"`{i:2d}.`"

            description += f"{emoji} **{username}** - {balance:,} pièces\n"

        embed.description = description
        embed.set_footer(text=f"Top {len(top_users)} utilisateurs")
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Erreur leaderboard: {e}")
        await ctx.send("❌ **Erreur lors de l'affichage du classement.**")

# ==================== COMMANDES ADMIN ====================

@bot.command(name='addmoney', aliases=['addbal'])
@commands.is_owner()
async def addmoney_cmd(ctx, member: discord.Member, amount: int):
    """[OWNER] Ajoute des pièces à un utilisateur"""
    try:
        await database.update_balance(member.id, amount)
        embed = discord.Embed(
            title="💰 Argent ajouté",
            description=f"**{amount:,}** pièces ajoutées à **{member.display_name}**",
            color=0x00ff00
        )
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Erreur addmoney: {e}")
        await ctx.send("❌ **Erreur lors de l'ajout d'argent.**")

@bot.command(name='setmoney', aliases=['setbal'])
@commands.is_owner()
async def setmoney_cmd(ctx, member: discord.Member, amount: int):
    """[OWNER] Définit le solde exact d'un utilisateur"""
    try:
        await database.set_balance(member.id, amount)
        embed = discord.Embed(
            title="💰 Solde défini",
            description=f"Solde de **{member.display_name}** défini à **{amount:,}** pièces",
            color=0x00ff00
        )
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Erreur setmoney: {e}")
        await ctx.send("❌ **Erreur lors de la définition du solde.**")

# ==================== COMMANDE D'AIDE ====================

@bot.command(name='help', aliases=['h', 'aide'])
async def help_cmd(ctx):
    """Affiche l'aide du bot économie"""
    embed = discord.Embed(
        title="🤖 Bot Économie - Aide",
        description="Voici toutes les commandes disponibles :",
        color=0x0099ff
    )

    # Commandes principales
    embed.add_field(
        name="💰 Commandes Économie",
        value=f"`{PREFIX}balance [@user]` - Affiche le solde\n"
              f"`{PREFIX}give <@user> <montant>` - Donne des pièces\n"
              f"`{PREFIX}dailyspin` - Daily spin (50-150 pièces)\n"
              f"`{PREFIX}leaderboard [limite]` - Top des plus riches",
        inline=False
    )

    # Aliases
    embed.add_field(
        name="🔄 Aliases",
        value="`balance` → `bal`, `money`\n"
              "`give` → `pay`, `transfer`\n"
              "`dailyspin` → `daily`, `spin`\n"
              "`leaderboard` → `top`, `rich`, `lb`",
        inline=False
    )

    embed.set_footer(text=f"Préfixe: {PREFIX} | Développé avec discord.py")
    embed.set_thumbnail(url=bot.user.display_avatar.url)

    await ctx.send(embed=embed)

# ==================== ÉVÉNEMENTS ADDITIONNELS ====================

@bot.event
async def on_guild_join(guild):
    """Événement quand le bot rejoint un serveur"""
    logger.info(f"✅ Bot ajouté au serveur: {guild.name} ({guild.id})")

@bot.event
async def on_guild_remove(guild):
    """Événement quand le bot quitte un serveur"""
    logger.info(f"❌ Bot retiré du serveur: {guild.name} ({guild.id})")

# ==================== DÉMARRAGE ====================

async def main():
    """Fonction principale pour démarrer le bot"""
    try:
        async with bot:
            await bot.start(TOKEN)
    except KeyboardInterrupt:
        logger.info("👋 Arrêt du bot demandé par l'utilisateur")
    except Exception as e:
        logger.error(f"💥 Erreur fatale: {e}")
    finally:
        if database.pool:
            await database.close()
            logger.info("🔌 Connexion à la base fermée")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Au revoir !")
    except Exception as e:
        print(f"💥 Erreur lors du démarrage: {e}")