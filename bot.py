import discord
from discord.ext import commands
from datetime import datetime, timezone
import random
import os
from dotenv import load_dotenv
import asyncio
import logging
import math
import json
import db

# Import du serveur de santé
try:
    from health_server import HealthServer
    HEALTH_SERVER_AVAILABLE = True
except ImportError:
    HEALTH_SERVER_AVAILABLE = False
    logging.warning("⚠️ health_server.py non trouvé, pas de health check")

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

# ==================== COMMANDES ÉCONOMIE EXISTANTES ====================

@bot.command(name='balance', aliases=['bal', 'money'])
async def balance_cmd(ctx, member: discord.Member = None):
    """Affiche le solde d'un utilisateur"""
    target = member or ctx.author
    
    try:
        balance = await database.get_balance(target.id)
        
        embed = discord.Embed(
            title="💰 Solde",
            description=f"**{target.display_name}** possède **{balance:,}** PrissBucks",
            color=0x00ff00 if balance > 0 else 0xff9900
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Erreur balance pour {target.id}: {e}")
        await ctx.send("❌ **Erreur lors de la récupération du solde.**")

@bot.command(name='give', aliases=['pay', 'transfer'])
@commands.cooldown(1, 5, commands.BucketType.user)
async def give_cmd(ctx, member: discord.Member, amount: int):
    """Donne des pièces à un autre utilisateur"""
    giver = ctx.author
    receiver = member
    
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
        giver_balance = await database.get_balance(giver.id)
        if giver_balance < amount:
            await ctx.send(f"❌ **Solde insuffisant !**\nTu as {giver_balance:,} PrissBucks mais tu essayes de donner {amount:,} PrissBucks.")
            return

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
@commands.cooldown(1, 86400, commands.BucketType.user)
async def dailyspin_cmd(ctx):
    """Récupère tes pièces quotidiennes"""
    user_id = ctx.author.id
    now = datetime.now(timezone.utc)

    try:
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

        base_reward = random.randint(50, 150)
        bonus_chance = random.randint(1, 100)
        
        if bonus_chance <= 10:
            bonus = random.randint(50, 200)
            total_reward = base_reward + bonus
            bonus_text = f"\n🎉 **BONUS:** +{bonus} pièces !"
        else:
            total_reward = base_reward
            bonus_text = ""

        await database.update_balance(user_id, total_reward)
        await database.set_last_daily(user_id, now)

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

# ==================== NOUVELLES COMMANDES SHOP ====================

@bot.command(name='shop', aliases=['boutique', 'store'])
async def shop_cmd(ctx, page: int = 1):
    """Affiche la boutique avec pagination"""
    try:
        items = await database.get_shop_items(active_only=True)
        
        if not items:
            embed = discord.Embed(
                title="🛍️ Boutique PrissBucks",
                description="❌ **La boutique est vide pour le moment.**",
                color=0xff9900
            )
            await ctx.send(embed=embed)
            return
        
        # Pagination (5 items par page)
        items_per_page = 5
        total_pages = math.ceil(len(items) / items_per_page)
        
        if page < 1 or page > total_pages:
            await ctx.send(f"❌ **Page invalide !** Utilise une page entre 1 et {total_pages}.")
            return
        
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_items = items[start_idx:end_idx]
        
        embed = discord.Embed(
            title="🛍️ Boutique PrissBucks",
            description="Dépense tes PrissBucks pour des récompenses exclusives !",
            color=0x9932cc
        )
        
        for item in page_items:
            # Icône selon le type d'item
            icon = "🎭" if item["type"] == "role" else "📦"
            
            embed.add_field(
                name=f"{icon} **{item['name']}** - {item['price']:,} 💰",
                value=f"{item['description']}\n`{PREFIX}buy {item['id']}` pour acheter",
                inline=False
            )
        
        embed.set_footer(text=f"Page {page}/{total_pages} • {len(items)} item(s) disponible(s)")
        
        # Ajouter des boutons de navigation si nécessaire
        if total_pages > 1:
            embed.add_field(
                name="📄 Navigation",
                value=f"`{PREFIX}shop {page-1 if page > 1 else total_pages}` ← Page précédente\n"
                      f"`{PREFIX}shop {page+1 if page < total_pages else 1}` → Page suivante",
                inline=False
            )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Erreur shop: {e}")
        await ctx.send("❌ **Erreur lors de l'affichage de la boutique.**")

@bot.command(name='buy', aliases=['acheter', 'purchase'])
@commands.cooldown(1, 3, commands.BucketType.user)
async def buy_cmd(ctx, item_id: int):
    """Achète un item du shop"""
    user_id = ctx.author.id
    
    try:
        # Récupérer les infos de l'item
        item = await database.get_shop_item(item_id)
        if not item or not item["is_active"]:
            await ctx.send("❌ **Cet item n'existe pas ou n'est plus disponible.**")
            return
        
        # Effectuer l'achat (transaction atomique)
        success, message = await database.purchase_item(user_id, item_id)
        
        if not success:
            await ctx.send(f"❌ **Achat échoué :** {message}")
            return
        
        # Si c'est un rôle, l'attribuer
        if item["type"] == "role":
            try:
                role_id = item["data"].get("role_id")
                if role_id:
                    role = ctx.guild.get_role(int(role_id))
                    if role:
                        await ctx.author.add_roles(role)
                        role_text = f"\n🎭 **Rôle {role.name} attribué !**"
                    else:
                        role_text = "\n⚠️ **Rôle introuvable, contacte un admin.**"
                        logger.error(f"Rôle {role_id} introuvable pour l'item {item_id}")
                else:
                    role_text = "\n⚠️ **Erreur d'attribution du rôle.**"
            except Exception as e:
                logger.error(f"Erreur attribution rôle {item_id}: {e}")
                role_text = "\n⚠️ **Erreur lors de l'attribution du rôle.**"
        else:
            role_text = ""
        
        # Message de confirmation
        embed = discord.Embed(
            title="✅ Achat réussi !",
            description=f"**{ctx.author.display_name}** a acheté **{item['name']}** pour **{item['price']:,}** PrissBucks !{role_text}",
            color=0x00ff00
        )
        
        # Afficher le nouveau solde
        new_balance = await database.get_balance(user_id)
        embed.set_footer(text=f"Nouveau solde: {new_balance:,} PrissBucks")
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Erreur buy {user_id} -> {item_id}: {e}")
        await ctx.send("❌ **Erreur lors de l'achat.**")

@bot.command(name='inventory', aliases=['inv', 'mes-achats'])
async def inventory_cmd(ctx, member: discord.Member = None):
    """Affiche les achats d'un utilisateur"""
    target = member or ctx.author
    
    try:
        purchases = await database.get_user_purchases(target.id)
        
        if not purchases:
            embed = discord.Embed(
                title="📦 Inventaire vide",
                description=f"**{target.display_name}** n'a encore rien acheté dans la boutique.",
                color=0xff9900
            )
            embed.add_field(
                name="💡 Astuce",
                value=f"Utilise `{PREFIX}shop` pour voir les items disponibles !",
                inline=False
            )
            await ctx.send(embed=embed)
            return
        
        embed = discord.Embed(
            title=f"📦 Inventaire de {target.display_name}",
            description=f"**{len(purchases)}** item(s) possédé(s)",
            color=0x9932cc
        )
        
        total_spent = 0
        for purchase in purchases[:10]:  # Limiter à 10 items
            icon = "🎭" if purchase["type"] == "role" else "📦"
            date = purchase["purchase_date"].strftime("%d/%m/%Y")
            
            embed.add_field(
                name=f"{icon} {purchase['name']}",
                value=f"💰 **{purchase['price_paid']:,}** PrissBucks\n📅 Acheté le {date}",
                inline=True
            )
            total_spent += purchase["price_paid"]
        
        if len(purchases) > 10:
            embed.add_field(
                name="📄 ...",
                value=f"Et {len(purchases) - 10} autre(s) item(s)",
                inline=True
            )
        
        embed.set_footer(text=f"Total dépensé: {total_spent:,} PrissBucks")
        embed.set_thumbnail(url=target.display_avatar.url)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Erreur inventory {target.id}: {e}")
        await ctx.send("❌ **Erreur lors de l'affichage de l'inventaire.**")

# ==================== COMMANDES ADMIN SHOP ====================

@bot.command(name='additem')
@commands.has_permissions(administrator=True)
async def additem_cmd(ctx, price: int, role_input: str, *, name: str):
    """[ADMIN] Ajoute un rôle au shop"""
    if price <= 0:
        await ctx.send("❌ **Le prix doit être positif !**")
        return
    
    try:
        # Essayer de récupérer le rôle par ID ou mention
        role = None
        
        # Si c'est un ID numérique
        if role_input.isdigit():
            role = ctx.guild.get_role(int(role_input))
        # Si c'est une mention <@&ID>
        elif role_input.startswith('<@&') and role_input.endswith('>'):
            role_id = int(role_input[3:-1])
            role = ctx.guild.get_role(role_id)
        # Sinon essayer de trouver par nom
        else:
            role = discord.utils.get(ctx.guild.roles, name=role_input)
        
        if not role:
            await ctx.send(f"❌ **Rôle introuvable !**\n"
                          f"Utilisez l'une de ces méthodes :\n"
                          f"• `!additem {price} @RôleNom {name}`\n"
                          f"• `!additem {price} {role_input} {name}` (avec l'ID du rôle)\n"
                          f"• `!additem {price} \"Nom exact du rôle\" {name}`")
            return
        
        # Vérifier que le bot peut gérer ce rôle
        if role >= ctx.guild.me.top_role:
            await ctx.send("❌ **Je ne peux pas gérer ce rôle (hiérarchie) !**\n"
                          f"Le rôle {role.mention} est plus haut que mon rôle dans la hiérarchie.")
            return
        
        # Vérifier si ce rôle existe déjà dans le shop
        existing_items = await database.get_shop_items(active_only=False)
        for item in existing_items:
            if item.get('data', {}).get('role_id') == role.id and item.get('is_active'):
                await ctx.send(f"⚠️ **Ce rôle est déjà dans la boutique !**\n"
                              f"Item existant : **{item['name']}** (ID: {item['id']}) - {item['price']:,} PrissBucks")
                return
        
        # Créer une description personnalisée si pas fournie
        description = f"🎭 Obtenez le rôle {role.mention} avec tous ses privilèges !"
        if "PERM VOC" in name.upper():
            description += "\n🎤 Inclut les permissions vocales spéciales !"
        if "BOURGEOIS" in name.upper():
            description += "\n💎 Statut de prestige sur le serveur !"
        
        # Ajouter à la base
        item_id = await database.add_shop_item(
            name=name,
            description=description,
            price=price,
            item_type="role",
            data={"role_id": role.id}
        )
        
        embed = discord.Embed(
            title="✅ Item ajouté au shop !",
            color=0x00ff00
        )
        embed.add_field(name="📛 Nom", value=name, inline=True)
        embed.add_field(name="💰 Prix", value=f"{price:,} PrissBucks", inline=True)
        embed.add_field(name="🎭 Rôle", value=f"{role.mention} (`{role.id}`)", inline=True)
        embed.add_field(name="🆔 Item ID", value=f"`{item_id}`", inline=True)
        embed.add_field(name="📝 Description", value=description, inline=False)
        embed.set_footer(text="Les utilisateurs peuvent maintenant acheter cet item avec !buy " + str(item_id))
        
        await ctx.send(embed=embed)
        logger.info(f"Item ajouté au shop: {name} (rôle {role.name}, prix {price})")
        
    except ValueError as e:
        await ctx.send("❌ **ID de rôle invalide !** Utilisez un nombre valide.")
    except Exception as e:
        logger.error(f"Erreur additem: {e}")
        await ctx.send("❌ **Erreur lors de l'ajout de l'item.**")

@bot.command(name='removeitem')
@commands.has_permissions(administrator=True)
async def removeitem_cmd(ctx, item_id: int):
    """[ADMIN] Retire un item du shop"""
    try:
        # Vérifier que l'item existe
        item = await database.get_shop_item(item_id)
        if not item:
            await ctx.send("❌ **Cet item n'existe pas.**")
            return
        
        # Désactiver l'item
        success = await database.deactivate_shop_item(item_id)
        
        if success:
            embed = discord.Embed(
                title="✅ Item retiré du shop !",
                description=f"**{item['name']}** n'est plus disponible à l'achat.",
                color=0x00ff00
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ **Erreur lors de la suppression.**")
        
    except Exception as e:
        logger.error(f"Erreur removeitem: {e}")
        await ctx.send("❌ **Erreur lors de la suppression de l'item.**")

@bot.command(name='shopstats')
@commands.has_permissions(administrator=True)
async def shopstats_cmd(ctx):
    """[ADMIN] Affiche les statistiques du shop"""
    try:
        stats = await database.get_shop_stats()
        
        embed = discord.Embed(
            title="📊 Statistiques de la boutique",
            color=0x0099ff
        )
        
        # Statistiques générales
        embed.add_field(
            name="👥 Acheteurs uniques", 
            value=f"**{stats['unique_buyers']}** utilisateurs", 
            inline=True
        )
        embed.add_field(
            name="🛒 Total des achats", 
            value=f"**{stats['total_purchases']}** achats", 
            inline=True
        )
        embed.add_field(
            name="💰 Revenus totaux", 
            value=f"**{stats['total_revenue']:,}** PrissBucks", 
            inline=True
        )
        
        # Top des items
        if stats['top_items']:
            top_text = ""
            for i, item in enumerate(stats['top_items'][:5], 1):
                emoji = ["🥇", "🥈", "🥉", "🏅", "🏅"][i-1]
                top_text += f"{emoji} **{item['name']}** - {item['purchases']} vente(s)\n"
            
            embed.add_field(
                name="🏆 Top des ventes",
                value=top_text,
                inline=False
            )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Erreur shopstats: {e}")
        await ctx.send("❌ **Erreur lors de l'affichage des statistiques.**")

@bot.command(name='listshop')
@commands.has_permissions(administrator=True)
async def listshop_cmd(ctx):
    """[ADMIN] Liste tous les items du shop (actifs et inactifs)"""
    try:
        items = await database.get_shop_items(active_only=False)
        
        if not items:
            await ctx.send("❌ **Aucun item dans la base de données.**")
            return
        
        embed = discord.Embed(
            title="📋 Liste complète des items",
            color=0x0099ff
        )
        
        active_items = [item for item in items if item['is_active']]
        inactive_items = [item for item in items if not item['is_active']]
        
        # Items actifs
        if active_items:
            active_text = ""
            for item in active_items[:10]:
                icon = "🎭" if item["type"] == "role" else "📦"
                active_text += f"{icon} `{item['id']}` **{item['name']}** - {item['price']:,} 💰\n"
            
            embed.add_field(
                name=f"✅ Items actifs ({len(active_items)})",
                value=active_text,
                inline=False
            )
        
        # Items inactifs
        if inactive_items:
            inactive_text = ""
            for item in inactive_items[:5]:
                icon = "🎭" if item["type"] == "role" else "📦"
                inactive_text += f"{icon} `{item['id']}` ~~{item['name']}~~ - {item['price']:,} 💰\n"
            
            embed.add_field(
                name=f"❌ Items inactifs ({len(inactive_items)})",
                value=inactive_text,
                inline=False
            )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Erreur listshop: {e}")
        await ctx.send("❌ **Erreur lors de l'affichage de la liste.**")

# ==================== COMMANDES ADMIN EXISTANTES ====================

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

# ==================== COMMANDE D'AIDE MISE À JOUR ====================

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
    
    # Nouvelles commandes shop
    embed.add_field(
        name="🛍️ Commandes Boutique",
        value=f"`{PREFIX}shop [page]` - Affiche la boutique\n"
              f"`{PREFIX}buy <id>` - Achète un item\n"
              f"`{PREFIX}inventory [@user]` - Affiche l'inventaire",
        inline=False
    )
    
    # Commandes admin
    if ctx.author.guild_permissions.administrator:
        embed.add_field(
            name="👑 Commandes Admin",
            value=f"`{PREFIX}additem <prix> <@role> <nom>` - Ajoute un rôle au shop\n"
                  f"`{PREFIX}removeitem <id>` - Retire un item\n"
                  f"`{PREFIX}shopstats` - Statistiques du shop\n"
                  f"`{PREFIX}listshop` - Liste tous les items",
            inline=False
        )

    # Aliases
    embed.add_field(
        name="🔄 Aliases",
        value="`balance` → `bal`, `money`\n"
              "`give` → `pay`, `transfer`\n"
              "`dailyspin` → `daily`, `spin`\n"
              "`leaderboard` → `top`, `rich`, `lb`\n"
              "`shop` → `boutique`, `store`\n"
              "`buy` → `acheter`, `purchase`\n"
              "`inventory` → `inv`, `mes-achats`",
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

# ==================== GESTION D'ERREURS GLOBALE ====================

@bot.event
async def on_error(event, *args, **kwargs):
    """Gestion d'erreur globale pour éviter les crashs"""
    import traceback
    logger.error(f"Erreur dans l'événement {event}: {traceback.format_exc()}")

# ==================== DÉMARRAGE AVEC RESTART AUTOMATIQUE ====================

async def main():
    """Fonction principale pour démarrer le bot avec gestion de reconnexion"""
    max_retries = 5
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            logger.info(f"🚀 Tentative de connexion {retry_count + 1}/{max_retries}")
            async with bot:
                await bot.start(TOKEN)
        except KeyboardInterrupt:
            logger.info("👋 Arrêt du bot demandé par l'utilisateur")
            break
        except discord.ConnectionClosed:
            logger.warning("🔌 Connexion fermée, tentative de reconnexion...")
            retry_count += 1
            await asyncio.sleep(5)
        except discord.LoginFailure:
            logger.error("❌ Token invalide, arrêt du bot")
            break
        except Exception as e:
            logger.error(f"💥 Erreur fatale: {e}")
            retry_count += 1
            if retry_count < max_retries:
                logger.info(f"⏳ Redémarrage dans 10 secondes...")
                await asyncio.sleep(10)
            else:
                logger.error("❌ Nombre maximum de tentatives atteint")
        finally:
            if database.pool:
                try:
                    await database.close()
                    logger.info("🔌 Connexion à la base fermée")
                except:
                    pass

if __name__ == "__main__":
    async def run_bot_with_health():
        """Lance le bot avec le serveur de santé"""
        tasks = []
        
        # Tâche principale du bot
        bot_task = asyncio.create_task(main())
        tasks.append(bot_task)
        
        # Serveur de santé si disponible
        if HEALTH_SERVER_AVAILABLE:
            health_server = HealthServer()
            health_task = asyncio.create_task(health_server.run_forever())
            tasks.append(health_task)
        
        try:
            # Attendre que l'une des tâches se termine
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            
            # Annuler les tâches restantes
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        except KeyboardInterrupt:
            print("\n👋 Arrêt en cours...")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    
    try:
        asyncio.run(run_bot_with_health())
    except KeyboardInterrupt:
        print("\n👋 Au revoir !")
    except Exception as e:
        print(f"💥 Erreur lors du démarrage: {e}")