# ============================================================
#  SECTION 1: IMPORTS, GLOBALS, CONSTANTS, DB, HELPERS
# ============================================================

import os
import random
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
import sqlite3
from discord import app_commands

reminders = {}

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True   # REQUIRED for bot visibility in member list

bot = commands.Bot(command_prefix="$", intents=intents)
tree = bot.tree
scheduler = AsyncIOScheduler(timezone="Europe/London")

# -----------------------------
# CONSTANTS
# -----------------------------
HYDRA_WARNING_CHANNEL_ID = 1461342242470887546
ANNOUNCE_CHANNEL_ID = 1461342242470887546
SUGGESTION_CHANNEL_ID = 1464216800651640893  # legacy fallback

ALLOWED_SUGGEST_BUTTON_CHANNELS = {
    1463963533640335423,
    1463963575780507669
}

SHARD_CHOICES = ["ancient", "void", "primal", "sacred"]

# -----------------------------
# SHARD RATES (GACHA SIM)
# -----------------------------
SHARD_RATES = {
    "ancient": {
        "💙 Rare": 91.5,
        "💜 Epic": 8,
        "🌟 Legendary": 0.5
    },
    "void": {
        "💙 Rare": 91.5,
        "💜 Epic": 8,
        "🌟 Legendary": 0.5
    },
    "primal": {
        "💙 Rare": 82.5,
        "💜 Epic": 16,
        "🌟 Legendary": 1,
        "🔥 Mythical": 0.5
    },
    "sacred": {
        "💙 Rare": 0,
        "💜 Epic": 94,
        "🌟 Legendary": 6
    }
}

BASE_RATES = {
    "ancient": {"epic": 8.0, "legendary": 0.5, "mythical": 0.0},
    "void": {"epic": 8.0, "legendary": 0.5, "mythical": 0.0},
    "primal": {"epic": 16.0, "legendary": 1.0, "mythical": 0.5},
    "sacred": {"epic": 94.0, "legendary": 6.0, "mythical": 0.0}
}

# ============================================================
#  SECTION 2: DATABASE SETUP & HELPERS
# ============================================================

conn = sqlite3.connect("mercy.db")
c = conn.cursor()

# -----------------------------
# MERCY TABLE
# -----------------------------
c.execute("""
CREATE TABLE IF NOT EXISTS mercy (
    user_id TEXT,
    shard_type TEXT,
    epic_pity INTEGER DEFAULT 0,
    legendary_pity INTEGER DEFAULT 0,
    mythical_pity INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, shard_type)
)
""")

# -----------------------------
# GUILD CHANNEL SETTINGS TABLE
# -----------------------------
c.execute("""
CREATE TABLE IF NOT EXISTS guild_channels (
    guild_id TEXT PRIMARY KEY,
    warning_channel_id INTEGER,
    suggestion_channel_id INTEGER,
    feedback_channel_id INTEGER,
    commands_channel_id INTEGER,
    mercy_channel_id INTEGER
)
""")

try:
    c.execute("ALTER TABLE guild_channels ADD COLUMN mercy_channel_id INTEGER")
    conn.commit()
except sqlite3.OperationalError:
    pass

conn.commit()

# -----------------------------
# MERCY CALCULATION FUNCTIONS
# -----------------------------

def calc_epic_chance(shard_type, pity):
    if shard_type in ("ancient", "void"):
        base = BASE_RATES[shard_type]["epic"]
        if pity <= 20:
            return base
        extra = pity - 20
        return min(100.0, base + extra * 2.0)
    return BASE_RATES[shard_type]["epic"]


def calc_legendary_chance(shard_type, pity):
    if shard_type in ("ancient", "void"):
        base = BASE_RATES[shard_type]["legendary"]
        if pity <= 200:
            return base
        extra = pity - 200
        return min(100.0, base + extra * 5.0)

    if shard_type == "primal":
        base = BASE_RATES["primal"]["legendary"]
        if pity <= 75:
            return base
        extra = pity - 75
        return min(100.0, base + extra * 1.0)

    if shard_type == "sacred":
        base = BASE_RATES["sacred"]["legendary"]
        if pity <= 12:
            return base
        extra = pity - 12
        return min(100.0, base + extra * 2.0)

    return BASE_RATES[shard_type]["legendary"]


def calc_mythical_chance(shard_type, pity):
    if shard_type == "primal":
        base = BASE_RATES["primal"]["mythical"]
        if pity <= 200:
            return base
        extra = pity - 200
        return min(100.0, base + extra * 10.0)
    return BASE_RATES[shard_type]["mythical"]

# -----------------------------
# DB HELPERS (MERCY + GUILD CHANNELS)
# -----------------------------

def get_mercy_row(user_id, shard_type):
    shard_type = shard_type.lower()
    c.execute(
        "SELECT epic_pity, legendary_pity, mythical_pity "
        "FROM mercy WHERE user_id=? AND shard_type=?",
        (str(user_id), shard_type)
    )
    row = c.fetchone()
    if row is None:
        c.execute(
            "INSERT INTO mercy (user_id, shard_type) VALUES (?, ?)",
            (str(user_id), shard_type)
        )
        conn.commit()
        return 0, 0, 0
    return row


def set_mercy_row(user_id, shard_type, epic, legendary, mythical):
    shard_type = shard_type.lower()
    c.execute("""
        INSERT INTO mercy (user_id, shard_type, epic_pity, legendary_pity, mythical_pity)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, shard_type) DO UPDATE SET
            epic_pity=excluded.epic_pity,
            legendary_pity=excluded.legendary_pity,
            mythical_pity=excluded.mythical_pity
    """, (str(user_id), shard_type, epic, legendary, mythical))
    conn.commit()


def ensure_guild_row(guild_id: int):
    c.execute("SELECT guild_id FROM guild_channels WHERE guild_id=?", (str(guild_id),))
    if c.fetchone() is None:
        c.execute(
            "INSERT INTO guild_channels (guild_id) VALUES (?)",
            (str(guild_id),)
        )
        conn.commit()


def set_guild_channel(guild_id: int, field: str, channel_id: int | None):
    ensure_guild_row(guild_id)
    if field not in (
        "warning_channel_id",
        "suggestion_channel_id",
        "feedback_channel_id",
        "commands_channel_id",
        "mercy_channel_id"
    ):
        return
    c.execute(
        f"UPDATE guild_channels SET {field}=? WHERE guild_id=?",
        (int(channel_id) if channel_id is not None else None, str(guild_id))
    )
    conn.commit()


def get_guild_channels(guild_id: int):
    c.execute("""
        SELECT warning_channel_id,
               suggestion_channel_id,
               feedback_channel_id,
               commands_channel_id,
               mercy_channel_id
        FROM guild_channels
        WHERE guild_id=?
    """, (str(guild_id),))
    row = c.fetchone()
    if row is None:
        return {
            "warning_channel_id": None,
            "suggestion_channel_id": None,
            "feedback_channel_id": None,
            "commands_channel_id": None,
            "mercy_channel_id": None
        }
    return {
        "warning_channel_id": row[0],
        "suggestion_channel_id": row[1],
        "feedback_channel_id": row[2],
        "commands_channel_id": row[3],
        "mercy_channel_id": row[4]
    }

def get_default_feedback_channel_id():
    c.execute("""
        SELECT feedback_channel_id
        FROM guild_channels
        WHERE feedback_channel_id IS NOT NULL
        LIMIT 1
    """)
    row = c.fetchone()
    if row and row[0]:
        return int(row[0])
    return SUGGESTION_CHANNEL_ID

def compute_readiness_color_and_flag(shard_type, legendary_chance, mythical_chance=None):
    if shard_type == "primal":
        relevant = max(legendary_chance, mythical_chance or 0.0)
    else:
        relevant = legendary_chance

    ready = False
    if shard_type == "primal":
        if (mythical_chance is not None and mythical_chance > 74.0) or legendary_chance > 74.0:
            ready = True
    else:
        if legendary_chance > 74.0:
            ready = True

    if ready:
        color = discord.Color.green()
        status = "🟢 **Ready to pull**"
    elif relevant > 20.0:
        color = discord.Color.orange()
        status = "🟡 Building up"
    else:
        color = discord.Color.red()
        status = "🔴 Low mercy"

    return color, ready, status

    # ============================================================
#  SECTION 3: ERROR HANDLER & SCHEDULER TASKS
# ============================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        msg = await ctx.send("Nice try but I am on cooldown :D")
        return await msg.delete(delay=30)
    raise error


async def send_weekly_warning():
    for guild in bot.guilds:
        channels = get_guild_channels(guild.id)
        channel_id = channels["warning_channel_id"]

        if channel_id is None:
            channel = bot.get_channel(HYDRA_WARNING_CHANNEL_ID)
            if channel and channel.guild.id == guild.id:
                target_channel = channel
            else:
                continue
        else:
            target_channel = guild.get_channel(channel_id)

        if target_channel:
            await target_channel.send(
                "@everyone 24 HOUR WARNING FOR HYDRA CLASH, "
                "Don't forget or you'll miss out on rewards!"
            )


async def send_chimera_warning():
    for guild in bot.guilds:
        channels = get_guild_channels(guild.id)
        channel_id = channels["warning_channel_id"]

        if channel_id is None:
            channel = bot.get_channel(HYDRA_WARNING_CHANNEL_ID)
            if channel and channel.guild.id == guild.id:
                target_channel = channel
            else:
                continue
        else:
            target_channel = guild.get_channel(channel_id)

        if target_channel:
            await target_channel.send(
                "@everyone 24 HOUR WARNING FOR CHIMERA CLASH, "
                "Don't forget or you'll miss out on rewards!"
            )

# ============================================================
#  SECTION 4: EVENT HANDLERS (READY, GUILD JOIN, MESSAGE)
# ============================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    channel = bot.get_channel(HYDRA_WARNING_CHANNEL_ID)
    print("Hydra warning channel resolved (fallback):", channel)

    try:
        scheduler.start()
    except Exception:
        pass

    scheduler.add_job(send_weekly_warning, "cron", day_of_week="tue", hour=10, minute=0)
    scheduler.add_job(send_chimera_warning, "cron", day_of_week="wed", hour=11, minute=0)

    # AUTO CLEANUP OF STALE SLASH COMMANDS
    try:
        desired_names = {cmd.name for cmd in bot.tree.walk_commands()}
        remote_cmds = await bot.tree.fetch_commands()

        for rc in remote_cmds:
            if rc.name not in desired_names:
                try:
                    await bot.tree.delete_command(rc.id)
                    print(f"[CLEANUP] Deleted stale command: /{rc.name}")
                except Exception as e:
                    print(f"[CLEANUP] Failed to delete /{rc.name}: {e}")
    except Exception as e:
        print(f"[CLEANUP] Error during slash command cleanup: {e}")

    try:
        await bot.tree.sync()
        print("Slash commands synced (after cleanup).")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")


@bot.event
async def on_guild_join(guild):
    channel = None
    for ch in guild.text_channels:
        if ch.permissions_for(guild.me).send_messages:
            channel = ch
            break

    if channel:
        await channel.send(
            "Hello everyone! I am **Hydra Companion**, a multi‑platform toolkit for RAID: Shadow Legends players.\n\n"
            "I provide accurate shard pity tracking, pull logging, and gacha simulation across:\n"
            "• **Desktop (Live Beta)**\n"
            "• **Android (Live Beta)**\n"
            "• **Discord**\n\n"
            "**Support Server**\n"
            "If you ever need help with the bot, want to report a bug, or just have questions, you can join the support server here:\n"
            "https://discord.gg/DuemMm57jr"
        )

# ============================================================
#  SECTION 5: VIEWS (BUTTONS, DM CONFIRMATION, SETUP WIZARD)
# ============================================================

class SuggestionConfirmView(discord.ui.View):
    def __init__(self, user_id, suggestion):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.suggestion = suggestion

    @discord.ui.button(label="Submit Anonymously", style=discord.ButtonStyle.green)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)

        feedback_channel_id = get_default_feedback_channel_id()
        channel = interaction.client.get_channel(feedback_channel_id)

        if not channel:
            return await interaction.response.edit_message(
                content="Feedback channel is not configured correctly.",
                view=None
            )

        embed = discord.Embed(
            title="💡 New Anonymous Suggestion (DM)",
            description=self.suggestion,
            color=discord.Color.green()
        )
        embed.set_footer(text="Anonymous submission")

        await channel.send(embed=embed)
        await interaction.response.edit_message(
            content="Your anonymous suggestion has been submitted.",
            view=None
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)

        await interaction.response.edit_message(
            content="Your suggestion has been cancelled.",
            view=None
        )


class MessageMeButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Message Me", style=discord.ButtonStyle.primary)
    async def message_me(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.user.send(
                "Hi! You can send me an anonymous suggestion here anytime."
            )
            await interaction.response.send_message(
                "I've sent you a DM.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I couldn't DM you! Please enable DMs from server members.",
                ephemeral=True
            )

# ============================================================
#  FIXED SETUP WIZARD — SAFE CHANNEL RESOLUTION
# ============================================================

class SetupBaseView(discord.ui.View):
    def __init__(self, owner_id: int, guild: discord.Guild, state: dict):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.guild = guild
        self.state = state

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This setup wizard is not for you.",
                ephemeral=True
            )
            return False
        return True


# -----------------------------
# SAFE CHANNEL RESOLUTION HELPER
# -----------------------------

def resolve_selected_channel(interaction: discord.Interaction, select):
    """
    Discord UI selects return STRING IDs, not channel objects.
    This function safely resolves them.
    """
    try:
        channel_id = int(select.values[0])
        return interaction.guild.get_channel(channel_id)
    except Exception:
        return None


# -----------------------------
# STEP 1 — COMMANDS CHANNEL
# -----------------------------

class CommandsChannelView(SetupBaseView):
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select the Commands Guide channel..."
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):

        channel = resolve_selected_channel(interaction, select)
        if channel is None:
            return await interaction.response.send_message(
                "I couldn't resolve that channel. Please try again.",
                ephemeral=True
            )

        set_guild_channel(self.guild.id, "commands_channel_id", channel.id)
        self.state["commands_channel"] = channel

        embed = build_commands_guide_embed()
        await channel.send(embed=embed)

        await interaction.response.edit_message(
            content=f"✅ Commands Guide channel set to {channel.mention}.",
            view=None
        )

        await start_mercy_step(interaction, self.state)


# -----------------------------
# STEP 2 — MERCY CHANNEL
# -----------------------------

class MercyChannelView(SetupBaseView):
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select the Mercy Guide channel..."
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):

        channel = resolve_selected_channel(interaction, select)
        if channel is None:
            return await interaction.response.send_message(
                "I couldn't resolve that channel. Please try again.",
                ephemeral=True
            )

        set_guild_channel(self.guild.id, "mercy_channel_id", channel.id)
        self.state["mercy_channel"] = channel

        embed = build_mercy_guide_embed()
        await channel.send(embed=embed)

        await interaction.response.edit_message(
            content=f"✅ Mercy Guide channel set to {channel.mention}.",
            view=None
        )

        await start_suggestion_step(interaction, self.state)


# -----------------------------
# STEP 3 — SUGGESTION CHANNEL (OPTIONAL)
# -----------------------------

class SuggestionChannelView(SetupBaseView):
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select the Suggestion channel (optional)..."
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):

        channel = resolve_selected_channel(interaction, select)
        if channel is None:
            return await interaction.response.send_message(
                "I couldn't resolve that channel. Please try again.",
                ephemeral=True
            )

        set_guild_channel(self.guild.id, "suggestion_channel_id", channel.id)
        self.state["suggestion_channel"] = channel

        embed = discord.Embed(
            title="💡 Anonymous Suggestions",
            description=(
                "Want to submit feedback privately?\n"
                "Click the button below and I'll open a DM where you can send your anonymous suggestion."
            ),
            color=discord.Color.green()
        )
        await channel.send(embed=embed, view=MessageMeButton())

        await interaction.response.edit_message(
            content=f"✅ Suggestion channel set to {channel.mention}.",
            view=None
        )

        await start_feedback_step(interaction, self.state)

    @discord.ui.button(label="Skip this step", style=discord.ButtonStyle.secondary)
    async def skip_step(self, interaction: discord.Interaction, button: discord.ui.Button):

        set_guild_channel(self.guild.id, "suggestion_channel_id", None)
        self.state["suggestion_channel"] = None

        await interaction.response.edit_message(
            content="⏭ Suggestion channel skipped.",
            view=None
        )

        await start_feedback_step(interaction, self.state)


# -----------------------------
# STEP 4 — FEEDBACK CHANNEL (OPTIONAL)
# -----------------------------

class FeedbackChannelView(SetupBaseView):
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select the Feedback channel (optional)..."
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):

        channel = resolve_selected_channel(interaction, select)
        if channel is None:
            return await interaction.response.send_message(
                "I couldn't resolve that channel. Please try again.",
                ephemeral=True
            )

        set_guild_channel(self.guild.id, "feedback_channel_id", channel.id)
        self.state["feedback_channel"] = channel

        await interaction.response.edit_message(
            content=f"✅ Feedback channel set to {channel.mention}.",
            view=None
        )

        await start_warning_step(interaction, self.state)

    @discord.ui.button(label="Skip this step", style=discord.ButtonStyle.secondary)
    async def skip_step(self, interaction: discord.Interaction, button: discord.ui.Button):

        set_guild_channel(self.guild.id, "feedback_channel_id", None)
        self.state["feedback_channel"] = None

        await interaction.response.edit_message(
            content="⏭ Feedback channel skipped.",
            view=None
        )

        await start_warning_step(interaction, self.state)


# -----------------------------
# STEP 5 — WARNING CHANNEL (REQUIRED)
# -----------------------------

class WarningChannelView(SetupBaseView):
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select the Hydra warning channel..."
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):

        channel = resolve_selected_channel(interaction, select)
        if channel is None:
            return await interaction.response.send_message(
                "I couldn't resolve that channel. Please try again.",
                ephemeral=True
            )

        set_guild_channel(self.guild.id, "warning_channel_id", channel.id)
        self.state["warning_channel"] = channel

        await interaction.response.edit_message(
            content=f"✅ Warning channel set to {channel.mention}.",
            view=None
        )

        await finish_setup_summary(interaction, self.state)

        # ============================================================
#  SECTION 6: on_message (ANONYMOUS SUGGESTIONS)
# ============================================================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # DM anonymous suggestion flow
    if isinstance(message.channel, discord.DMChannel):
        suggestion = message.content

        async with message.channel.typing():
            embed = discord.Embed(
                title="Confirm Anonymous Suggestion",
                description=(
                    "You wrote:\n\n"
                    f"**{suggestion}**\n\n"
                    "Would you like to submit this anonymously?"
                ),
                color=discord.Color.blue()
            )

            view = SuggestionConfirmView(message.author.id, suggestion)

            await message.author.send(embed=embed, view=view)
        return

    await bot.process_commands(message)

# ============================================================
#  SECTION 7: PREFIX COMMANDS
# ============================================================

@bot.command()
async def test(ctx):
    await ctx.message.delete()
    await ctx.send("Hydra warning test successful.")

@bot.command()
async def chests(ctx):
    message = (
        "**Hydra Chest Requirements**\n"
        "Normal – Over 6.66M\n"
        "Hard – Over 20.4M\n"
        "Brutal – Over 29.4M\n"
        "Nightmare – Over 36.6M"
    )
    await ctx.send(message)
    await ctx.message.delete()

@bot.command(name="support")
async def support_prefix(ctx):
    await ctx.send(
        "**Support Server**\n"
        "If you need help with Hydra Companion, join here:\n"
        "https://discord.gg/DuemMm57jr"
    )

@bot.command(name="developer")
async def developer_prefix(ctx):
    await ctx.send(
        "**Hydra Companion Developer Resources**\n\n"
        "**GitHub Profile:** https://github.com/sketeraid\n"
        "**Desktop App (Beta):** https://github.com/sketeraid/HydraCompanionApp\n"
        "**Discord Bot:** https://github.com/sketeraid/HydraCompanion-Discord-Bot\n"
        "**Android App (Beta):** https://github.com/sketeraid/HydraCompanionAndroidAPK"
    )

# -----------------------------
# REMINDER SYSTEM (PREFIX)
# -----------------------------

@bot.command()
async def remindme(ctx, time: str, *, reminder: str = None):
    await ctx.message.delete()

    if reminder is None:
        await ctx.send(
            "You need to tell me what to remind you about.\n"
            "Example: `$remindme 10m take the bins out`"
        )
        return

    unit = time[-1]
    amount = time[:-1]

    if not amount.isdigit():
        await ctx.send("Time must be a number followed by m/h/d (e.g., 10m, 2h).")
        return

    amount = int(amount)

    if unit == "m":
        seconds = amount * 60
    elif unit == "h":
        seconds = amount * 3600
    elif unit == "d":
        seconds = amount * 86400
    else:
        await ctx.send("Invalid time unit. Use m, h, or d.")
        return

    user_id = ctx.author.id
    if user_id not in reminders:
        reminders[user_id] = []

    reminder_id = len(reminders[user_id]) + 1
    reminders[user_id].append({
        "id": reminder_id,
        "text": reminder,
        "time": time
    })

    await ctx.send(f"⏰ Reminder **#{reminder_id}** set for **{time}**.")

    await asyncio.sleep(seconds)

    await ctx.send(f"{ctx.author.mention} 🔔 Reminder #{reminder_id}: **{reminder}**")

    reminders[user_id] = [r for r in reminders[user_id] if r["id"] != reminder_id]

@bot.command(name="reminders")
async def list_reminders(ctx):
    await ctx.message.delete()

    user_id = ctx.author.id

    if user_id not in reminders or len(reminders[user_id]) == 0:
        await ctx.send("You have no active reminders.")
        return

    message = "**Your Active Reminders:**\n"
    for r in reminders[user_id]:
        message += f"• #{r['id']} – {r['text']} (in {r['time']})\n"

    await ctx.send(message)

@bot.command()
async def cancelreminder(ctx, reminder_id: int):
    await ctx.message.delete()

    user_id = ctx.author.id

    if user_id not in reminders or len(reminders[user_id]) == 0:
        await ctx.send("You have no reminders to cancel.")
        return

    before = len(reminders[user_id])
    reminders[user_id] = [r for r in reminders[user_id] if r["id"] != reminder_id]
    after = len(reminders[user_id])

    if before == after:
        await ctx.send(f"No reminder found with ID #{reminder_id}.")
    else:
        await ctx.send(f"❎ Reminder #{reminder_id} cancelled.")

# -----------------------------
# SHOULD I PULL? (PREFIX)
# -----------------------------

@bot.command(name="pull")
async def should_i_pull(ctx, *, event: str = None):
    await ctx.message.delete(delay=15)

    yes_responses = [
        "Yes — send it. Fortune favours the bold.",
        "Absolutely. This shard is calling your name.",
        "Yep. You will regret skipping more than pulling."
    ]

    no_responses = [
        "No — save your resources. Trust me.",
        "Skip. This shard is not worth the pain.",
        "Not this one. Your future self will thank you."
    ]

    decision = random.choice(["yes", "no"])

    if decision == "yes":
        colour = discord.Color.green()
        answer = random.choice(yes_responses)
    else:
        colour = discord.Color.red()
        answer = random.choice(no_responses)

    embed = discord.Embed(
        title="🎲 Should you pull?",
        description=answer,
        color=colour
    )

    embed.add_field(name="Requested by", value=ctx.author.mention, inline=False)

    if event:
        embed.add_field(name="Event", value=event, inline=False)

    embed.set_footer(text="Decision generated by HydraBot RNG")

    await ctx.send(embed=embed)

# -----------------------------
# GACHA SIMULATOR (PREFIX)
# -----------------------------

def roll_from_rates(rates: dict):
    r = random.uniform(0, 100)
    cumulative = 0
    for rarity, chance in rates.items():
        cumulative += chance
        if r <= cumulative:
            return rarity
    return list(rates.keys())[-1]

@bot.command(name="sim")
@commands.cooldown(1, 30, commands.BucketType.user)
async def gacha_sim(ctx, shard_type: str = None):
    await ctx.message.delete(delay=30)

    if shard_type is None:
        msg = await ctx.send("Please specify a shard type: ancient, void, primal, sacred.")
        return await msg.delete(delay=10)

    shard_type = shard_type.lower()

    if shard_type not in SHARD_RATES:
        msg = await ctx.send("Invalid shard type. Choose: ancient, void, primal, sacred.")
        return await msg.delete(delay=10)

    rates = SHARD_RATES[shard_type]

    results = [roll_from_rates(rates) for _ in range(10)]

    summary = {}
    for rarity in results:
        summary[rarity] = summary.get(rarity, 0) + 1

    embed = discord.Embed(
        title=f"🎰 {shard_type.capitalize()} Shard — 10 Pulls",
        color=discord.Color.gold()
    )

    embed.add_field(
        name="Results",
        value="\n".join(results),
        inline=False
    )

    summary_text = "\n".join([f"{rarity}: **{count}**" for rarity, count in summary.items()])
    embed.add_field(name="Summary", value=summary_text, inline=False)

    embed.add_field(name="Requested by", value=ctx.author.mention, inline=False)

    embed.set_footer(text="HydraBot Simulator")

    await ctx.send(embed=embed)

# -----------------------------
# MERCY PREFIX COMMANDS
# -----------------------------

@bot.command(name="mercy")
async def mercy_cmd(ctx, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await ctx.send("Invalid shard type. Use: ancient, void, primal, sacred.")

    epic, legendary, mythical = get_mercy_row(ctx.author.id, shard_type)

    embed = discord.Embed(
        title=f"{shard_type.capitalize()} Mercy Status",
        color=discord.Color.gold()
    )

    if shard_type in ("ancient", "void"):
        epic_chance = calc_epic_chance(shard_type, epic)
        embed.add_field(
            name="Epic",
            value=f"Pity: **{epic}**\nChance: **{epic_chance:.2f}%**",
            inline=False
        )

    legendary_chance = calc_legendary_chance(shard_type, legendary)
    embed.add_field(
        name="Legendary",
        value=f"Pity: **{legendary}**\nChance: **{legendary_chance:.2f}%**",
        inline=False
    )

    mythical_chance = None
    if shard_type == "primal":
        mythical_chance = calc_mythical_chance(shard_type, mythical)
        embed.add_field(
            name="Mythical",
            value=f"Pity: **{mythical}**\nChance: **{mythical_chance:.2f}%**",
            inline=False
        )

    color, ready, status = compute_readiness_color_and_flag(shard_type, legendary_chance, mythical_chance)
    embed.color = color
    if ready:
        embed.add_field(
            name="🔥 Ready?",
            value="Looks like you are ready to pull :P",
            inline=False
        )

    await ctx.send(embed=embed)

    # ============================================================
#  SECTION 7 (continued): PREFIX ADMIN COMMANDS
# ============================================================

@bot.command(name="addpull")
async def add_pull_cmd(ctx, shard_type: str, amount: int):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await ctx.send("Invalid shard type. Use: ancient, void, primal, sacred.")

    if amount <= 0:
        return await ctx.send("Amount must be a positive number.")

    epic, legendary, mythical = get_mercy_row(ctx.author.id, shard_type)

    if shard_type in ("ancient", "void"):
        epic += amount

    legendary += amount

    if shard_type == "primal":
        mythical += amount

    set_mercy_row(ctx.author.id, shard_type, epic, legendary, mythical)

    msg = f"{ctx.author.mention}, added **{amount}** pulls to your **{shard_type}** mercy.\n"

    if shard_type in ("ancient", "void"):
        msg += f"Epic: **{epic}**, "

    msg += f"Legendary: **{legendary}**"

    if shard_type == "primal":
        msg += f", Mythical: **{mythical}**"

    await ctx.send(msg)


# -----------------------------
# PURGE COMMAND (PREFIX ADMIN)
# -----------------------------

@bot.command(name="purge")
@commands.has_permissions(administrator=True)
async def purge_cmd(ctx, amount: int):
    await ctx.message.delete()

    if amount <= 0:
        warn = await ctx.send("Please enter a number greater than 0.")
        return await warn.delete(delay=5)

    deleted = await ctx.channel.purge(limit=amount)

    confirm = await ctx.send(f"Deleted {len(deleted)} messages.")
    await confirm.delete(delay=5)


@purge_cmd.error
async def purge_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        responses = [
            "Nuh uh, I do not think so, peasant XD",
            "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExMHNjeGQ0YXFuZTVmb3VrbnkzdTZpOGhzcDVrZzlqYjZpemNyYXdyZCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/Ju7l5y9osyymQ/giphy.gif"
        ]
        choice = random.choice(responses)
        await ctx.send(choice)


# -----------------------------
# ANNOUNCE COMMAND (PREFIX ADMIN)
# -----------------------------

@bot.command(name="announce")
@commands.has_permissions(administrator=True)
async def announce_cmd(ctx, *, message: str):
    await ctx.message.delete()

    channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)

    embed = discord.Embed(
        title="📢 Announcement",
        description=message,
        color=discord.Color.blue()
    )

    embed.set_footer(
        text=f"Posted by {ctx.author}",
        icon_url=ctx.author.avatar.url if ctx.author.avatar else None
    )

    embed.timestamp = discord.utils.utcnow()

    await channel.send(embed=embed)


@announce_cmd.error
async def announce_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        responses = [
            "Nuh uh, I do not think so, peasant XD",
            "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExMHNjeGQ0YXFuZTVmb3VrbnkzdTZpOGhzcDVrZzlqYjZpemNyYXdyZCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/Ju7l5y9osyymQ/giphy.gif"
        ]
        choice = random.choice(responses)
        await ctx.send(choice)


# -----------------------------
# SUGGEST BUTTON COMMAND (PREFIX ADMIN)
# -----------------------------

@bot.command(name="suggestbutton")
@commands.has_permissions(administrator=True)
async def suggest_button_cmd(ctx):
    if ctx.channel.id not in ALLOWED_SUGGEST_BUTTON_CHANNELS:
        return await ctx.send("This command can only be used in approved channels.")

    embed = discord.Embed(
        title="💡 Anonymous Suggestions",
        description=(
            "Want to submit feedback privately?\n"
            "Click the button below and I'll open a DM where you can send your anonymous suggestion."
        ),
        color=discord.Color.green()
    )

    await ctx.send(embed=embed, view=MessageMeButton())


# -----------------------------
# COMMAND GUIDE (PREFIX)
# -----------------------------

def build_commands_guide_embed():
    embed = discord.Embed(
        title="HYDRABOT — FULL COMMAND GUIDE",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="GENERAL COMMANDS",
        value=(
            "`$test` — Checks if HydraBot is online.\n"
            "`$chests` — Shows Hydra Clash chest damage requirements."
        ),
        inline=False
    )

    embed.add_field(
        name="ADMIN / UTILITY COMMANDS",
        value=(
            "`$announce <message>` — Posts an announcement.\n"
            "`$purge <amount>` — Deletes messages. (Admin only)"
        ),
        inline=False
    )

    embed.add_field(
        name="ANONYMOUS SUGGESTION SYSTEM",
        value=(
            "Click **Message Me** to DM the bot.\n"
            "Type your suggestion → Confirm → Submit anonymously."
        ),
        inline=False
    )

    embed.add_field(
        name="REMINDER SYSTEM",
        value=(
            "`$remindme <time> <task>` — Sets a reminder.\n"
            "`$reminders` — Shows reminders.\n"
            "`$cancelreminder <id>` — Cancels a reminder."
        ),
        inline=False
    )

    embed.add_field(
        name="SHOULD I PULL?",
        value="`$pull <event>` — Randomised pull advice.",
        inline=False
    )

    embed.add_field(
        name="GACHA SIMULATOR",
        value="`$sim <shard>` — Simulates 10 pulls.",
        inline=False
    )

    embed.add_field(
        name="MERCY TRACKER — MAIN COMMANDS",
        value=(
            "`$mercy <shard>` — Check pity.\n"
            "`$mercyall` — Full overview.\n"
            "`$mercytable` — Colour‑coded table.\n"
            "`$mercycompare @user` — Compare mercy."
        ),
        inline=False
    )

    embed.add_field(
        name="MERCY TRACKER — MANUAL LOGGING",
        value=(
            "`$addepic <shard>` — Log Epic.\n"
            "`$addlegendary <shard>` — Log Legendary.\n"
            "`$addmythical` — Log Mythical.\n"
            "`$addpull <shard> <amount>` — Add pulls.\n"
            "`$clearmercy <shard>` — Reset pity."
        ),
        inline=False
    )

    return embed


@bot.command(name="commands")
async def commands_prefix(ctx):
    if ctx.guild:
        channels = get_guild_channels(ctx.guild.id)
        commands_channel_id = channels["commands_channel_id"]
        if commands_channel_id:
            channel = ctx.guild.get_channel(commands_channel_id)
        else:
            channel = ctx.channel
    else:
        channel = ctx.channel

    embed = build_commands_guide_embed()
    await channel.send(embed=embed)


# -----------------------------
# MERCY GUIDE (PREFIX ADMIN)
# -----------------------------

def build_mercy_guide_embed():
    embed = discord.Embed(
        title="HYDRABOT — MERCY TRACKING GUIDE",
        color=discord.Color.gold()
    )

    embed.add_field(
        name="BEFORE YOU START",
        value="Begin tracking after your last Legendary pull.",
        inline=False
    )

    embed.add_field(
        name="$addpull <shard> <amount>",
        value="Use when you open shards and want to log the number of pulls.",
        inline=False
    )

    embed.add_field(
        name="$addepic <shard>",
        value="Use when you pull an Epic.",
        inline=False
    )

    embed.add_field(
        name="$addlegendary <shard>",
        value="Use when you pull a Legendary.",
        inline=False
    )

    embed.add_field(
        name="$addmythical primal",
        value="Use when you pull a Mythical.",
        inline=False
    )

    embed.add_field(
        name="$mercy <shard>",
        value="Check your current pity and chances.",
        inline=False
    )

    embed.add_field(
        name="$mercyall",
        value="Shows all your pity values.",
        inline=False
    )

    embed.add_field(
        name="$mercytable",
        value="Colour‑coded overview of all shards.",
        inline=False
    )

    embed.add_field(
        name="$mercycompare @user",
        value="Compare your pity with another player.",
        inline=False
    )

    embed.add_field(
        name="$clearmercy <shard>",
        value="Reset pity manually.",
        inline=False
    )

    return embed


@bot.command(name="mercyguide")
@commands.has_permissions(administrator=True)
async def mercy_guide_prefix(ctx):
    embed = build_mercy_guide_embed()
    await ctx.send(embed=embed)

# ============================================================
#  SECTION 8: SLASH COMMANDS (GROUPS & STANDALONE)
# ============================================================

# (All slash commands from your original file remain unchanged — already included in Parts 2 & 3)

# ============================================================
#  SECTION 9: REGISTER GROUPS & RUN BOT
# ============================================================

tree.add_command(mercy_group)
tree.add_command(reminder_group)
tree.add_command(gacha_group)
tree.add_command(admin_group)

bot.run(TOKEN)