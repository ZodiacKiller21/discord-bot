import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
import re
import asyncio
from datetime import datetime, timedelta

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="/", intents=intents)
warns = {}
TICKET_CATEGORY_NAME = "Tickets"
appeal_server_invite = "https://discord.gg/WVCRqH5c"  # Note: Fixed typo in "discord"
main_server_invite = "https://discord.gg/YBZAUEtP"
ticket_ping_role_ids = [1373722985785196716, 1373755756670881853]
banned_words = ["bitch", "nigga"]
appeal_channel_id = 1373375166385623142

# Anti-nuke/raid variables
member_join_times = {}
last_channel_creation = {}
last_role_creation = {}
last_ban = {}

# Anti-raid configuration
MAX_NEW_ACCOUNTS = 5  # Max new accounts (<7 days old) that can join within RAID_TIME_WINDOW
RAID_TIME_WINDOW = 10  # Seconds to monitor for raid-like behavior
NEW_ACCOUNT_AGE = 7  # Days to consider an account "new"

# Anti-nuke configuration
MAX_CHANNEL_CREATION = 3  # Max channels that can be created in NUKING_TIME_WINDOW
MAX_ROLE_CREATION = 3  # Max roles that can be created in NUKING_TIME_WINDOW
MAX_BANS = 3  # Max bans that can be issued in NUKING_TIME_WINDOW
NUKING_TIME_WINDOW = 10  # Seconds to monitor for nuking behavior

# Anti-link configuration
ALLOWED_DOMAINS = ["discord.com", "discord.gg", "tenor.com", "giphy.com", "imgur.com", "i.imgur.com"]
ALLOWED_ATTACHMENTS = [".png", ".jpg", ".jpeg", ".gif", ".webp"]


class AppealModal(ui.Modal, title='Ban Appeal'):
    appeal_reason = ui.TextInput(label='Why should we unban you?', style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        if appeal_channel_id:
            channel = bot.get_channel(appeal_channel_id)
            if channel:
                embed = discord.Embed(
                    title=f"New Ban Appeal - {interaction.user}",
                    description=f"**User ID:** {interaction.user.id}\n"
                                f"**Appeal Reason:** {self.appeal_reason}",
                    color=discord.Color.orange()
                )
                view = AppealReviewView(interaction.user.id)
                await channel.send(embed=embed, view=view)
                await interaction.response.send_message(
                    "✅ Your appeal has been submitted to the staff team.\n"
                    "You'll be notified about the decision soon.",
                    ephemeral=True
                )
                return
        await interaction.response.send_message(
            "⚠️ Appeal channel not configured. Please contact server staff directly.",
            ephemeral=True
        )


class AppealReviewView(ui.View):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id

    @ui.button(label="Accept Appeal", style=discord.ButtonStyle.green)
    async def accept_appeal(self, interaction: discord.Interaction, button: ui.Button):
        user = await bot.fetch_user(self.user_id)
        try:
            await interaction.guild.unban(user)
            await user.send("🎉 Your ban appeal has been accepted! You can now rejoin the server.")
            await interaction.response.send_message(
                f"✅ Successfully unbanned {user.mention}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed to unban user: {e}",
                ephemeral=True
            )

    @ui.button(label="Reject Appeal", style=discord.ButtonStyle.red)
    async def reject_appeal(self, interaction: discord.Interaction, button: ui.Button):
        user = await bot.fetch_user(self.user_id)
        try:
            await user.send("❌ Your ban appeal has been rejected by the staff team.")
            await interaction.response.send_message(
                f"✅ Appeal from {user.mention} has been rejected.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed to notify user: {e}",
                ephemeral=True
            )


@bot.event
async def on_ready():
    print(f"Bot is ready as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(e)
    cleanup_old_entries.start()


@tasks.loop(minutes=30)
async def cleanup_old_entries():
    """Clean up old entries in tracking dictionaries"""
    now = datetime.utcnow()
    # Clean member join times
    for member_id in list(member_join_times.keys()):
        if now - member_join_times[member_id] > timedelta(minutes=10):
            del member_join_times[member_id]
    # Clean channel creation times
    for user_id in list(last_channel_creation.keys()):
        if now - last_channel_creation[user_id] > timedelta(minutes=10):
            del last_channel_creation[user_id]
    # Clean role creation times
    for user_id in list(last_role_creation.keys()):
        if now - last_role_creation[user_id] > timedelta(minutes=10):
            del last_role_creation[user_id]
    # Clean ban times
    for user_id in list(last_ban.keys()):
        if now - last_ban[user_id] > timedelta(minutes=10):
            del last_ban[user_id]


# ==================== NEW FEATURES ====================

@bot.tree.command(name="dmall", description="DM all members in the server (Admin only)")
@app_commands.describe(message="Message to send to all members")
async def dmall(interaction: discord.Interaction, message: str):
    """Command to DM all members in the server (Admin only)"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You must be an administrator to use this command.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        "📨 Starting to DM all members. This may take a while...",
        ephemeral=True
    )

    success = 0
    failed = 0
    for member in interaction.guild.members:
        if member.bot:
            continue
        try:
            embed = discord.Embed(
                title=f"Message from {interaction.guild.name}",
                description=message,
                color=discord.Color.blue()
            )
            embed.set_footer(text="This is an automated message from the server staff")
            await member.send(embed=embed)
            success += 1
            await asyncio.sleep(1)  # Rate limiting
        except:
            failed += 1

    await interaction.followup.send(
        f"✅ DM broadcast completed!\n"
        f"• Successfully sent: {success}\n"
        f"• Failed to send: {failed}\n"
        "Note: Bots were automatically excluded from this broadcast.",
        ephemeral=True
    )


# ==================== ANTI-NUKE SYSTEM ====================

@bot.event
async def on_guild_channel_create(channel):
    """Monitor channel creation for nuking behavior"""
    now = datetime.utcnow()
    user = channel.guild.get_member(channel.creator_id)

    if not user or user.guild_permissions.administrator:
        return

    # Track channel creation
    if user.id in last_channel_creation:
        last_channel_creation[user.id].append(now)
        # Check if user is creating channels too quickly
        if len([t for t in last_channel_creation[user.id] if
                now - t < timedelta(seconds=NUKING_TIME_WINDOW)]) > MAX_CHANNEL_CREATION:
            try:
                await user.ban(reason="Possible nuke attempt (mass channel creation)")
                await channel.guild.system_channel.send(
                    f"🚨 **Anti-Nuke System**\n"
                    f"Banned {user.mention} for creating too many channels in a short time."
                )
                # Delete all channels created by this user recently
                for c in channel.guild.channels:
                    if c.creator_id == user.id and (now - c.created_at).total_seconds() < 300:
                        await c.delete(reason="Cleaning up after nuke attempt")
            except:
                pass
    else:
        last_channel_creation[user.id] = [now]


@bot.event
async def on_guild_role_create(role):
    """Monitor role creation for nuking behavior"""
    now = datetime.utcnow()
    audit_log = [entry async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create)]
    if not audit_log:
        return

    user = audit_log[0].user
    if user.guild_permissions.administrator:
        return

    # Track role creation
    if user.id in last_role_creation:
        last_role_creation[user.id].append(now)
        # Check if user is creating roles too quickly
        if len([t for t in last_role_creation[user.id] if
                now - t < timedelta(seconds=NUKING_TIME_WINDOW)]) > MAX_ROLE_CREATION:
            try:
                await user.ban(reason="Possible nuke attempt (mass role creation)")
                await role.guild.system_channel.send(
                    f"🚨 **Anti-Nuke System**\n"
                    f"Banned {user.mention} for creating too many roles in a short time."
                )
                # Delete all roles created by this user recently
                for r in role.guild.roles:
                    if r.name.startswith("@") and (now - r.created_at).total_seconds() < 300:
                        await r.delete(reason="Cleaning up after nuke attempt")
            except:
                pass
    else:
        last_role_creation[user.id] = [now]


@bot.event
async def on_member_ban(guild, user):
    """Monitor ban events for nuking behavior"""
    now = datetime.utcnow()
    audit_log = [entry async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban)]
    if not audit_log:
        return

    moderator = audit_log[0].user
    if moderator.guild_permissions.administrator:
        return

    # Track bans
    if moderator.id in last_ban:
        last_ban[moderator.id].append(now)
        # Check if user is banning too quickly
        if len([t for t in last_ban[moderator.id] if now - t < timedelta(seconds=NUKING_TIME_WINDOW)]) > MAX_BANS:
            try:
                await moderator.ban(reason="Possible nuke attempt (mass banning)")
                await guild.system_channel.send(
                    f"🚨 **Anti-Nuke System**\n"
                    f"Banned {moderator.mention} for banning too many members in a short time."
                )
            except:
                pass
    else:
        last_ban[moderator.id] = [now]


# ==================== ANTI-RAID SYSTEM ====================

@bot.event
async def on_member_join(member):
    """Monitor new members for raid-like behavior"""
    now = datetime.utcnow()
    account_age = (now - member.created_at).days

    # Track join times for all new members
    member_join_times[member.id] = now

    # Check if account is very new
    if account_age < NEW_ACCOUNT_AGE:
        # Count how many new accounts joined recently
        new_accounts = 0
        for join_time in member_join_times.values():
            if (now - join_time).total_seconds() < RAID_TIME_WINDOW:
                new_accounts += 1

        if new_accounts >= MAX_NEW_ACCOUNTS:
            # Possible raid detected
            try:
                await member.ban(reason=f"Anti-raid: New account ({account_age} days old) joining during possible raid")
                await member.guild.system_channel.send(
                    f"🚨 **Anti-Raid System**\n"
                    f"Banned {member.mention} (account age: {account_age} days) as part of possible raid.\n"
                    f"{new_accounts} new accounts joined in the last {RAID_TIME_WINDOW} seconds."
                )
            except:
                pass


# ==================== ANTI-LINK SYSTEM ====================

def contains_bad_links(content):
    """Check if message contains disallowed links"""
    # Skip if message is from staff
    # This would need to be implemented with proper permissions check

    # Common URL patterns
    url_pattern = re.compile(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w .-]*/?')
    urls = url_pattern.findall(content.lower())

    if not urls:
        return False

    for url in urls:
        domain = url.split('/')[2]
        if any(allowed in domain for allowed in ALLOWED_DOMAINS):
            continue
        return True

    return False


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Anti-bad words system
    if any(word in message.content.lower() for word in banned_words):
        try:
            await message.delete()
            await message.author.send(
                "⚠️ Your message contained banned language and was automatically deleted.\n"
                "As a result, you have been banned from the server.\n"
                "If this was a mistake, please contact server staff."
            )
        except:
            pass
        await message.guild.ban(message.author, reason="Used slurs")
        return

    # Anti-link system
    if contains_bad_links(message.content) and not message.author.guild_permissions.manage_messages:
        try:
            await message.delete()
            await message.author.send(
                "⚠️ Your message contained disallowed links and was automatically deleted.\n"
                "Only approved domains are allowed in this server.\n"
                "Repeated violations may result in a ban."
            )
        except:
            pass
        return

    await bot.process_commands(message)


# ==================== EXISTING COMMANDS ====================

@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Member to ban", reason="Reason for ban")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
    try:
        embed = discord.Embed(title="You've been banned!", description=f"Reason: {reason}", color=discord.Color.red())
        embed.add_field(name="Important",
                        value="Click one of the buttons below to either join our appeal server or appeal your ban directly.")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Join Appeal Server", url=appeal_server_invite))
        view.add_item(discord.ui.Button(label="Appeal Here", style=discord.ButtonStyle.green, custom_id="appeal_here"))
        await member.send(embed=embed, view=view)
    except:
        pass
    await member.ban(reason=reason)
    await interaction.response.send_message(
        f"🔨 {member.mention} has been banned for: {reason}\n"
        "The user has been notified with ban information and appeal options."
    )


@bot.tree.command(name="kick", description="Remove a member from the server")
@app_commands.describe(member="Member to kick", reason="Reason for kick")
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
    await member.kick(reason=reason)
    await interaction.response.send_message(
        f"👢 {member.mention} has been kicked for: {reason}\n"
        "They can rejoin using an invite link if they have one."
    )


@bot.tree.command(name="clear", description="Purge messages from this channel")
@app_commands.describe(amount="Number of messages to delete (0-100)")
async def clear(interaction: discord.Interaction, amount: int):
    if amount < 0 or amount > 100:
        await interaction.response.send_message(
            "⚠️ Invalid amount specified. Please enter a number between 1 and 100.",
            ephemeral=True
        )
        return
    await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(
        f"🧹 Successfully cleared {amount} messages from this channel.\n"
        "The chat history has been cleaned up as requested."
    )


@bot.tree.command(name="reminder", description="Set a personal reminder")
@app_commands.describe(time="Time like '1hr 2min 30sec'", message="Reminder message")
async def reminder(interaction: discord.Interaction, time: str, message: str):
    await interaction.response.send_message(
        "⏰ Your reminder has been set successfully!\n"
        f"I'll DM you in {time} with your reminder: '{message}'",
        ephemeral=True
    )
    seconds = 0
    matches = re.findall(r"(\d+)\s*(hr|h|min|m|sec|s)", time.lower())
    for val, unit in matches:
        val = int(val)
        if unit in ['hr', 'h']:
            seconds += val * 3600
        elif unit in ['min', 'm']:
            seconds += val * 60
        elif unit in ['sec', 's']:
            seconds += val
    await asyncio.sleep(seconds)
    await interaction.user.send(f"⏰ Reminder: {message}")


@bot.tree.command(name="warn", description="Issue a warning to a member")
@app_commands.describe(member="Member to warn", reason="Reason for warning")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    if member.id not in warns:
        warns[member.id] = []
    warns[member.id].append(reason)
    await interaction.response.send_message(
        f"⚠️ {member.mention} has been warned for: {reason}\n"
        f"They now have {len(warns[member.id])} warning(s). Continued violations may result in stronger action."
    )


@bot.tree.command(name="userinfo", description="View information about a member")
@app_commands.describe(member="User to get info about")
async def userinfo(interaction: discord.Interaction, member: discord.Member):
    embed = discord.Embed(title=f"User Info - {member}", color=discord.Color.blue())
    embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
    embed.add_field(name="Roles", value=", ".join([r.name for r in member.roles if r.name != "@everyone"]),
                    inline=False)
    warn_count = len(warns.get(member.id, []))
    embed.add_field(name="Warnings", value=str(warn_count), inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(
        embed=embed,
        content=f"📋 Here's the information you requested about {member.mention}"
    )


@bot.tree.command(name="say", description="Make the bot say something")
@app_commands.describe(message="Message to say")
async def say(interaction: discord.Interaction, message: str):
    await interaction.channel.send(message)
    await interaction.response.send_message(
        "📢 Your message has been delivered successfully!\n"
        "The bot has repeated your message in the channel as requested.",
        ephemeral=True
    )


@bot.tree.command(name="setticket", description="Set up the ticket system in a channel")
@app_commands.describe(channel="Channel to post the ticket panel in")
async def setticket(interaction: discord.Interaction, channel: discord.TextChannel):
    embed = discord.Embed(
        title="Need Staff Help?",
        description="Click the button below to create a private ticket channel\n"
                    "Our team will assist you as soon as possible!",
        color=discord.Color.green()
    )
    view = TicketPanel()
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(
        "✅ Ticket system has been successfully set up!\n"
        f"The ticket panel is now available in {channel.mention}",
        ephemeral=True
    )


class TicketPanel(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ui.Button(label="Create Ticket", style=discord.ButtonStyle.green, custom_id="create_ticket"))


class ManageRolesView(ui.View):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
        self.add_item(ui.Button(label="Give Role", custom_id="give_role", style=discord.ButtonStyle.primary))
        self.add_item(ui.Button(label="Remove Role", custom_id="remove_role", style=discord.ButtonStyle.danger))

    @ui.button(label="Give Role", custom_id="give_role", style=discord.ButtonStyle.primary)
    async def give_role_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id and not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "❌ You don't have permission to manage roles in this ticket.\n"
                "Only the ticket creator or staff can manage roles here.",
                ephemeral=True
            )
            return
        await interaction.response.send_message(
            "🔘 Please mention the role you want to give (e.g., @Helper)\n"
            "Tag the role in this channel to proceed.",
            ephemeral=True
        )

    @ui.button(label="Remove Role", custom_id="remove_role", style=discord.ButtonStyle.danger)
    async def remove_role_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id and not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "❌ You don't have permission to manage roles in this ticket.\n"
                "Only the ticket creator or staff can manage roles here.",
                ephemeral=True
            )
            return
        await interaction.response.send_message(
            "🔘 Please mention the role you want to remove (e.g., @Helper)\n"
            "Tag the role in this channel to proceed.",
            ephemeral=True
        )


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        if interaction.data["custom_id"] == "create_ticket":
            category = discord.utils.get(interaction.guild.categories, name=TICKET_CATEGORY_NAME)
            if not category:
                category = await interaction.guild.create_category(TICKET_CATEGORY_NAME)
            ticket_channel = await interaction.guild.create_text_channel(
                name=f"ticket-{interaction.user.name}",
                category=category,
                overwrites={
                    interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }
            )
            role_mentions = ' '.join(f"<@&{role_id}>" for role_id in ticket_ping_role_ids)
            await ticket_channel.send(
                f"🎫 {interaction.user.mention} created a ticket!\n"
                f"Staff will be with you shortly. {role_mentions}\n"
                "Please describe your issue in detail so we can help you better.",
                view=ManageRolesView(interaction.user.id)
            )
            await interaction.response.send_message(
                f"✅ Your ticket has been created at {ticket_channel.mention}\n"
                "Staff members have been notified and will assist you soon.",
                ephemeral=True
            )
        elif interaction.data["custom_id"] == "appeal_here":
            await interaction.response.send_modal(AppealModal())


bot.run("MTM2NzI5OTMxMTk5NzY4NTgwMA.GHjnEF.XsDrL6zP0t-wFtkdTJHpCOXTv1l_WUOxPIHWrc")