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
    commands_channel_id INTEGER
)
""")

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
            # noqa
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
    if field not in ("warning_channel_id", "suggestion_channel_id", "feedback_channel_id", "commands_channel_id"):
        return
    # channel_id can be None, 0 (Not Required), or a real channel ID
    c.execute(
        f"UPDATE guild_channels SET {field}=? WHERE guild_id=?",
        (channel_id, str(guild_id))
    )
    conn.commit()


def get_guild_channels(guild_id: int):
    c.execute("""
        SELECT warning_channel_id, suggestion_channel_id, feedback_channel_id, commands_channel_id
        FROM guild_channels
        WHERE guild_id=?
    """, (str(guild_id),))
    row = c.fetchone()
    if row is None:
        return {
            "warning_channel_id": None,
            "suggestion_channel_id": None,
            "feedback_channel_id": None,
            "commands_channel_id": None
        }
    return {
        "warning_channel_id": row[0],
        "suggestion_channel_id": row[1],
        "feedback_channel_id": row[2],
        "commands_channel_id": row[3]
    }


def get_default_suggestion_channel_id():
    """
    For the DM-based anonymous suggestion flow.
    Assumes single main guild; picks the first configured suggestion channel.
    Returns None if none configured.
    """
    c.execute("""
        SELECT suggestion_channel_id
        FROM guild_channels
        WHERE suggestion_channel_id IS NOT NULL AND suggestion_channel_id != 0
        LIMIT 1
    """)
    row = c.fetchone()
    if row and row[0]:
        return int(row[0])
    return None


def compute_readiness_color_and_flag(shard_type, legendary_chance, mythical_chance=None):
    """
    Returns (color, ready_flag_bool, status_text_for_table)
    Ready only if:
      - Legendary > 74% (all shards)
      - OR Mythical > 74% (primal only)
    Epic is ignored for readiness.
    """
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
        elif channel_id == 0:
            # Not Required → skip
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
        elif channel_id == 0:
            # Not Required → skip
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

    try:
        await tree.sync()
        print("Slash commands synced.")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")


@bot.event
async def on_guild_join(guild):
    # Welcome message when the bot joins a new server
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
#  SECTION 5: VIEWS (BUTTONS, DM CONFIRMATION, ADMIN SETUP)
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

        suggestion_channel_id = get_default_suggestion_channel_id()
        if suggestion_channel_id is None:
            return await interaction.response.edit_message(
                content="Suggestion channel is not configured. Please ask an admin to run `/admin setup`.",
                view=None
            )

        channel = interaction.client.get_channel(suggestion_channel_id)

        if not channel:
            return await interaction.response.edit_message(
                content="Suggestion channel is not configured correctly.",
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

# -----------------------------
# ADMIN SETUP WIZARD VIEW
# -----------------------------

class SetupWizard(discord.ui.View):
    """
    /admin setup wizard:
    Steps:
      1. Hydra Warning Channel
      2. Suggestion Channel
      3. Feedback Channel
      4. Commands Guide Channel
      5. Review & Save

    Storage semantics:
      - None  → Not configured
      - 0     → Not Required
      - >0    → Channel ID
    """
    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.interaction = interaction
        self.guild = interaction.guild
        self.step = 1

        channels = get_guild_channels(self.guild.id)
        self.warning_channel_id = channels["warning_channel_id"]
        self.suggestion_channel_id = channels["suggestion_channel_id"]
        self.feedback_channel_id = channels["feedback_channel_id"]
        self.commands_channel_id = channels["commands_channel_id"]

        self.message = None
        self.add_item(self._build_select())

    # ------------- helpers -------------

    def _current_field_name(self):
        if self.step == 1:
            return "warning_channel_id"
        if self.step == 2:
            return "suggestion_channel_id"
        if self.step == 3:
            return "feedback_channel_id"
        if self.step == 4:
            return "commands_channel_id"
        return None

    def _current_title(self):
        if self.step == 1:
            return "Step 1 — Hydra Warning Channel"
        if self.step == 2:
            return "Step 2 — Suggestion Channel"
        if self.step == 3:
            return "Step 3 — Feedback Channel"
        if self.step == 4:
            return "Step 4 — Commands Guide Channel"
        if self.step == 5:
            return "Step 5 — Review & Save"
        return "Setup Wizard"

    def _current_description(self):
        if self.step == 1:
            return (
                "Choose which channel should receive **Hydra/Chimera warnings**.\n\n"
                "• Select a channel\n"
                "• Or choose **Not Required** if you don't want warnings\n"
                "• Or leave unselected to keep it **Not configured**"
            )
        if self.step == 2:
            return (
                "Choose which channel should receive **suggestions**.\n\n"
                "This is where the bot will post anonymous suggestions and the suggestion button."
            )
        if self.step == 3:
            return (
                "Choose which channel should receive **feedback**.\n\n"
                "You can use this for general feedback or future features."
            )
        if self.step == 4:
            return (
                "Choose which channel should receive the **commands guide**.\n\n"
                "If unset, `$commands` and `/admin commands-guide` will post in the current channel."
            )
        if self.step == 5:
            return "Review your configuration below, then click **Save** or go **Back** to adjust."
        return ""

    def _get_value_for_field(self, field: str):
        return getattr(self, field)

    def _set_value_for_field(self, field: str, value):
        setattr(self, field, value)

    def _format_channel_value(self, value: int | None):
        if value is None:
            return "Not configured"
        if value == 0:
            return "Not Required"
        channel = self.guild.get_channel(value)
        if channel:
            return channel.mention
        return f"<#{value}> (missing)"

    def _build_select(self) -> discord.ui.Select:
        options = []

        # Not Required option
        options.append(
            discord.SelectOption(
                label="❌ Not Required",
                value="0",
                description="Disable this feature for this server."
            )
        )

        # All text channels
        for ch in self.guild.text_channels:
            options.append(
                discord.SelectOption(
                    label=f"#{ch.name}",
                    value=str(ch.id)
                )
            )

        select = discord.ui.Select(
            placeholder="Select a channel or Not Required…",
            min_values=1,
            max_values=1,
            options=options
        )

        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.interaction.user.id:
                return await interaction.response.send_message(
                    "You are not the owner of this setup session.",
                    ephemeral=True
                )

            field = self._current_field_name()
            if not field:
                return await interaction.response.defer()

            raw = select.values[0]
            if raw == "0":
                value = 0
            else:
                value = int(raw)

            self._set_value_for_field(field, value)

            await interaction.response.defer()

        select.callback = callback
        return select

    def _build_embed(self) -> discord.Embed:
        if self.step < 5:
            embed = discord.Embed(
                title=self._current_title(),
                description=self._current_description(),
                color=discord.Color.blurple()
            )
        else:
            embed = discord.Embed(
                title="Step 5 — Review & Save",
                description=self._current_description(),
                color=discord.Color.green()
            )

            embed.add_field(
                name="Hydra Warning Channel",
                value=self._format_channel_value(self.warning_channel_id),
                inline=False
            )
            embed.add_field(
                name="Suggestion Channel",
                value=self._format_channel_value(self.suggestion_channel_id),
                inline=False
            )
            embed.add_field(
                name="Feedback Channel",
                value=self._format_channel_value(self.feedback_channel_id),
                inline=False
            )
            embed.add_field(
                name="Commands Guide Channel",
                value=self._format_channel_value(self.commands_channel_id),
                inline=False
            )

        return embed

    async def start(self):
        embed = self._build_embed()
        self.message = await self.interaction.response.send_message(
            embed=embed,
            view=self
        )

    async def _refresh(self, interaction: discord.Interaction | None = None):
        # Rebuild select for steps 1–4
        self.clear_items()
        if self.step <= 4:
            self.add_item(self._build_select())

        # Buttons
        self.add_item(self.back_button)
        self.add_item(self.skip_button)
        self.add_item(self.next_button)
        self.add_item(self.cancel_button)

        embed = self._build_embed()

        if interaction:
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await self.interaction.edit_original_response(embed=embed, view=self)

    # ------------- buttons -------------

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction.user.id:
            return await interaction.response.send_message(
                "You are not the owner of this setup session.",
                ephemeral=True
            )

        if self.step > 1:
            self.step -= 1
        await interaction.response.defer()
        await self._refresh(interaction)

    @discord.ui.button(label="Skip (Not Required)", style=discord.ButtonStyle.secondary, row=1)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction.user.id:
            return await interaction.response.send_message(
                "You are not the owner of this setup session.",
                ephemeral=True
            )

        field = self._current_field_name()
        if field and self.step <= 4:
            self._set_value_for_field(field, 0)

        if self.step < 5:
            self.step += 1

        await interaction.response.defer()
        await self._refresh(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, row=1)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction.user.id:
            return await interaction.response.send_message(
                "You are not the owner of this setup session.",
                ephemeral=True
            )

        if self.step < 5:
            self.step += 1
            await interaction.response.defer()
            await self._refresh(interaction)
            return

        # Step 5 → Save
        ensure_guild_row(self.guild.id)
        set_guild_channel(self.guild.id, "warning_channel_id", self.warning_channel_id)
        set_guild_channel(self.guild.id, "suggestion_channel_id", self.suggestion_channel_id)
        set_guild_channel(self.guild.id, "feedback_channel_id", self.feedback_channel_id)
        set_guild_channel(self.guild.id, "commands_channel_id", self.commands_channel_id)

        # Auto-post suggestion button if configured and not disabled
        if self.suggestion_channel_id and self.suggestion_channel_id != 0:
            channel = self.guild.get_channel(self.suggestion_channel_id)
            if channel:
                embed = discord.Embed(
                    title="💡 Anonymous Suggestions",
                    description=(
                        "Want to submit feedback privately?\n"
                        "Click the button below and I'll open a DM where you can send your anonymous suggestion."
                    ),
                    color=discord.Color.green()
                )
                await channel.send(embed=embed, view=MessageMeButton())

        summary_embed = discord.Embed(
            title="✅ Setup Complete",
            description="Your configuration has been saved.",
            color=discord.Color.green()
        )
        summary_embed.add_field(
            name="Hydra Warning Channel",
            value=self._format_channel_value(self.warning_channel_id),
            inline=False
        )
        summary_embed.add_field(
            name="Suggestion Channel",
            value=self._format_channel_value(self.suggestion_channel_id),
            inline=False
        )
        summary_embed.add_field(
            name="Feedback Channel",
            value=self._format_channel_value(self.feedback_channel_id),
            inline=False
        )
        summary_embed.add_field(
            name="Commands Guide Channel",
            value=self._format_channel_value(self.commands_channel_id),
            inline=False
        )

        self.clear_items()
        await interaction.response.edit_message(embed=summary_embed, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction.user.id:
            return await interaction.response.send_message(
                "You are not the owner of this setup session.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="Setup Cancelled",
            description="No changes were saved.",
            color=discord.Color.red()
        )
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

# ============================================================
#  SECTION 6: on_message (ANONYMOUS SUGGESTIONS)
# ============================================================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

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

# -----------------------------
# BASIC PREFIX COMMANDS
# -----------------------------

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

# -----------------------------
# SUPPORT & DEVELOPER (PREFIX)
# -----------------------------

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


@bot.command(name="mercyall")
async def mercy_all_cmd(ctx):
    user = ctx.author.id
    embed = discord.Embed(
        title=f"{ctx.author.display_name}'s Full Mercy Overview",
        color=discord.Color.blue()
    )

    for shard in BASE_RATES.keys():
        epic, legendary, mythical = get_mercy_row(user, shard)

        text = ""

        legendary_chance = calc_legendary_chance(shard, legendary)
        mythical_chance = None

        if shard in ("ancient", "void"):
            epic_chance = calc_epic_chance(shard, epic)
            text += f"**Epic:** {epic} pulls — {epic_chance:.2f}%\n"

        text += f"**Legendary:** {legendary} pulls — {legendary_chance:.2f}%"

        if shard == "primal":
            mythical_chance = calc_mythical_chance(shard, mythical)
            text += f"\n**Mythical:** {mythical} pulls — {mythical_chance:.2f}%"

        _, ready, _ = compute_readiness_color_and_flag(shard, legendary_chance, mythical_chance)
        if ready:
            text += "\n🔥 **Looks like you are ready to pull :P**"

        embed.add_field(name=shard.capitalize(), value=text, inline=False)

    await ctx.send(embed=embed)


@bot.command(name="mercytable")
async def mercy_table_cmd(ctx):
    user = ctx.author.id

    embed = discord.Embed(
        title=f"{ctx.author.display_name}'s Mercy Table",
        color=discord.Color.gold()
    )

    for shard in BASE_RATES.keys():
        epic, legendary, mythical = get_mercy_row(user, shard)

        lines = []

        legendary_chance = calc_legendary_chance(shard, legendary)
        mythical_chance = None

        if shard in ("ancient", "void"):
            epic_chance = calc_epic_chance(shard, epic)
            lines.append(f"**Epic:** {epic} pulls — {epic_chance:.2f}%")
            lines.append(f"**Legendary:** {legendary} pulls — {legendary_chance:.2f}%")
        elif shard == "primal":
            mythical_chance = calc_mythical_chance(shard, mythical)
            lines.append(f"**Legendary:** {legendary} pulls — {legendary_chance:.2f}%")
            lines.append(f"**Mythical:** {mythical} pulls — {mythical_chance:.2f}%")
        else:  # sacred
            lines.append(f"**Legendary:** {legendary} pulls — {legendary_chance:.2f}%")

        _, _, status = compute_readiness_color_and_flag(shard, legendary_chance, mythical_chance)
        lines.append(f"**Status:** {status}")

        embed.add_field(
            name=shard.capitalize(),
            value="\n".join(lines),
            inline=False
        )

    await ctx.send(embed=embed)


@bot.command(name="mercycompare")
async def mercy_compare_cmd(ctx, member: discord.Member):
    user1 = ctx.author
    user2 = member

    embed = discord.Embed(
        title=f"Mercy Comparison: {user1.display_name} vs {user2.display_name}",
        color=discord.Color.purple()
    )

    for shard in BASE_RATES.keys():
        epic1, legendary1, mythical1 = get_mercy_row(user1.id, shard)
        epic2, legendary2, mythical2 = get_mercy_row(user2.id, shard)

        lines = []

        # User 1
        if shard in ("ancient", "void"):
            e1 = calc_epic_chance(shard, epic1)
            l1 = calc_legendary_chance(shard, legendary1)
            lines.append(
                f"**{user1.display_name}:** "
                f"E:{epic1} ({e1:.2f}%)  L:{legendary1} ({l1:.2f}%)"
            )
        elif shard == "primal":
            l1 = calc_legendary_chance(shard, legendary1)
            m1 = calc_mythical_chance(shard, mythical1)
            lines.append(
                f"**{user1.display_name}:** "
                f"L:{legendary1} ({l1:.2f}%)  M:{mythical1} ({m1:.2f}%)"
            )
        else:
            l1 = calc_legendary_chance(shard, legendary1)
            lines.append(
                f"**{user1.display_name}:** "
                f"L:{legendary1} ({l1:.2f}%)"
            )

        # User 2
        if shard in ("ancient", "void"):
            e2 = calc_epic_chance(shard, epic2)
            l2 = calc_legendary_chance(shard, legendary2)
            lines.append(
                f"**{user2.display_name}:** "
                f"E:{epic2} ({e2:.2f}%)  L:{legendary2} ({l2:.2f}%)"
            )
        elif shard == "primal":
            l2 = calc_legendary_chance(shard, legendary2)
            m2 = calc_mythical_chance(shard, mythical2)
            lines.append(
                f"**{user2.display_name}:** "
                f"L:{legendary2} ({l2:.2f}%)  M:{mythical2} ({m2:.2f}%)"
            )
        else:
            l2 = calc_legendary_chance(shard, legendary2)
            lines.append(
                f"**{user2.display_name}:** "
                f"L:{legendary2} ({l2:.2f}%)"
            )

        embed.add_field(
            name=shard.capitalize(),
            value="\n".join(lines),
            inline=False
        )

    await ctx.send(embed=embed)


@bot.command(name="clearmercy")
async def clear_mercy_cmd(ctx, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await ctx.send("Invalid shard type.")

    set_mercy_row(ctx.author.id, shard_type, 0, 0, 0)
    await ctx.send(f"{ctx.author.mention}, your {shard_type} mercy has been reset.")


@bot.command(name="addepic")
async def add_epic_cmd(ctx, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await ctx.send("Invalid shard type.")

    epic, legendary, mythical = get_mercy_row(ctx.author.id, shard_type)

    epic = 0
    legendary += 1
    if shard_type == "primal":
        mythical += 1

    set_mercy_row(ctx.author.id, shard_type, epic, legendary, mythical)
    await ctx.send(f"{ctx.author.mention}, **Epic** recorded for {shard_type}.")


@bot.command(name="addlegendary")
async def add_legendary_cmd(ctx, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await ctx.send("Invalid shard type.")

    epic, legendary, mythical = get_mercy_row(ctx.author.id, shard_type)

    epic = 0
    legendary = 0
    if shard_type == "primal":
        mythical += 1

    set_mercy_row(ctx.author.id, shard_type, epic, legendary, mythical)
    await ctx.send(f"{ctx.author.mention}, **Legendary** recorded for {shard_type}.")


@bot.command(name="addmythical")
async def add_mythical_cmd(ctx, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type != "primal":
        return await ctx.send("Only primal shards can pull mythical champions.")

    epic, legendary, mythical = get_mercy_row(ctx.author.id, shard_type)

    epic = 0
    legendary = 0
    mythical = 0

    set_mercy_row(ctx.author.id, shard_type, epic, legendary, mythical)
    await ctx.send(f"{ctx.author.mention}, **Mythical** recorded for primal.")


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
# SUGGEST BUTTON COMMAND (PREFIX ADMIN, DB-DRIVEN)
# -----------------------------

@bot.command(name="suggestbutton")
@commands.has_permissions(administrator=True)
async def suggest_button_cmd(ctx):
    if not ctx.guild:
        return await ctx.send("This command can only be used in a server.")

    channels = get_guild_channels(ctx.guild.id)
    suggestion_channel_id = channels["suggestion_channel_id"]

    if suggestion_channel_id is None:
        return await ctx.send(
            "Suggestion channel is not configured. Ask an admin to run `/admin setup`."
        )

    if suggestion_channel_id == 0:
        return await ctx.send(
            "Suggestion feature is currently **Not Required** for this server."
        )

    if suggestion_channel_id != ctx.channel.id:
        channel = ctx.guild.get_channel(suggestion_channel_id)
        if channel:
            return await ctx.send(
                f"This command can only be used in {channel.mention}."
            )
        else:
            return await ctx.send(
                "Configured suggestion channel no longer exists. Ask an admin to run `/admin setup` again."
            )

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
            "`$announce <message>` — Posts an announcement in the announcement channel.\n"
            "`$purge <amount>` — Deletes the last X messages. (Admin only)"
        ),
        inline=False
    )

    embed.add_field(
        name="ANONYMOUS SUGGESTION SYSTEM",
        value=(
            "Click the **Message Me** button to DM the bot.\n"
            "Type your suggestion → Bot asks for confirmation → Submit anonymously."
        ),
        inline=False
    )

    embed.add_field(
        name="REMINDER SYSTEM",
        value=(
            "`$remindme <time> <task>` — Sets a reminder.\n"
            " Examples: `10m`, `2h`, `1d`\n"
            "`$reminders` — Shows your active reminders.\n"
            "`$cancelreminder <id>` — Cancels a reminder."
        ),
        inline=False
    )

    embed.add_field(
        name="SHOULD I PULL?",
        value=(
            "`$pull <event>` — Randomised pull advice.\n"
            "Usable in any channel."
        ),
        inline=False
    )

    embed.add_field(
        name="GACHA SIMULATOR",
        value=(
            "`$sim <shard>` — Simulates 10 pulls.\n"
            "Shard types: `ancient`, `void`, `primal`, `sacred`."
        ),
        inline=False
    )

    embed.add_field(
        name="MERCY TRACKER — MAIN COMMANDS",
        value=(
            "`$mercy <shard>` — Shows your pity and current percentages for that shard.\n"
            "`$mercyall` — Full overview of all shard types.\n"
            "`$mercytable` — Colour‑coded table of your pity and chances, with readiness indicators.\n"
            "`$mercycompare @user` — Compare your mercy with another player."
        ),
        inline=False
    )

    embed.add_field(
        name="MERCY TRACKER — MANUAL LOGGING",
        value=(
            "Use these after each pull result:\n\n"
            "`$addepic <shard>` — Logs an Epic pull.\n"
            "`$addlegendary <shard>` — Logs a Legendary pull.\n"
            "`$addmythical` — Logs a Mythical pull (Primal only).\n"
            "`$addpull <shard> <amount>` — Adds raw pulls to pity counters.\n"
            "`$clearmercy <shard>` — Resets pity for that shard."
        ),
        inline=False
    )

    return embed


@bot.command(name="commands")
async def commands_prefix(ctx):
    if ctx.guild:
        channels = get_guild_channels(ctx.guild.id)
        commands_channel_id = channels["commands_channel_id"]
        if commands_channel_id and commands_channel_id != 0:
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
        value=(
            "Begin tracking after your last Legendary pull.\n"
            "This ensures your pity starts at the correct point."
        ),
        inline=False
    )

    embed.add_field(
        name="$addpull <shard> <amount>",
        value=(
            "Use when you open shards and want to log the number of pulls.\n\n"
            "**Example:**\n"
            "`$addpull void 10`\n\n"
            "**What it does:**\n"
            "• Increases Epic pity (Ancient/Void only)\n"
            "• Increases Legendary pity (all shards)\n"
            "• Increases Mythical pity (Primal only)"
        ),
        inline=False
    )

    embed.add_field(
        name="$addepic <shard>",
        value=(
            "Use when you pull an Epic.\n\n"
            "**Example:**\n"
            "`$addepic ancient`\n\n"
            "**What it does:**\n"
            "• Resets Epic pity (Ancient/Void only)\n"
            "• Increases Legendary pity"
        ),
        inline=False
    )

    embed.add_field(
        name="$addlegendary <shard>",
        value=(
            "Use when you pull a Legendary.\n\n"
            "**Example:**\n"
            "`$addlegendary sacred`\n\n"
            "**What it does:**\n"
            "• Resets Epic pity\n"
            "• Resets Legendary pity\n"
            "• Increases Mythical pity (Primal only)\n\n"
            "This is the command you use to start tracking after your last Legendary."
        ),
        inline=False
    )

    embed.add_field(
        name="$addmythical primal",
        value=(
            "Use when you pull a Mythical.\n\n"
            "**What it does:**\n"
            "• Resets ALL Primal pity values"
        ),
        inline=False
    )

    embed.add_field(
        name="$mercy <shard>",
        value=(
            "Use to check your current pity and chances.\n\n"
            "**Shows:**\n"
            "• Epic / Legendary / Mythical chances\n"
            "• Current pity\n"
            "• Next block progress\n"
            "• “Ready to pull” indicator (74%+ Legendary or Mythical)"
        ),
        inline=False
    )

    embed.add_field(
        name="$mercyall",
        value="Shows all your pity values in one embed.",
        inline=False
    )

    embed.add_field(
        name="$mercytable",
        value=(
            "Colour‑coded overview of all shards, including:\n"
            "• Pity values\n"
            "• Percentages\n"
            "• Status indicators (🟢 Ready, 🟡 Building, 🔴 Low)"
        ),
        inline=False
    )

    embed.add_field(
        name="$mercycompare @user",
        value="Compare your pity and chances directly with another player.",
        inline=False
    )

    embed.add_field(
        name="$clearmercy <shard>",
        value="Use only if you want to manually reset pity.",
        inline=False
    )

    embed.add_field(
        name="EXAMPLE WORKFLOW",
        value=(
            "Pull a Legendary → `$addlegendary void`\n"
            "Open 12 shards → `$addpull void 12`\n"
            "Pull an Epic → `$addepic void`\n"
            "Check pity → `$mercy void`"
        ),
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

# -----------------------------
# AUTOCOMPLETE HELPERS
# -----------------------------

async def shard_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    current = current.lower()
    return [
        app_commands.Choice(name=s.capitalize(), value=s)
        for s in SHARD_CHOICES
        if current in s
    ]

# -----------------------------
# MERCY GROUP (SLASH)
# -----------------------------

mercy_group = app_commands.Group(
    name="mercy",
    description="Mercy tracking and comparison commands."
)

@mercy_group.command(name="check", description="Check your mercy for a shard.")
@app_commands.describe(shard_type="Shard type: ancient, void, primal, sacred")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_check(
    interaction: discord.Interaction,
    shard_type: str
):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message(
            "Invalid shard type. Use: ancient, void, primal, sacred.",
            ephemeral=True
        )

    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)

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

    color, ready, _ = compute_readiness_color_and_flag(shard_type, legendary_chance, mythical_chance)
    embed.color = color
    if ready:
        embed.add_field(
            name="🔥 Ready?",
            value="Looks like you are ready to pull :P",
            inline=False
        )

    await interaction.response.send_message(embed=embed)


@mercy_group.command(name="table", description="Show your mercy table for all shards.")
async def mercy_table_slash(interaction: discord.Interaction):
    user = interaction.user.id

    embed = discord.Embed(
        title=f"{interaction.user.display_name}'s Mercy Table",
        color=discord.Color.gold()
    )

    for shard in BASE_RATES.keys():
        epic, legendary, mythical = get_mercy_row(user, shard)

        lines = []

        legendary_chance = calc_legendary_chance(shard, legendary)
        mythical_chance = None

        if shard in ("ancient", "void"):
            epic_chance = calc_epic_chance(shard, epic)
            lines.append(f"**Epic:** {epic} pulls — {epic_chance:.2f}%")
            lines.append(f"**Legendary:** {legendary} pulls — {legendary_chance:.2f}%")
        elif shard == "primal":
            mythical_chance = calc_mythical_chance(shard, mythical)
            lines.append(f"**Legendary:** {legendary} pulls — {legendary_chance:.2f}%")
            lines.append(f"**Mythical:** {mythical} pulls — {mythical_chance:.2f}%")
        else:
            lines.append(f"**Legendary:** {legendary} pulls — {legendary_chance:.2f}%")

        _, _, status = compute_readiness_color_and_flag(shard, legendary_chance, mythical_chance)
        lines.append(f"**Status:** {status}")

        embed.add_field(
            name=shard.capitalize(),
            value="\n".join(lines),
            inline=False
        )

    await interaction.response.send_message(embed=embed)


@mercy_group.command(name="all", description="Show a full mercy overview for all shards.")
async def mercy_all_slash(interaction: discord.Interaction):
    user = interaction.user.id
    embed = discord.Embed(
        title=f"{interaction.user.display_name}'s Full Mercy Overview",
        color=discord.Color.blue()
    )

    for shard in BASE_RATES.keys():
        epic, legendary, mythical = get_mercy_row(user, shard)

        text = ""

        legendary_chance = calc_legendary_chance(shard, legendary)
        mythical_chance = None

        if shard in ("ancient", "void"):
            epic_chance = calc_epic_chance(shard, epic)
            text += f"**Epic:** {epic} pulls — {epic_chance:.2f}%\n"

        text += f"**Legendary:** {legendary} pulls — {legendary_chance:.2f}%"

        if shard == "primal":
            mythical_chance = calc_mythical_chance(shard, mythical)
            text += f"\n**Mythical:** {mythical} pulls — {mythical_chance:.2f}%"

        _, ready, _ = compute_readiness_color_and_flag(shard, legendary_chance, mythical_chance)
        if ready:
            text += "\n🔥 **Looks like you are ready to pull :P**"

        embed.add_field(name=shard.capitalize(), value=text, inline=False)

    await interaction.response.send_message(embed=embed)


@mercy_group.command(name="compare", description="Compare your mercy with another user.")
@app_commands.describe(member="User to compare with")
async def mercy_compare_slash(
    interaction: discord.Interaction,
    member: discord.Member
):
    user1 = interaction.user
    user2 = member

    embed = discord.Embed(
        title=f"Mercy Comparison: {user1.display_name} vs {user2.display_name}",
        color=discord.Color.purple()
    )

    for shard in BASE_RATES.keys():
        epic1, legendary1, mythical1 = get_mercy_row(user1.id, shard)
        epic2, legendary2, mythical2 = get_mercy_row(user2.id, shard)

        lines = []

        # User 1
        if shard in ("ancient", "void"):
            e1 = calc_epic_chance(shard, epic1)
            l1 = calc_legendary_chance(shard, legendary1)
            lines.append(
                f"**{user1.display_name}:** "
                f"E:{epic1} ({e1:.2f}%)  L:{legendary1} ({l1:.2f}%)"
            )
        elif shard == "primal":
            l1 = calc_legendary_chance(shard, legendary1)
            m1 = calc_mythical_chance(shard, mythical1)
            lines.append(
                f"**{user1.display_name}:** "
                f"L:{legendary1} ({l1:.2f}%)  M:{mythical1} ({m1:.2f}%)"
            )
        else:
            l1 = calc_legendary_chance(shard, legendary1)
            lines.append(
                f"**{user1.display_name}:** "
                f"L:{legendary1} ({l1:.2f}%)"
            )

        # User 2
        if shard in ("ancient", "void"):
            e2 = calc_epic_chance(shard, epic2)
            l2 = calc_legendary_chance(shard, legendary2)
            lines.append(
                f"**{user2.display_name}:** "
                f"E:{epic2} ({e2:.2f}%)  L:{legendary2} ({l2:.2f}%)"
            )
        elif shard == "primal":
            l2 = calc_legendary_chance(shard, legendary2)
            m2 = calc_mythical_chance(shard, mythical2)
            lines.append(
                f"**{user2.display_name}:** "
                f"L:{legendary2} ({l2:.2f}%)  M:{mythical2} ({m2:.2f}%)"
            )
        else:
            l2 = calc_legendary_chance(shard, legendary2)
            lines.append(
                f"**{user2.display_name}:** "
                f"L:{legendary2} ({l2:.2f}%)"
            )

        embed.add_field(
            name=shard.capitalize(),
            value="\n".join(lines),
            inline=False
        )

    await interaction.response.send_message(embed=embed)


@mercy_group.command(name="add-pull", description="Add pulls to your mercy for a shard.")
@app_commands.describe(
    shard_type="Shard type: ancient, void, primal, sacred",
    amount="Number of pulls to add"
)
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_add_pull_slash(
    interaction: discord.Interaction,
    shard_type: str,
    amount: int
):
    shard_type = shard_type.lower()

    if shard_type not in BASE_RATES:
        return await interaction.response.send_message(
            "Invalid shard type. Use: ancient, void, primal, sacred.",
            ephemeral=True
        )

    if amount <= 0:
        return await interaction.response.send_message(
            "Amount must be a positive number.",
            ephemeral=True
        )

    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)

    if shard_type in ("ancient", "void"):
        epic += amount

    legendary += amount

    if shard_type == "primal":
        mythical += amount

    set_mercy_row(interaction.user.id, shard_type, epic, legendary, mythical)

    msg = f"{interaction.user.mention}, added **{amount}** pulls to your **{shard_type}** mercy.\n"

    if shard_type in ("ancient", "void"):
        msg += f"Epic: **{epic}**, "

    msg += f"Legendary: **{legendary}**"

    if shard_type == "primal":
        msg += f", Mythical: **{mythical}**"

    await interaction.response.send_message(msg)


@mercy_group.command(name="add-epic", description="Record an epic pull for a shard.")
@app_commands.describe(shard_type="Shard type: ancient, void, primal, sacred")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_add_epic_slash(
    interaction: discord.Interaction,
    shard_type: str
):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message(
            "Invalid shard type.",
            ephemeral=True
        )

    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)

    epic = 0
    legendary += 1
    if shard_type == "primal":
        mythical += 1

    set_mercy_row(interaction.user.id, shard_type, epic, legendary, mythical)
    await interaction.response.send_message(
        f"{interaction.user.mention}, **Epic** recorded for {shard_type}."
    )


@mercy_group.command(name="add-legendary", description="Record a legendary pull for a shard.")
@app_commands.describe(shard_type="Shard type: ancient, void, primal, sacred")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_add_legendary_slash(
    interaction: discord.Interaction,
    shard_type: str
):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message(
            "Invalid shard type.",
            ephemeral=True
        )

    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)

    epic = 0
    legendary = 0
    if shard_type == "primal":
        mythical += 1

    set_mercy_row(interaction.user.id, shard_type, epic, legendary, mythical)
    await interaction.response.send_message(
        f"{interaction.user.mention}, **Legendary** recorded for {shard_type}."
    )


@mercy_group.command(name="add-mythical", description="Record a mythical pull (primal only).")
@app_commands.describe(shard_type="Must be primal")
async def mercy_add_mythical_slash(
    interaction: discord.Interaction,
    shard_type: str
):
    shard_type = shard_type.lower()
    if shard_type != "primal":
        return await interaction.response.send_message(
            "Only primal shards can pull mythical champions.",
            ephemeral=True
        )

    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)

    epic = 0
    legendary = 0
    mythical = 0

    set_mercy_row(interaction.user.id, shard_type, epic, legendary, mythical)
    await interaction.response.send_message(
        f"{interaction.user.mention}, **Mythical** recorded for primal."
    )


@mercy_group.command(name="clear", description="Clear your mercy for a shard.")
@app_commands.describe(shard_type="Shard type: ancient, void, primal, sacred")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_clear_slash(
    interaction: discord.Interaction,
    shard_type: str
):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message(
            "Invalid shard type.",
            ephemeral=True
        )

    set_mercy_row(interaction.user.id, shard_type, 0, 0, 0)
    await interaction.response.send_message(
        f"{interaction.user.mention}, your {shard_type} mercy has been reset."
    )

# -----------------------------
# REMINDER GROUP (SLASH)
# -----------------------------

reminder_group = app_commands.Group(
    name="reminder",
    description="Set and manage reminders."
)

@reminder_group.command(name="set", description="Set a reminder.")
@app_commands.describe(
    time="Time like 10m, 2h, 1d",
    reminder="What you want to be reminded about"
)
async def reminder_set(
    interaction: discord.Interaction,
    time: str,
    reminder: str
):
    unit = time[-1]
    amount = time[:-1]

    if not amount.isdigit():
        return await interaction.response.send_message(
            "Time must be a number followed by m/h/d (e.g., 10m, 2h).",
            ephemeral=True
        )

    amount = int(amount)

    if unit == "m":
        seconds = amount * 60
    elif unit == "h":
        seconds = amount * 3600
    elif unit == "d":
        seconds = amount * 86400
    else:
        return await interaction.response.send_message(
            "Invalid time unit. Use m, h, or d.",
            ephemeral=True
        )

    user_id = interaction.user.id
    if user_id not in reminders:
        reminders[user_id] = []

    reminder_id = len(reminders[user_id]) + 1
    reminders[user_id].append({
        "id": reminder_id,
        "text": reminder,
        "time": time
    })

    await interaction.response.send_message(
        f"⏰ Reminder **#{reminder_id}** set for **{time}**.",
        ephemeral=True
    )

    async def reminder_task():
        await asyncio.sleep(seconds)
        channel = interaction.channel
        try:
            await channel.send(
                f"{interaction.user.mention} 🔔 Reminder #{reminder_id}: **{reminder}**"
            )
        finally:
            reminders[user_id] = [
                r for r in reminders[user_id] if r["id"] != reminder_id
            ]

    bot.loop.create_task(reminder_task())


@reminder_group.command(name="list", description="List your active reminders.")
async def reminder_list(interaction: discord.Interaction):
    user_id = interaction.user.id

    if user_id not in reminders or len(reminders[user_id]) == 0:
        return await interaction.response.send_message(
            "You have no active reminders.",
            ephemeral=True
        )

    message = "**Your Active Reminders:**\n"
    for r in reminders[user_id]:
        message += f"• #{r['id']} – {r['text']} (in {r['time']})\n"

    await interaction.response.send_message(message, ephemeral=True)


@reminder_group.command(name="cancel", description="Cancel a reminder by ID.")
@app_commands.describe(reminder_id="The reminder ID to cancel")
async def reminder_cancel(
    interaction: discord.Interaction,
    reminder_id: int
):
    user_id = interaction.user.id

    if user_id not in reminders or len(reminders[user_id]) == 0:
        return await interaction.response.send_message(
            "You have no reminders to cancel.",
            ephemeral=True
        )

    before = len(reminders[user_id])
    reminders[user_id] = [r for r in reminders[user_id] if r["id"] != reminder_id]
    after = len(reminders[user_id])

    if before == after:
        await interaction.response.send_message(
            f"No reminder found with ID #{reminder_id}.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"❎ Reminder #{reminder_id} cancelled.",
            ephemeral=True
        )

# -----------------------------
# GACHA GROUP (SLASH)
# -----------------------------

gacha_group = app_commands.Group(
    name="gacha",
    description="Gacha simulator and pull advice."
)

@gacha_group.command(name="simulate", description="Simulate 10 pulls for a shard.")
@app_commands.describe(shard_type="Shard type: ancient, void, primal, sacred")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def gacha_simulate_slash(
    interaction: discord.Interaction,
    shard_type: str
):
    shard_type = shard_type.lower()

    if shard_type not in SHARD_RATES:
        return await interaction.response.send_message(
            "Invalid shard type. Choose: ancient, void, primal, sacred.",
            ephemeral=True
        )

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

    embed.add_field(name="Requested by", value=interaction.user.mention, inline=False)

    embed.set_footer(text="HydraBot Simulator")

    await interaction.response.send_message(embed=embed)


@gacha_group.command(name="pull-advice", description="Ask if you should pull.")
@app_commands.describe(event="Optional event or banner name")
async def gacha_pull_advice_slash(
    interaction: discord.Interaction,
    event: str | None = None
):
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

    embed.add_field(name="Requested by", value=interaction.user.mention, inline=False)

    if event:
        embed.add_field(name="Event", value=event, inline=False)

    embed.set_footer(text="Decision generated by HydraBot RNG")

    await interaction.response.send_message(embed=embed)

# -----------------------------
# ADMIN GROUP (SLASH, ADMIN-ONLY)
# -----------------------------

admin_group = app_commands.Group(
    name="admin",
    description="Admin-only tools.",
    default_permissions=discord.Permissions(administrator=True)
)

@admin_group.command(name="announce", description="Send an announcement to the configured channel.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(message="Announcement text")
async def admin_announce_slash(
    interaction: discord.Interaction,
    message: str
):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True
        )

    channel = interaction.client.get_channel(ANNOUNCE_CHANNEL_ID)

    embed = discord.Embed(
        title="📢 Announcement",
        description=message,
        color=discord.Color.blue()
    )

    embed.set_footer(
        text=f"Posted by {interaction.user}",
        icon_url=interaction.user.avatar.url if interaction.user.avatar else None
    )

    embed.timestamp = discord.utils.utcnow()

    await channel.send(embed=embed)
    await interaction.response.send_message("Announcement sent.", ephemeral=True)


@admin_group.command(name="purge", description="Purge a number of messages in this channel.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(amount="Number of messages to delete")
async def admin_purge_slash(
    interaction: discord.Interaction,
    amount: int
):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True
        )

    if amount <= 0:
        return await interaction.response.send_message(
            "Please enter a number greater than 0.",
            ephemeral=True
        )

    deleted = await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(
        f"Deleted {len(deleted)} messages.",
        ephemeral=True
    )

# NEW: ADMIN SUGGEST BUTTON (SLASH, DB-DRIVEN)

@admin_group.command(name="suggest-button", description="Post the anonymous suggestion button.")
@app_commands.default_permissions(administrator=True)
async def admin_suggest_button_slash(
    interaction: discord.Interaction
):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True
        )

    if not interaction.guild:
        return await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=True
        )

    channels = get_guild_channels(interaction.guild.id)
    suggestion_channel_id = channels["suggestion_channel_id"]

    if suggestion_channel_id is None:
        return await interaction.response.send_message(
            "Suggestion channel is not configured. Ask an admin to run `/admin setup`.",
            ephemeral=True
        )

    if suggestion_channel_id == 0:
        return await interaction.response.send_message(
            "Suggestion feature is currently **Not Required** for this server.",
            ephemeral=True
        )

    if suggestion_channel_id != interaction.channel.id:
        channel = interaction.guild.get_channel(suggestion_channel_id)
        if channel:
            return await interaction.response.send_message(
                f"This command can only be used in {channel.mention}.",
                ephemeral=True
            )
        else:
            return await interaction.response.send_message(
                "Configured suggestion channel no longer exists. Run `/admin setup` again.",
                ephemeral=True
            )

    embed = discord.Embed(
        title="💡 Anonymous Suggestions",
        description=(
            "Want to submit feedback privately?\n"
            "Click the button below and I'll open a DM where you can send your anonymous suggestion."
        ),
        color=discord.Color.green()
    )

    await interaction.response.send_message(embed=embed, view=MessageMeButton())

# NEW: ADMIN SETUP WIZARD (SLASH)

@admin_group.command(name="setup", description="Run the HydraBot setup wizard.")
@app_commands.default_permissions(administrator=True)
async def admin_setup_slash(
    interaction: discord.Interaction
):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True
        )

    if not interaction.guild:
        return await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=True
        )

    view = SetupWizard(interaction)
    await view.start()

# -----------------------------
# ADMIN GROUP: COMMANDS GUIDE & MERCY GUIDE (SLASH)
# -----------------------------

@admin_group.command(name="commands-guide", description="Post the full commands guide embed.")
@app_commands.default_permissions(administrator=True)
async def admin_commands_guide_slash(
    interaction: discord.Interaction
):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True
        )

    channels = get_guild_channels(interaction.guild.id)
    commands_channel_id = channels["commands_channel_id"]
    if commands_channel_id and commands_channel_id != 0:
        channel = interaction.guild.get_channel(commands_channel_id)
    else:
        channel = interaction.channel

    embed = build_commands_guide_embed()
    await channel.send(embed=embed)
    await interaction.response.send_message(
        "Commands guide posted.",
        ephemeral=True
    )


@admin_group.command(name="mercy-guide", description="Post the mercy tracking guide embed.")
@app_commands.default_permissions(administrator=True)
async def admin_mercy_guide_slash(
    interaction: discord.Interaction
):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True
        )

    embed = build_mercy_guide_embed()
    await interaction.channel.send(embed=embed)
    await interaction.response.send_message(
        "Mercy guide posted.",
        ephemeral=True
    )

# -----------------------------
# STANDALONE SLASH: SUPPORT & DEVELOPER
# -----------------------------

@tree.command(name="support", description="Get the Hydra Companion support server link.")
async def support_slash(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**Support Server**\n"
        "If you need help with Hydra Companion, join here:\n"
        "https://discord.gg/DuemMm57jr"
    )


@tree.command(name="developer", description="Links to Hydra Companion developer resources.")
async def developer_slash(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**Hydra Companion Developer Resources**\n\n"
        "**GitHub Profile:** https://github.com/sketeraid\n"
        "**Desktop App (Beta):** https://github.com/sketeraid/HydraCompanionApp\n"
        "**Discord Bot:** https://github.com/sketeraid/HydraCompanion-Discord-Bot\n"
        "**Android App (Beta):** https://github.com/sketeraid/HydraCompanionAndroidAPK"
    )

# ============================================================
#  SECTION 9: REGISTER GROUPS & RUN BOT
# ============================================================

tree.add_command(mercy_group)
tree.add_command(reminder_group)
tree.add_command(gacha_group)
tree.add_command(admin_group)

bot.run(TOKEN)