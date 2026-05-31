# ============================================================
#  SECTION 1: IMPORTS, GLOBALS, CONSTANTS, DB, HELPERS
# ============================================================

import os
import sys
import time
import random
import asyncio
import sqlite3
import json
import discord
from discord.ext import commands
from discord import app_commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="$", intents=intents)
tree = bot.tree
scheduler = AsyncIOScheduler(timezone="Europe/London")

HYDRA_WARNING_CHANNEL_ID = 1461342242470887546
ANNOUNCE_CHANNEL_ID = 1461342242470887546
SUGGESTION_CHANNEL_ID = 1464216800651640893
KEY_REPORT_CHANNEL_ID = 1483798122931949598

HYDRA_MAX_KEYS = 3
CHIMERA_MAX_KEYS = 2

ALLOWED_SUGGEST_BUTTON_CHANNELS = {
    1463963533640335423,
    1463963575780507669
}

SHARD_CHOICES = ["ancient", "void", "primal", "sacred"]

BASE_RATES = {
    "ancient": {"epic": 8.0, "legendary": 0.5, "mythical": 0.0},
    "void": {"epic": 8.0, "legendary": 0.5, "mythical": 0.0},
    "primal": {"epic": 16.0, "legendary": 1.0, "mythical": 0.5},
    "sacred": {"epic": 94.0, "legendary": 6.0, "mythical": 0.0}
}

# ============================================================
#  LOAD CHAMPION STRATEGY DATA
# ============================================================

CHAMPIONS_DATA_FILE = "champions_data.json"
champions_data = {}

if os.path.exists(CHAMPIONS_DATA_FILE):
    with open(CHAMPIONS_DATA_FILE, 'r', encoding='utf-8') as f:
        champions_data = json.load(f)
    print(f"✅ Loaded {len(champions_data)} champions from database.")
else:
    print(f"⚠️ Warning: {CHAMPIONS_DATA_FILE} not found. /champion command will be empty.")

# ============================================================
#  SECTION 2: DATABASE SETUP
# ============================================================

# Check if Railway gave us a permanent hard drive path, otherwise use local
DB_PATH = os.getenv("DB_PATH", "mercy.db")

# Thread safety applied to prevent simultaneous command crashes
conn = sqlite3.connect(DB_PATH, check_same_thread=False)

with conn:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS mercy (
        user_id TEXT,
        shard_type TEXT,
        epic_pity INTEGER DEFAULT 0,
        legendary_pity INTEGER DEFAULT 0,
        mythical_pity INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, shard_type)
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS guild_channels (
        guild_id TEXT PRIMARY KEY,
        warning_channel_id INTEGER,
        suggestion_channel_id INTEGER,
        feedback_channel_id INTEGER,
        commands_channel_id INTEGER,
        mercy_channel_id INTEGER,
        warning_report_channel_id INTEGER
    )
    """)

    # Apply schema updates gracefully if the DB already exists
    columns_to_add = [
        ("mercy_channel_id", "INTEGER"),
        ("warning_report_channel_id", "INTEGER")
    ]
    for col_name, col_type in columns_to_add:
        try:
            conn.execute(f"ALTER TABLE guild_channels ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass

    conn.execute("""
    CREATE TABLE IF NOT EXISTS keys (
        user_id TEXT PRIMARY KEY,
        username TEXT,
        hydra_used INTEGER DEFAULT 0,
        chimera_used INTEGER DEFAULT 0
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS hidden_warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT,
        user_id TEXT,
        mod_id TEXT,
        reason TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        channel_id TEXT,
        reminder_text TEXT,
        due_time INTEGER
    )
    """)

# ============================================================
#  SECTION 3: MERCY & DB HELPERS
# ============================================================

def calc_epic_chance(shard_type, pity):
    if shard_type in ("ancient", "void"):
        base = BASE_RATES[shard_type]["epic"]
        if pity <= 20:
            return base
        return min(100.0, base + (pity - 20) * 2.0)
    return BASE_RATES[shard_type]["epic"]

def calc_legendary_chance(shard_type, pity):
    if shard_type in ("ancient", "void"):
        base = BASE_RATES[shard_type]["legendary"]
        if pity <= 200:
            return base
        return min(100.0, base + (pity - 200) * 5.0)
    if shard_type == "primal":
        base = BASE_RATES["primal"]["legendary"]
        if pity <= 75:
            return base
        return min(100.0, base + (pity - 75) * 1.0)
    if shard_type == "sacred":
        base = BASE_RATES["sacred"]["legendary"]
        if pity <= 12:
            return base
        return min(100.0, base + (pity - 12) * 2.0)
    return BASE_RATES[shard_type]["legendary"]

def calc_mythical_chance(shard_type, pity):
    if shard_type == "primal":
        base = BASE_RATES["primal"]["mythical"]
        if pity <= 200:
            return base
        return min(100.0, base + (pity - 200) * 10.0)
    return BASE_RATES[shard_type]["mythical"]

def get_mercy_row(user_id, shard_type):
    shard_type = shard_type.lower()
    cursor = conn.execute(
        "SELECT epic_pity, legendary_pity, mythical_pity FROM mercy WHERE user_id=? AND shard_type=?",
        (str(user_id), shard_type)
    )
    row = cursor.fetchone()
    if row is None:
        with conn:
            conn.execute("INSERT INTO mercy (user_id, shard_type) VALUES (?, ?)", (str(user_id), shard_type))
        return 0, 0, 0
    return row

def set_mercy_row(user_id, shard_type, epic, legendary, mythical):
    shard_type = shard_type.lower()
    with conn:
        conn.execute("""
            INSERT INTO mercy (user_id, shard_type, epic_pity, legendary_pity, mythical_pity)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, shard_type) DO UPDATE SET
                epic_pity=excluded.epic_pity,
                legendary_pity=excluded.legendary_pity,
                mythical_pity=excluded.mythical_pity
        """, (str(user_id), shard_type, epic, legendary, mythical))

def process_mercy_pulls(user_id, shard_type, amount, epic_on=0, legendary_on=0, mythical_on=0):
    epic_pity, leg_pity, myth_pity = get_mercy_row(user_id, shard_type)

    epic_on = min(epic_on, amount)
    legendary_on = min(legendary_on, amount)
    mythical_on = min(mythical_on, amount)

    if shard_type in ("ancient", "void"):
        if epic_on > 0:
            epic_pity = amount - epic_on
        else:
            epic_pity += amount

    if legendary_on > 0:
        leg_pity = amount - legendary_on
    else:
        leg_pity += amount

    if shard_type == "primal":
        if mythical_on > 0:
            myth_pity = amount - mythical_on
        else:
            myth_pity += amount

    set_mercy_row(user_id, shard_type, epic_pity, leg_pity, myth_pity)
    return epic_pity, leg_pity, myth_pity

def get_guild_channels(guild_id):
    cursor = conn.execute("""
        SELECT warning_channel_id, suggestion_channel_id, feedback_channel_id,
               commands_channel_id, mercy_channel_id, warning_report_channel_id
        FROM guild_channels WHERE guild_id=?
    """, (str(guild_id),))
    row = cursor.fetchone()
    if row is None:
        return {
            "warning_channel_id": None, "suggestion_channel_id": None,
            "feedback_channel_id": None, "commands_channel_id": None,
            "mercy_channel_id": None, "warning_report_channel_id": None
        }
    return {
        "warning_channel_id": row[0], "suggestion_channel_id": row[1],
        "feedback_channel_id": row[2], "commands_channel_id": row[3],
        "mercy_channel_id": row[4], "warning_report_channel_id": row[5]
    }

def ensure_guild_row(guild_id):
    cursor = conn.execute("SELECT guild_id FROM guild_channels WHERE guild_id=?", (str(guild_id),))
    if cursor.fetchone() is None:
        with conn:
            conn.execute("INSERT INTO guild_channels (guild_id) VALUES (?)", (str(guild_id),))

def set_guild_channel(guild_id, field, channel_id):
    ensure_guild_row(guild_id)
    with conn:
        conn.execute(f"UPDATE guild_channels SET {field}=? WHERE guild_id=?", (channel_id, str(guild_id)))

def get_default_feedback_channel_id():
    cursor = conn.execute("SELECT feedback_channel_id FROM guild_channels WHERE feedback_channel_id IS NOT NULL LIMIT 1")
    row = cursor.fetchone()
    if row and row[0]:
        return int(row[0])
    return SUGGESTION_CHANNEL_ID

def compute_readiness_color_and_flag(shard_type, legendary_chance, mythical_chance=None):
    relevant = mythical_chance if shard_type == "primal" else legendary_chance
    ready = relevant > 74.0

    if ready:
        return discord.Color.green(), True, "🟢 **Ready to pull**"
    if relevant > 20.0:
        return discord.Color.orange(), False, "🟡 Building up"
    return discord.Color.red(), False, "🔴 Low mercy"

def get_shard_emoji(shard_type):
    return {"ancient": "🔵", "void": "🟣", "primal": "🔴", "sacred": "🟡"}.get(shard_type, "🔮")

# ============================================================
#  KEY TRACKING HELPERS
# ============================================================

def get_key_row(user_id, username):
    cursor = conn.execute("SELECT hydra_used, chimera_used FROM keys WHERE user_id=?", (str(user_id),))
    row = cursor.fetchone()
    if row is None:
        with conn:
            conn.execute("INSERT INTO keys (user_id, username, hydra_used, chimera_used) VALUES (?, ?, 0, 0)", (str(user_id), username))
        return 0, 0
    return row

def set_key_row(user_id, username, hydra_used, chimera_used):
    with conn:
        conn.execute("""
            INSERT INTO keys (user_id, username, hydra_used, chimera_used)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                hydra_used=excluded.hydra_used,
                chimera_used=excluded.chimera_used
        """, (str(user_id), username, hydra_used, chimera_used))

# ============================================================
#  SECTION 3.5: SCHEDULER TASKS
# ============================================================

async def send_weekly_warning():
    for guild in bot.guilds:
        channel_id = get_guild_channels(guild.id).get("warning_channel_id")
        if not channel_id: continue
        target = guild.get_channel(channel_id)
        if target: await target.send("@everyone 24 HOUR WARNING FOR HYDRA CLASH, Don't forget or you'll miss out on rewards!")

async def send_chimera_warning():
    for guild in bot.guilds:
        channel_id = get_guild_channels(guild.id).get("warning_channel_id")
        if not channel_id: continue
        target = guild.get_channel(channel_id)
        if target: await target.send("@everyone 24 HOUR WARNING FOR CHIMERA CLASH, Don't forget or you'll miss out on rewards!")

async def send_monthly_warning_report():
    for guild in bot.guilds:
        report_ch_id = get_guild_channels(guild.id).get("warning_report_channel_id")
        if not report_ch_id: continue
        target = guild.get_channel(report_ch_id)
        if not target: continue

        cursor = conn.execute("SELECT user_id, mod_id, reason, timestamp FROM hidden_warnings WHERE guild_id=?", (str(guild.id),))
        rows = cursor.fetchall()
        
        if not rows:
            await target.send("📊 **Monthly Hidden Warning Report:** No warnings recorded this month.")
            continue
            
        lines = [f"• <@{uid}> warned by <@{mid}> on {timestamp}\n  Reason: {reason}" for uid, mid, reason, timestamp in rows]
        embed = discord.Embed(title="📊 Monthly Hidden Warnings Report", description="\n".join(lines), color=discord.Color.red())
        await target.send(embed=embed)
        
        with conn:
            conn.execute("DELETE FROM hidden_warnings WHERE guild_id=?", (str(guild.id),))

async def send_hydra_key_report_and_reset():
    channel = bot.get_channel(KEY_REPORT_CHANNEL_ID)
    if not channel: return
    cursor = conn.execute("SELECT username, hydra_used FROM keys")
    rows = cursor.fetchall()
    if not rows:
        await channel.send("Hydra key report: no data recorded this week.")
    else:
        await channel.send("**Weekly Hydra Key Usage Report**\n" + "\n".join([f"{u}: {used}/{HYDRA_MAX_KEYS} used" for u, used in rows]))
    with conn:
        conn.execute("UPDATE keys SET hydra_used = 0")

async def send_chimera_key_report_and_reset():
    channel = bot.get_channel(KEY_REPORT_CHANNEL_ID)
    if not channel: return
    cursor = conn.execute("SELECT username, chimera_used FROM keys")
    rows = cursor.fetchall()
    if not rows:
        await channel.send("Chimera key report: no data recorded this week.")
    else:
        await channel.send("**Weekly Chimera Key Usage Report**\n" + "\n".join([f"{u}: {used}/{CHIMERA_MAX_KEYS} used" for u, used in rows]))
    with conn:
        conn.execute("UPDATE keys SET chimera_used = 0")

async def check_persistent_reminders():
    now = int(time.time())
    cursor = conn.execute("SELECT id, user_id, channel_id, reminder_text FROM reminders WHERE due_time <= ?", (now,))
    rows = cursor.fetchall()
    for r_id, user_id, channel_id, text in rows:
        channel = bot.get_channel(int(channel_id))
        if channel:
            try:
                await channel.send(f"<@{user_id}> 🔔 Reminder: **{text}**")
            except discord.Forbidden:
                pass
        with conn:
            conn.execute("DELETE FROM reminders WHERE id=?", (r_id,))

# ============================================================
#  SECTION 4: EVENTS
# ============================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    
    # Prevents duplicate crons if the bot reconnects to the gateway
    if not hasattr(bot, 'scheduler_started'):
        bot.scheduler_started = True
        try: scheduler.start()
        except Exception: pass

        scheduler.add_job(send_weekly_warning, "cron", day_of_week="tue", hour=11, minute=0)
        scheduler.add_job(send_chimera_warning, "cron", day_of_week="wed", hour=11, minute=0)
        scheduler.add_job(send_monthly_warning_report, "cron", day=1, hour=12, minute=0)
        scheduler.add_job(send_hydra_key_report_and_reset, "cron", day_of_week="wed", hour=10, minute=59)
        scheduler.add_job(send_chimera_key_report_and_reset, "cron", day_of_week="thu", hour=11, minute=0)
        scheduler.add_job(check_persistent_reminders, "interval", seconds=60)

    try: await bot.tree.sync()
    except Exception as e: print("Slash sync failed:", e)

@bot.event
async def on_guild_join(guild):
    for ch in guild.text_channels:
        if ch.permissions_for(guild.me).send_messages:
            await ch.send("Hello! I am **Hydra Companion**.\nSupport server: https://discord.gg/DuemMm57jr")
            break

# ============================================================
#  SECTION 5: VIEWS
# ============================================================

class SuggestionConfirmView(discord.ui.View):
    def __init__(self, user_id, suggestion):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.suggestion = suggestion

    @discord.ui.button(label="Submit Anonymously", style=discord.ButtonStyle.green)
    async def submit_button(self, interaction, button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("Not your confirmation.", ephemeral=True)
        channel = interaction.client.get_channel(get_default_feedback_channel_id())
        if not channel: return await interaction.response.edit_message(content="Feedback channel misconfigured.", view=None)
        embed = discord.Embed(title="💡 New Anonymous Suggestion", description=self.suggestion, color=discord.Color.green())
        embed.set_footer(text="Anonymous submission")
        await channel.send(embed=embed)
        await interaction.response.edit_message(content="Suggestion submitted.", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction, button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("Not your confirmation.", ephemeral=True)
        await interaction.response.edit_message(content="Cancelled.", view=None)

class MessageMeButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Message Me", style=discord.ButtonStyle.primary)
    async def message_me(self, interaction, button):
        try:
            await interaction.user.send("Send your anonymous suggestion here.")
            await interaction.response.send_message("DM sent.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Enable DMs first.", ephemeral=True)

class SetupBaseView(discord.ui.View):
    def __init__(self, owner_id, guild, state):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.guild = guild
        self.state = state

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Not your setup wizard.", ephemeral=True)
            return False
        return True

# ------------------------------------------------------------
#  SETUP WIZARD VIEWS
# ------------------------------------------------------------

class CommandsChannelView(SetupBaseView):
    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Select the Commands Guide channel...")
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.Select):
        channel = interaction.guild.get_channel(select.values[0].id)
        set_guild_channel(self.guild.id, "commands_channel_id", channel.id)
        self.state["commands_channel"] = channel
        await interaction.response.edit_message(content=f"Commands Guide channel set to {channel.mention}.", view=None)
        await channel.send(embed=build_commands_guide_embed())
        await start_mercy_step(interaction, self.state)

class MercyChannelView(SetupBaseView):
    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Select the Mercy Guide channel...")
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.Select):
        channel = interaction.guild.get_channel(select.values[0].id)
        set_guild_channel(self.guild.id, "mercy_channel_id", channel.id)
        self.state["mercy_channel"] = channel
        await interaction.response.edit_message(content=f"Mercy Guide channel set to {channel.mention}.", view=None)
        await channel.send(embed=build_mercy_guide_embed())
        await start_suggestion_step(interaction, self.state)

class SuggestionChannelView(SetupBaseView):
    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Select the Suggestion channel (optional)...")
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.Select):
        channel = interaction.guild.get_channel(select.values[0].id)
        set_guild_channel(self.guild.id, "suggestion_channel_id", channel.id)
        self.state["suggestion_channel"] = channel
        await interaction.response.edit_message(content=f"Suggestion channel set to {channel.mention}.", view=None)
        embed = discord.Embed(
            title="💡 Anonymous Suggestions",
            description="Want to submit feedback privately?\nClick the button below and I'll open a DM where you can send your anonymous suggestion.",
            color=discord.Color.green()
        )
        await channel.send(embed=embed, view=MessageMeButton())
        await start_feedback_step(interaction, self.state)

    @discord.ui.button(label="Skip this step", style=discord.ButtonStyle.secondary)
    async def skip_step(self, interaction: discord.Interaction, button):
        set_guild_channel(self.guild.id, "suggestion_channel_id", None)
        self.state["suggestion_channel"] = None
        await interaction.response.edit_message(content="Suggestion channel skipped.", view=None)
        await start_feedback_step(interaction, self.state)

class FeedbackChannelView(SetupBaseView):
    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Select the Feedback channel (optional)...")
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.Select):
        channel = interaction.guild.get_channel(select.values[0].id)
        set_guild_channel(self.guild.id, "feedback_channel_id", channel.id)
        self.state["feedback_channel"] = channel
        await interaction.response.edit_message(content=f"Feedback channel set to {channel.mention}.", view=None)
        await start_warning_step(interaction, self.state)

    @discord.ui.button(label="Skip this step", style=discord.ButtonStyle.secondary)
    async def skip_step(self, interaction: discord.Interaction, button):
        set_guild_channel(self.guild.id, "feedback_channel_id", None)
        self.state["feedback_channel"] = None
        await interaction.response.edit_message(content="Feedback channel skipped.", view=None)
        await start_warning_step(interaction, self.state)

class WarningChannelView(SetupBaseView):
    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Select the Hydra Warning channel...")
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.Select):
        channel = interaction.guild.get_channel(select.values[0].id)
        set_guild_channel(self.guild.id, "warning_channel_id", channel.id)
        self.state["warning_channel"] = channel
        await interaction.response.edit_message(content=f"Warning channel set to {channel.mention}.", view=None)
        await start_report_step(interaction, self.state)

class ReportChannelView(SetupBaseView):
    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Select Hidden Warning Report channel...")
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.Select):
        channel = interaction.guild.get_channel(select.values[0].id)
        set_guild_channel(self.guild.id, "warning_report_channel_id", channel.id)
        self.state["warning_report_channel"] = channel
        await finish_setup_summary(interaction, self.state)

    @discord.ui.button(label="Skip this step", style=discord.ButtonStyle.secondary)
    async def skip_step(self, interaction: discord.Interaction, button):
        set_guild_channel(self.guild.id, "warning_report_channel_id", None)
        self.state["warning_report_channel"] = None
        await finish_setup_summary(interaction, self.state)

async def start_commands_step(interaction, state):
    await interaction.response.send_message("Step 1/6 — Select the **Commands Guide** channel (required):", view=CommandsChannelView(interaction.user.id, interaction.guild, state))

async def start_mercy_step(interaction, state):
    await interaction.followup.send("Step 2/6 — Select the **Mercy Guide** channel (required):", view=MercyChannelView(interaction.user.id, interaction.guild, state))

async def start_suggestion_step(interaction, state):
    await interaction.followup.send("Step 3/6 — Select the **Suggestion** channel (optional):", view=SuggestionChannelView(interaction.user.id, interaction.guild, state))

async def start_feedback_step(interaction, state):
    await interaction.followup.send("Step 4/6 — Select the **Feedback** channel (optional):", view=FeedbackChannelView(interaction.user.id, interaction.guild, state))

async def start_warning_step(interaction, state):
    await interaction.followup.send("Step 5/6 — Select the **Hydra Warning** channel (required):", view=WarningChannelView(interaction.user.id, interaction.guild, state))

async def start_report_step(interaction, state):
    await interaction.followup.send("Step 6/6 — Select the **Hidden Warning Report** channel (optional):", view=ReportChannelView(interaction.user.id, interaction.guild, state))

async def finish_setup_summary(interaction, state):
    guild = interaction.guild
    channels = get_guild_channels(guild.id)

    def fmt(ch): return ch.mention if isinstance(ch, discord.TextChannel) else "Skipped"

    embed = discord.Embed(title="✅ Hydra Companion Setup Complete", color=discord.Color.green())
    embed.add_field(name="Commands Guide Channel", value=fmt(guild.get_channel(channels["commands_channel_id"])), inline=False)
    embed.add_field(name="Mercy Guide Channel", value=fmt(guild.get_channel(channels["mercy_channel_id"])), inline=False)
    embed.add_field(name="Suggestion Channel", value=fmt(guild.get_channel(channels["suggestion_channel_id"])), inline=False)
    embed.add_field(name="Feedback Channel", value=fmt(guild.get_channel(channels["feedback_channel_id"])), inline=False)
    embed.add_field(name="Warning Channel", value=fmt(guild.get_channel(channels["warning_channel_id"])), inline=False)
    embed.add_field(name="Report Channel", value=fmt(guild.get_channel(channels["warning_report_channel_id"])), inline=False)

    # Edit the existing message smoothly to prevent interaction failed crashes
    await interaction.response.edit_message(content="Wizard completed!", embed=embed, view=None)

# ============================================================
#  SECTION 6: on_message (ANONYMOUS SUGGESTIONS)
# ============================================================

@bot.event
async def on_message(message):
    if message.author.bot: return

    if isinstance(message.channel, discord.DMChannel):
        embed = discord.Embed(
            title="Confirm Anonymous Suggestion",
            description=f"You wrote:\n\n**{message.content}**\n\nWould you like to submit this anonymously?",
            color=discord.Color.blue()
        )
        await message.author.send(embed=embed, view=SuggestionConfirmView(message.author.id, message.content))
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
    await ctx.send("**Hydra Chest Requirements**\nNormal – Over 6.66M\nHard – Over 20.4M\nBrutal – Over 29.4M\nNightmare – Over 36.6M")
    await ctx.message.delete()

@bot.command(name="support")
async def support_prefix(ctx):
    await ctx.send("**Support Server**\nIf you need help with Hydra Companion, join here:\nhttps://discord.gg/DuemMm57jr")

@bot.command(name="developer")
async def developer_prefix(ctx):
    await ctx.send("**Hydra Companion Developer Resources**\n\n**GitHub:** https://github.com/sketeraid")

def build_commands_guide_embed():
    embed = discord.Embed(title="Hydra Companion — FULL COMMAND GUIDE", color=discord.Color.blurple())
    embed.add_field(name="GENERAL COMMANDS", value="`$test` — Check if online.\n`$chests` — Hydra Clash chests.\n`/champion [name]` — Get optimal builds.", inline=False)
    embed.add_field(name="ADMIN / UTILITY", value="`/announce <msg>` — Post announcement.\n`/purge <amount>` — Delete messages.\n`/kick` & `/ban` — Moderation.\n`/warn` — Silently log warning.", inline=False)
    embed.add_field(name="ANONYMOUS SUGGESTIONS", value="Click **Message Me** → DM bot → Confirm → Submit anonymously.", inline=False)
    embed.add_field(name="REMINDERS", value="`/reminder set` — Set reminder.\n`/reminder list` — List active.\n`/reminder cancel` — Cancel.", inline=False)
    embed.add_field(name="SHOULD I PULL?", value="`/pull-advice` — Random pull advice.", inline=False)
    embed.add_field(name="MERCY TRACKER", value="`/mercy check <shard>`\n`/mercy all`\n`/mercy table`\n`/mercy compare @user`\n`/mercy add <shard> <amount> ...`\n`/mercy clear <shard>`", inline=False)
    return embed

@bot.command(name="commands")
async def commands_prefix(ctx):
    channels = get_guild_channels(ctx.guild.id)
    ch_id = channels["commands_channel_id"]
    channel = ctx.guild.get_channel(ch_id) if ch_id else ctx.channel
    await channel.send(embed=build_commands_guide_embed())

def build_mercy_guide_embed():
    embed = discord.Embed(title="Hydra Companion — MERCY TRACKING GUIDE", color=discord.Color.gold())
    embed.add_field(name="BEFORE YOU START", value="Begin tracking after your last Legendary pull.", inline=False)
    embed.add_field(name="📝 Unified Logging: /mercy add", value="Use `/mercy add` to log a batch of pulls. You can optionally tell the bot exactly *which pull number* was an Epic, Legendary, or Mythical so it can flawlessly calculate your remaining pity—just like RAID does under the hood.", inline=False)
    embed.add_field(name="📊 /mercy check", value="Shows detailed pity, chances, and readiness for a specific shard.", inline=False)
    embed.add_field(name="📋 /mercy all OR /mercy table", value="Provides a beautiful, clean overview of all your tracked shards.", inline=False)
    embed.add_field(name="🧹 /mercy clear", value="Manually force a shard's counters back to zero.", inline=False)
    return embed

@bot.command(name="mercyguide")
@commands.has_permissions(administrator=True)
async def mercy_guide_prefix(ctx):
    await ctx.send(embed=build_mercy_guide_embed())

@bot.command(name="purge")
@commands.has_permissions(administrator=True)
async def purge_prefix(ctx, amount: int):
    await ctx.message.delete()
    if amount <= 0 or amount > 100:
        warn = await ctx.send("Please enter a number between 1 and 100.")
        return await warn.delete(delay=5)
    
    deleted = await ctx.channel.purge(limit=amount)
    confirm = await ctx.send(f"✅ Deleted {len(deleted)} messages.")
    await confirm.delete(delay=5)

# -----------------------------
# PREFIX MERCY ADD 
# -----------------------------
@bot.command(name="mercyadd")
async def mercyadd_cmd(ctx, shard_type: str, amount: int, epic_on: int = 0, legendary_on: int = 0, mythical_on: int = 0):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES: return await ctx.send("Invalid shard type.")
    if amount <= 0: return await ctx.send("Amount must be positive.")

    e, l, m = process_mercy_pulls(ctx.author.id, shard_type, amount, epic_on, legendary_on, mythical_on)
    
    emoji = get_shard_emoji(shard_type)
    msg = f"{ctx.author.mention}, recorded **{amount}** pulls to your {emoji} **{shard_type.capitalize()}** mercy.\n"
    if epic_on > 0 or legendary_on > 0 or mythical_on > 0:
        msg += "*(Pity resets applied perfectly based on exactly when you pulled your rarities)*\n"
    
    if shard_type in ("ancient", "void"): msg += f"**Epic:** {e}  |  "
    msg += f"**Legendary:** {l}"
    if shard_type == "primal": msg += f"  |  **Mythical:** {m}"
    await ctx.send(msg)

# ============================================================
#  SECTION 8: SLASH COMMANDS 
# ============================================================

async def shard_autocomplete(interaction, current):
    return [app_commands.Choice(name=s.capitalize(), value=s) for s in SHARD_CHOICES if current.lower() in s]

# ------------------------------------------------------------
# CHAMPION INFO SLASH COMMAND (CONDENSES TO MATCH ON-THE-FLY)
# ------------------------------------------------------------
async def champion_autocomplete(interaction: discord.Interaction, current: str):
    matches = [
        app_commands.Choice(name=name, value=name)
        for name in champions_data.keys()
        if current.lower() in name.lower()
    ]
    return matches[:25]

@tree.command(name="champion", description="Get optimal builds, stats, and info for a specific champion.")
@app_commands.describe(name="The name of the champion")
@app_commands.autocomplete(name=champion_autocomplete)
async def champion_info_slash(interaction: discord.Interaction, name: str):
    if not champions_data:
        return await interaction.response.send_message("Champion database is currently empty or missing.", ephemeral=True)

    champ_key = None
    for key in champions_data.keys():
        if key.lower() == name.lower():
            champ_key = key
            break

    if not champ_key:
        return await interaction.response.send_message(f"Could not find a champion named **{name}**.", ephemeral=True)

    data = champions_data[champ_key]

    # Dynamically set the embed color based on Champion Rarity
    rarity = data.get('rarity', 'Unknown').lower()
    if rarity == "mythical":
        color = discord.Color.red()
    elif rarity == "legendary":
        color = discord.Color.gold()
    elif rarity == "epic":
        color = discord.Color.purple()
    elif rarity == "rare":
        color = discord.Color.blue()
    elif rarity == "uncommon":
        color = discord.Color.green()
    elif rarity == "common":
        color = discord.Color.light_grey()
    else:
        color = discord.Color.dark_theme()

    embed = discord.Embed(
        title=f"🔥 {data.get('name', champ_key)}",
        url=data.get('url', ''),
        color=color
    )

    embed.add_field(name="⚔️ Rarity", value=f"`{data.get('rarity', 'Unknown')}`", inline=True)
    embed.add_field(name="🔮 Affinity", value=f"`{data.get('affinity', 'Unknown')}`", inline=True)
    embed.add_field(name="⚔️ Faction", value=f"`{data.get('faction', 'Unknown')}`", inline=True)
    embed.add_field(name="🛡️ Role", value=f"`{data.get('role', 'Unknown')}`", inline=True)
    embed.add_field(name="⭐ Star Rating", value=f"`{data.get('rating', 'Unrated')}`", inline=True)

    areas = data.get('top_areas', [])
    areas_str = ", ".join(areas) if areas else "General PvE"
    embed.add_field(name="🏰 Top Viable Areas", value=f"`{areas_str}`", inline=False)

    # ----------------------------------------------------
    # NEW DYNAMIC SKILL EXTRACTOR
    # ----------------------------------------------------
    active_skills = data.get('active_skills', [])
    for skill in active_skills:
        # Discord has a 1024 character limit per field, so we slice it just in case!
        embed.add_field(name=f"⚔️ {skill.get('title', 'Active Skill')}", value=skill.get('desc', 'No description')[:1021] + "...", inline=False)

    passive_skills = data.get('passive_skills', [])
    for skill in passive_skills:
        embed.add_field(name=f"🛡️ {skill.get('title', 'Passive Skill')}", value=skill.get('desc', 'No description')[:1021] + "...", inline=False)

    moves = data.get('moves_multipliers', [])
    moves_str = "\n".join([f"🔹 {m}" for m in moves]) if moves else "No listed formula"
    embed.add_field(name="📊 Skill Damage Multipliers", value=moves_str, inline=False)

    avatar_url = bot.user.display_avatar.url if bot.user.display_avatar else None
    embed.set_footer(text="Hydra Companion • Strategy Insights", icon_url=avatar_url)

    await interaction.response.send_message(embed=embed)

# ------------------------------------------------------------
# KEY TRACKING (MODAL POP-UP)
# ------------------------------------------------------------
keys_group = app_commands.Group(name="keys", description="Track Hydra and Chimera key usage.")

class KeyUsageModal(discord.ui.Modal, title='Log Key Usage'):
    amount = discord.ui.TextInput(
        label='How many keys did you use?',
        style=discord.TextStyle.short,
        placeholder='Enter a number (e.g., 1, 2, 3)',
        required=True,
        max_length=1
    )

    def __init__(self, boss: str):
        super().__init__()
        self.boss = boss

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        amount_used_str = self.amount.value

        if not amount_used_str.isdigit():
            return await interaction.response.send_message("Please enter a valid number.", ephemeral=True)
        
        amount_used = int(amount_used_str)
        if amount_used <= 0: return await interaction.response.send_message("Must be greater than 0.", ephemeral=True)

        hydra_used, chimera_used = get_key_row(user.id, user.display_name)

        if self.boss == "hydra":
            if hydra_used + amount_used > HYDRA_MAX_KEYS:
                return await interaction.response.send_message(f"You cannot use {amount_used} keys. You only have {HYDRA_MAX_KEYS - hydra_used} left.", ephemeral=True)
            hydra_used += amount_used
            set_key_row(user.id, user.display_name, hydra_used, chimera_used)
            await interaction.response.send_message(f"Logged {amount_used} Hydra key(s)! Only {HYDRA_MAX_KEYS - hydra_used}/{HYDRA_MAX_KEYS} keys remain, warrior.")

        elif self.boss == "chimera":
            if chimera_used + amount_used > CHIMERA_MAX_KEYS:
                return await interaction.response.send_message(f"You cannot use {amount_used} keys. You only have {CHIMERA_MAX_KEYS - chimera_used} left.", ephemeral=True)
            chimera_used += amount_used
            set_key_row(user.id, user.display_name, hydra_used, chimera_used)
            await interaction.response.send_message(f"Logged {amount_used} Chimera key(s)! Only {CHIMERA_MAX_KEYS - chimera_used}/{CHIMERA_MAX_KEYS} keys remain, warrior.")

@keys_group.command(name="add", description="Record a used Hydra or Chimera key via Pop-Up.")
@app_commands.choices(boss=[app_commands.Choice(name="Hydra", value="hydra"), app_commands.Choice(name="Chimera", value="chimera")])
async def keys_add_slash(interaction: discord.Interaction, boss: str):
    await interaction.response.send_modal(KeyUsageModal(boss))

@keys_group.command(name="report", description="View Hydra and Chimera key usage for all users.")
@app_commands.default_permissions(administrator=True)
async def keys_report_slash(interaction):
    cursor = conn.execute("SELECT username, hydra_used, chimera_used FROM keys")
    rows = cursor.fetchall()
    if not rows: return await interaction.response.send_message("No key usage recorded yet.")

    def status_emoji(used, max_keys):
        if used >= max_keys: return "🟢"
        if used == 0: return "🔴"
        return "🟡"

    lines = [f"**{u}** | Hydra: {status_emoji(hu, HYDRA_MAX_KEYS)} ({hu}/{HYDRA_MAX_KEYS}) | Chimera: {status_emoji(cu, CHIMERA_MAX_KEYS)} ({cu}/{CHIMERA_MAX_KEYS})" for u, hu, cu in rows]
    await interaction.response.send_message(embed=discord.Embed(title="Key Usage Overview", description="\n".join(lines), color=discord.Color.dark_teal()))

# ------------------------------------------------------------
# STANDALONE ADMIN & UTILITY COMMANDS
# ------------------------------------------------------------
@tree.command(name="setup", description="Start the Hydra Companion setup wizard.")
@app_commands.default_permissions(administrator=True)
async def admin_setup_slash(interaction):
    await start_commands_step(interaction, {})

@tree.command(name="announce", description="Post an announcement to the configured announcement channel.")
@app_commands.default_permissions(administrator=True)
async def announce_slash(interaction, message: str):
    channel = interaction.client.get_channel(ANNOUNCE_CHANNEL_ID)
    if not channel: return await interaction.response.send_message("Announcement channel missing.", ephemeral=True)
    embed = discord.Embed(title="📢 Announcement", description=message, color=discord.Color.blue())
    embed.set_footer(text=f"Posted by {interaction.user}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
    embed.timestamp = discord.utils.utcnow()
    await channel.send(embed=embed)
    await interaction.response.send_message("Announcement sent.", ephemeral=True)

@tree.command(name="purge", description="Delete a number of messages from the current channel.")
@app_commands.default_permissions(administrator=True)
async def purge_slash(interaction, amount: int):
    if amount <= 0 or amount > 100:
        return await interaction.response.send_message("Please enter a number between 1 and 100.", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"✅ Deleted {len(deleted)} messages.", ephemeral=True)

@tree.command(name="kick", description="Kick a user from the server")
@app_commands.default_permissions(administrator=True)
async def kick_slash(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 Kicked {member.mention}. Reason: {reason}")

@tree.command(name="ban", description="Ban a user from the server")
@app_commands.default_permissions(administrator=True)
async def ban_slash(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 Banned {member.mention}. Reason: {reason}")

@tree.command(name="warn", description="Silently log a warning for a user. Appears in monthly report.")
@app_commands.default_permissions(administrator=True)
async def warn_slash(interaction: discord.Interaction, member: discord.Member, reason: str):
    with conn:
        conn.execute("INSERT INTO hidden_warnings (guild_id, user_id, mod_id, reason) VALUES (?, ?, ?, ?)",
                     (str(interaction.guild.id), str(member.id), str(interaction.user.id), reason))
    await interaction.response.send_message(f"✅ Secretly warned {member.display_name} for: {reason}", ephemeral=True)

@tree.command(name="reboot", description="Reboots the bot cleanly without resetting configurations.")
@app_commands.default_permissions(administrator=True)
async def reboot_slash(interaction: discord.Interaction):
    await interaction.response.send_message("🔄 Rebooting the bot... Be right back!", ephemeral=True)
    os.execv(sys.executable, ['python'] + sys.argv)

@tree.command(name="suggest-button", description="Post the anonymous suggestion button in the current channel.")
@app_commands.default_permissions(administrator=True)
async def suggest_button_slash(interaction):
    if interaction.channel.id not in ALLOWED_SUGGEST_BUTTON_CHANNELS:
        return await interaction.response.send_message("This channel is not approved.", ephemeral=True)
    embed = discord.Embed(title="💡 Anonymous Suggestions", description="Want to submit feedback privately?\nClick the button below and I'll open a DM where you can send your anonymous suggestion.", color=discord.Color.green())
    await interaction.response.send_message(embed=embed, view=MessageMeButton())

@tree.command(name="commands-guide", description="Post the full commands guide.")
@app_commands.default_permissions(administrator=True)
async def commands_guide_slash(interaction):
    await interaction.channel.send(embed=build_commands_guide_embed())
    await interaction.response.send_message("Commands guide posted.", ephemeral=True)

@tree.command(name="mercy-guide", description="Post the mercy tracking guide.")
@app_commands.default_permissions(administrator=True)
async def mercy_guide_slash(interaction):
    await interaction.channel.send(embed=build_mercy_guide_embed())
    await interaction.response.send_message("Mercy guide posted.", ephemeral=True)

# ------------------------------------------------------------
# PULL ADVICE & GENERAL INFO
# ------------------------------------------------------------
@tree.command(name="pull-advice", description="Get advice on whether you should pull right now.")
async def pull_advice_slash(interaction, event: str = None):
    decision = random.choice(["yes", "no"])
    answer = random.choice(["Yes — send it.", "Absolutely. This shard is calling your name.", "Yep. You will regret skipping more than pulling."] if decision == "yes" else ["No — save your resources.", "Skip. This shard is not worth it.", "Not this one. Your future self will thank you."])
    embed = discord.Embed(title="🎲 Should you pull?", description=answer, color=discord.Color.green() if decision == "yes" else discord.Color.red())
    embed.add_field(name="Requested by", value=interaction.user.mention, inline=False)
    if event: embed.add_field(name="Event", value=event, inline=False)
    await interaction.response.send_message(embed=embed)

@tree.command(name="support", description="Show the Hydra Companion support server link.")
async def support_slash(interaction):
    await interaction.response.send_message("**Support Server**\nhttps://discord.gg/DuemMm57jr")

# ------------------------------------------------------------
# MERCY SLASH COMMANDS
# ------------------------------------------------------------
mercy_group = app_commands.Group(name="mercy", description="View and manage your shard mercy counters.")

@mercy_group.command(name="add", description="Log your pulls, specifying EXACTLY which pull triggered a reset.")
@app_commands.describe(
    shard_type="Which shard did you pull?",
    amount="Total shards pulled in this batch (e.g., 10).",
    epic_on="Pull # of your LAST Epic (e.g., 4). Leave 0 if none.",
    legendary_on="Pull # of your LAST Legendary (e.g., 7). Leave 0 if none.",
    mythical_on="Pull # of your LAST Mythical (Primal only). Leave 0 if none."
)
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_add_slash(interaction, shard_type: str, amount: int, epic_on: int = 0, legendary_on: int = 0, mythical_on: int = 0):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES: return await interaction.response.send_message("Invalid shard.", ephemeral=True)
    if amount <= 0: return await interaction.response.send_message("Amount must be positive.", ephemeral=True)

    e, l, m = process_mercy_pulls(interaction.user.id, shard_type, amount, epic_on, legendary_on, mythical_on)
    
    emoji = get_shard_emoji(shard_type)
    msg = f"Recorded **{amount}** pulls to your {emoji} **{shard_type.capitalize()}** mercy.\n"
    if epic_on > 0 or legendary_on > 0 or mythical_on > 0:
        msg += "*(Pity resets applied perfectly based on exactly when you pulled your rarities)*\n"
        
    msg += f"**Current Standings:**\n"
    if shard_type in ("ancient", "void"): msg += f"• **Epic:** {e}\n"
    msg += f"• **Legendary:** {l}"
    if shard_type == "primal": msg += f"\n• **Mythical:** {m}"
    
    await interaction.response.send_message(msg)

@mercy_group.command(name="check", description="Show your detailed mercy status for a specific shard.")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_check_slash(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES: return await interaction.response.send_message("Invalid shard.", ephemeral=True)
    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)
    
    emoji = get_shard_emoji(shard_type)
    embed = discord.Embed(title=f"{emoji} {shard_type.capitalize()} Mercy Status", color=discord.Color.dark_theme())

    if shard_type in ("ancient", "void"):
        embed.add_field(name="🟣 Epic", value=f"**Pity:** {epic}\n**Chance:** {calc_epic_chance(shard_type, epic):.2f}%", inline=True)
    
    embed.add_field(name="🟡 Legendary", value=f"**Pity:** {legendary}\n**Chance:** {calc_legendary_chance(shard_type, legendary):.2f}%", inline=True)
    
    mythical_chance = None
    if shard_type == "primal":
        mythical_chance = calc_mythical_chance(shard_type, mythical)
        embed.add_field(name="🔴 Mythical", value=f"**Pity:** {mythical}\n**Chance:** {mythical_chance:.2f}%", inline=True)

    color, ready, status_msg = compute_readiness_color_and_flag(shard_type, calc_legendary_chance(shard_type, legendary), mythical_chance)
    embed.color = color
    embed.description = f"**Status:** {status_msg}"
    
    await interaction.response.send_message(embed=embed)

@mercy_group.command(name="all", description="Show a clean overview of all your mercy counters.")
async def mercy_all_slash(interaction):
    embed = discord.Embed(title=f"📊 {interaction.user.display_name}'s Mercy Overview", color=discord.Color.blue())
    
    for shard in BASE_RATES:
        epic, legendary, mythical = get_mercy_row(interaction.user.id, shard)
        emoji = get_shard_emoji(shard)
        
        text = ""
        if shard in ("ancient", "void"): text += f"**Epic:** {epic} pulls ({calc_epic_chance(shard, epic):.2f}%)\n"
        
        legendary_chance = calc_legendary_chance(shard, legendary)
        text += f"**Legendary:** {legendary} pulls ({legendary_chance:.2f}%)"
        
        mythical_chance = None
        if shard == "primal":
            mythical_chance = calc_mythical_chance(shard, mythical)
            text += f"\n**Mythical:** {mythical} pulls ({mythical_chance:.2f}%)"

        _, ready, _ = compute_readiness_color_and_flag(shard, legendary_chance, mythical_chance)
        if ready: text += "\n🔥 **Ready to pull!**"
        
        embed.add_field(name=f"{emoji} {shard.capitalize()}", value=text, inline=True)

    await interaction.response.send_message(embed=embed)

@mercy_group.command(name="table", description="Display a detailed mercy dashboard for all shards.")
async def mercy_table_slash(interaction):
    embed = discord.Embed(title=f"🗃️ {interaction.user.display_name}'s Mercy Dashboard", color=discord.Color.dark_gold())
    
    for shard in BASE_RATES:
        epic, legendary, mythical = get_mercy_row(interaction.user.id, shard)
        emoji = get_shard_emoji(shard)
        
        legendary_chance = calc_legendary_chance(shard, legendary)
        mythical_chance = calc_mythical_chance(shard, mythical) if shard == "primal" else None

        lines = []
        if shard in ("ancient", "void"):
            lines.append(f"🟣 **Epic:** {epic} pulls ({calc_epic_chance(shard, epic):.2f}%)")
        lines.append(f"🟡 **Legendary:** {legendary} pulls ({legendary_chance:.2f}%)")
        if shard == "primal":
            lines.append(f"🔴 **Mythical:** {mythical} pulls ({mythical_chance:.2f}%)")
        
        _, _, status = compute_readiness_color_and_flag(shard, legendary_chance, mythical_chance)
        lines.append(f"**Status:** {status}")
        
        embed.add_field(name=f"{emoji} {shard.capitalize()}", value="\n".join(lines), inline=False)

    await interaction.response.send_message(embed=embed)

@mercy_group.command(name="compare", description="Compare your mercy counters with another user.")
async def mercy_compare_slash(interaction, member: discord.Member):
    user1, user2 = interaction.user, member
    embed = discord.Embed(title=f"⚖️ Mercy Compare: {user1.display_name} vs {user2.display_name}", color=discord.Color.purple())

    for shard in BASE_RATES:
        e1, l1, m1 = get_mercy_row(user1.id, shard)
        e2, l2, m2 = get_mercy_row(user2.id, shard)
        emoji = get_shard_emoji(shard)

        def get_stats(uname, e, l, m):
            if shard in ("ancient", "void"): return f"**{uname}:** Epic {e} | Leg {l}"
            elif shard == "primal": return f"**{uname}:** Leg {l} | Myth {m}"
            else: return f"**{uname}:** Leg {l}"

        lines = [get_stats(user1.display_name, e1, l1, m1), get_stats(user2.display_name, e2, l2, m2)]
        embed.add_field(name=f"{emoji} {shard.capitalize()}", value="\n".join(lines), inline=False)
        
    await interaction.response.send_message(embed=embed)

@mercy_group.command(name="clear", description="Reset your mercy counters to zero for a specific shard.")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_clear_slash(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES: return await interaction.response.send_message("Invalid shard.", ephemeral=True)
    set_mercy_row(interaction.user.id, shard_type, 0, 0, 0)
    await interaction.response.send_message(f"🧹 Your **{shard_type}** mercy has been reset to 0.")

# ------------------------------------------------------------
# PERSISTENT REMINDER SLASH COMMANDS
# ------------------------------------------------------------
reminder_group = app_commands.Group(name="reminder", description="Set and manage persistent personal reminders.")

@reminder_group.command(name="set", description="Create a reminder for a future time (e.g., 10m, 2h, 1d).")
async def reminder_set_slash(interaction, duration: str, reminder: str):
    unit, amount = duration[-1].lower(), duration[:-1]
    if not amount.isdigit() or unit not in ["m", "h", "d"]:
        return await interaction.response.send_message("Time must be a number followed by m/h/d (e.g. `10m`, `2h`, `1d`).", ephemeral=True)
    
    seconds = int(amount) * {"m": 60, "h": 3600, "d": 86400}[unit]
    due_time = int(time.time()) + seconds
    
    with conn:
        cursor = conn.execute("INSERT INTO reminders (user_id, channel_id, reminder_text, due_time) VALUES (?, ?, ?, ?)",
                              (str(interaction.user.id), str(interaction.channel.id), reminder, due_time))
        reminder_id = cursor.lastrowid
    
    await interaction.response.send_message(f"✅ Reminder **#{reminder_id}** set!\nI will remind you <t:{due_time}:R> about: *{reminder}*", ephemeral=True)

@reminder_group.command(name="list", description="View all your active reminders.")
async def reminder_list_slash(interaction):
    cursor = conn.execute("SELECT id, reminder_text, due_time FROM reminders WHERE user_id=?", (str(interaction.user.id),))
    rows = cursor.fetchall()
    
    if not rows: return await interaction.response.send_message("You have no active reminders.", ephemeral=True)
    
    msg = "**Your Active Reminders:**\n" + "\n".join([f"• **#{r_id}** — {text} (Due <t:{due}:R>)" for r_id, text, due in rows])
    await interaction.response.send_message(msg, ephemeral=True)

@reminder_group.command(name="cancel", description="Cancel one of your active reminders.")
async def reminder_cancel_slash(interaction, reminder_id: int):
    cursor = conn.execute("SELECT id FROM reminders WHERE id=? AND user_id=?", (reminder_id, str(interaction.user.id)))
    if not cursor.fetchone():
        return await interaction.response.send_message(f"No reminder found with ID #{reminder_id}.", ephemeral=True)
        
    with conn:
        conn.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
    await interaction.response.send_message(f"❎ Reminder #{reminder_id} cancelled.", ephemeral=True)

# ============================================================
#  REGISTER GROUPS & RUN BOT
# ============================================================

tree.add_command(mercy_group)
tree.add_command(reminder_group)
tree.add_command(keys_group)

bot.run(TOKEN)