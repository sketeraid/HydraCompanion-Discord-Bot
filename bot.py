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
intents.members = True

bot = commands.Bot(command_prefix="$", intents=intents)
tree = bot.tree
scheduler = AsyncIOScheduler(timezone="Europe/London")

HYDRA_WARNING_CHANNEL_ID = 1461342242470887546
ANNOUNCE_CHANNEL_ID = 1461342242470887546
SUGGESTION_CHANNEL_ID = 1464216800651640893

ALLOWED_SUGGEST_BUTTON_CHANNELS = {
    1463963533640335423,
    1463963575780507669
}

SHARD_CHOICES = ["ancient", "void", "primal", "sacred"]

SHARD_RATES = {
    "ancient": {"💙 Rare": 91.5, "💜 Epic": 8, "🌟 Legendary": 0.5},
    "void": {"💙 Rare": 91.5, "💜 Epic": 8, "🌟 Legendary": 0.5},
    "primal": {"💙 Rare": 82.5, "💜 Epic": 16, "🌟 Legendary": 1, "🔥 Mythical": 0.5},
    "sacred": {"💙 Rare": 0, "💜 Epic": 94, "🌟 Legendary": 6}
}

BASE_RATES = {
    "ancient": {"epic": 8.0, "legendary": 0.5, "mythical": 0.0},
    "void": {"epic": 8.0, "legendary": 0.5, "mythical": 0.0},
    "primal": {"epic": 16.0, "legendary": 1.0, "mythical": 0.5},
    "sacred": {"epic": 94.0, "legendary": 6.0, "mythical": 0.0}
}

# ============================================================
#  SECTION 2: DATABASE SETUP
# ============================================================

conn = sqlite3.connect("mercy.db")
c = conn.cursor()

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

# ============================================================
#  SECTION 3: MERCY HELPERS
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
    c.execute(
        "SELECT epic_pity, legendary_pity, mythical_pity FROM mercy WHERE user_id=? AND shard_type=?",
        (str(user_id), shard_type)
    )
    row = c.fetchone()
    if row is None:
        c.execute("INSERT INTO mercy (user_id, shard_type) VALUES (?, ?)", (str(user_id), shard_type))
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

def ensure_guild_row(guild_id):
    c.execute("SELECT guild_id FROM guild_channels WHERE guild_id=?", (str(guild_id),))
    if c.fetchone() is None:
        c.execute("INSERT INTO guild_channels (guild_id) VALUES (?)", (str(guild_id),))
        conn.commit()

def set_guild_channel(guild_id, field, channel_id):
    ensure_guild_row(guild_id)
    c.execute(f"UPDATE guild_channels SET {field}=? WHERE guild_id=?", (channel_id, str(guild_id)))
    conn.commit()

def get_guild_channels(guild_id):
    c.execute("""
        SELECT warning_channel_id, suggestion_channel_id, feedback_channel_id,
               commands_channel_id, mercy_channel_id
        FROM guild_channels WHERE guild_id=?
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
    c.execute("SELECT feedback_channel_id FROM guild_channels WHERE feedback_channel_id IS NOT NULL LIMIT 1")
    row = c.fetchone()
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

# ============================================================
#  SECTION 3.5: SCHEDULER WARNING TASKS
# ============================================================

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
#  SECTION 4: EVENTS
# ============================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        scheduler.start()
    except Exception:
        pass
    scheduler.add_job(send_weekly_warning, "cron", day_of_week="tue", hour=10, minute=0)
    scheduler.add_job(send_chimera_warning, "cron", day_of_week="wed", hour=11, minute=0)
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Slash sync failed:", e)

@bot.event
async def on_guild_join(guild):
    for ch in guild.text_channels:
        if ch.permissions_for(guild.me).send_messages:
            await ch.send(
                "Hello! I am **Hydra Companion**.\n"
                "Support server: https://discord.gg/DuemMm57jr"
            )
            break

# ============================================================
#  SECTION 5: VIEWS (START)
# ============================================================

class SuggestionConfirmView(discord.ui.View):
    def __init__(self, user_id, suggestion):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.suggestion = suggestion

    @discord.ui.button(label="Submit Anonymously", style=discord.ButtonStyle.green)
    async def submit_button(self, interaction, button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your confirmation.", ephemeral=True)
        channel = interaction.client.get_channel(get_default_feedback_channel_id())
        if not channel:
            return await interaction.response.edit_message(content="Feedback channel misconfigured.", view=None)
        embed = discord.Embed(
            title="💡 New Anonymous Suggestion",
            description=self.suggestion,
            color=discord.Color.green()
        )
        embed.set_footer(text="Anonymous submission")
        await channel.send(embed=embed)
        await interaction.response.edit_message(content="Suggestion submitted.", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction, button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your confirmation.", ephemeral=True)
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


# ============================================================
#  STEP 1 — COMMANDS CHANNEL
# ============================================================

class CommandsChannelView(SetupBaseView):
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select the Commands Guide channel..."
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.Select):
        selected = select.values[0]  # AppCommandChannel
        channel = interaction.guild.get_channel(selected.id)  # Convert to real channel

        set_guild_channel(self.guild.id, "commands_channel_id", channel.id)
        self.state["commands_channel"] = channel

        await interaction.response.edit_message(
            content=f"Commands Guide channel set to {channel.mention}.",
            view=None
        )

        await channel.send(embed=build_commands_guide_embed())
        await start_mercy_step(interaction, self.state)


# ============================================================
#  STEP 2 — MERCY CHANNEL
# ============================================================

class MercyChannelView(SetupBaseView):
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select the Mercy Guide channel..."
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.Select):
        selected = select.values[0]
        channel = interaction.guild.get_channel(selected.id)

        set_guild_channel(self.guild.id, "mercy_channel_id", channel.id)
        self.state["mercy_channel"] = channel

        await interaction.response.edit_message(
            content=f"Mercy Guide channel set to {channel.mention}.",
            view=None
        )

        await channel.send(embed=build_mercy_guide_embed())
        await start_suggestion_step(interaction, self.state)


# ============================================================
#  STEP 3 — SUGGESTION CHANNEL
# ============================================================

class SuggestionChannelView(SetupBaseView):
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select the Suggestion channel (optional)..."
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.Select):
        selected = select.values[0]
        channel = interaction.guild.get_channel(selected.id)

        set_guild_channel(self.guild.id, "suggestion_channel_id", channel.id)
        self.state["suggestion_channel"] = channel

        await interaction.response.edit_message(
            content=f"Suggestion channel set to {channel.mention}.",
            view=None
        )

        embed = discord.Embed(
            title="💡 Anonymous Suggestions",
            description=(
                "Want to submit feedback privately?\n"
                "Click the button below and I'll open a DM where you can send your anonymous suggestion."
            ),
            color=discord.Color.green()
        )

        await channel.send(embed=embed, view=MessageMeButton())
        await start_feedback_step(interaction, self.state)

    @discord.ui.button(label="Skip this step", style=discord.ButtonStyle.secondary)
    async def skip_step(self, interaction: discord.Interaction, button):
        set_guild_channel(self.guild.id, "suggestion_channel_id", None)
        self.state["suggestion_channel"] = None

        await interaction.response.edit_message(
            content="Suggestion channel skipped.",
            view=None
        )

        await start_feedback_step(interaction, self.state)


# ============================================================
#  STEP 4 — FEEDBACK CHANNEL
# ============================================================

class FeedbackChannelView(SetupBaseView):
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select the Feedback channel (optional)..."
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.Select):
        selected = select.values[0]
        channel = interaction.guild.get_channel(selected.id)

        set_guild_channel(self.guild.id, "feedback_channel_id", channel.id)
        self.state["feedback_channel"] = channel

        await interaction.response.edit_message(
            content=f"Feedback channel set to {channel.mention}.",
            view=None
        )

        await start_warning_step(interaction, self.state)

    @discord.ui.button(label="Skip this step", style=discord.ButtonStyle.secondary)
    async def skip_step(self, interaction: discord.Interaction, button):
        set_guild_channel(self.guild.id, "feedback_channel_id", None)
        self.state["feedback_channel"] = None

        await interaction.response.edit_message(
            content="Feedback channel skipped.",
            view=None
        )

        await start_warning_step(interaction, self.state)


# ============================================================
#  STEP 5 — WARNING CHANNEL
# ============================================================

class WarningChannelView(SetupBaseView):
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select the Hydra Warning channel..."
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.Select):
        selected = select.values[0]
        channel = interaction.guild.get_channel(selected.id)

        set_guild_channel(self.guild.id, "warning_channel_id", channel.id)
        self.state["warning_channel"] = channel

        await interaction.response.edit_message(
            content=f"Warning channel set to {channel.mention}.",
            view=None
        )

        await finish_setup_summary(interaction, self.state)
# ============================================================
#  SETUP WIZARD HELPERS
# ============================================================

async def start_commands_step(interaction, state):
    view = CommandsChannelView(interaction.user.id, interaction.guild, state)
    await interaction.response.send_message(
        "Step 1/5 — Select the **Commands Guide** channel (required):",
        view=view
    )

async def start_mercy_step(interaction, state):
    view = MercyChannelView(interaction.user.id, interaction.guild, state)
    await interaction.followup.send(
        "Step 2/5 — Select the **Mercy Guide** channel (required):",
        view=view
    )

async def start_suggestion_step(interaction, state):
    view = SuggestionChannelView(interaction.user.id, interaction.guild, state)
    await interaction.followup.send(
        "Step 3/5 — Select the **Suggestion** channel (optional):",
        view=view
    )

async def start_feedback_step(interaction, state):
    view = FeedbackChannelView(interaction.user.id, interaction.guild, state)
    await interaction.followup.send(
        "Step 4/5 — Select the **Feedback** channel (optional):",
        view=view
    )

async def start_warning_step(interaction, state):
    view = WarningChannelView(interaction.user.id, interaction.guild, state)
    await interaction.followup.send(
        "Step 5/5 — Select the **Hydra Warning** channel (required):",
        view=view
    )

async def finish_setup_summary(interaction, state):
    guild = interaction.guild
    channels = get_guild_channels(guild.id)

    def fmt(ch):
        return ch.mention if isinstance(ch, discord.TextChannel) else "Skipped"

    commands_ch = guild.get_channel(channels["commands_channel_id"]) if channels["commands_channel_id"] else None
    mercy_ch = guild.get_channel(channels["mercy_channel_id"]) if channels["mercy_channel_id"] else None
    suggestion_ch = guild.get_channel(channels["suggestion_channel_id"]) if channels["suggestion_channel_id"] else None
    feedback_ch = guild.get_channel(channels["feedback_channel_id"]) if channels["feedback_channel_id"] else None
    warning_ch = guild.get_channel(channels["warning_channel_id"]) if channels["warning_channel_id"] else None

    embed = discord.Embed(
        title="✅ HydraBot Setup Complete",
        color=discord.Color.green()
    )
    embed.add_field(name="Commands Guide Channel", value=fmt(commands_ch), inline=False)
    embed.add_field(name="Mercy Guide Channel", value=fmt(mercy_ch), inline=False)
    embed.add_field(name="Suggestion Channel", value=fmt(suggestion_ch), inline=False)
    embed.add_field(name="Feedback Channel", value=fmt(feedback_ch), inline=False)
    embed.add_field(name="Warning Channel", value=fmt(warning_ch), inline=False)

    await interaction.followup.send(embed=embed)

    # ============================================================
#  SECTION 6: on_message (ANONYMOUS SUGGESTIONS)
# ============================================================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if isinstance(message.channel, discord.DMChannel):
        suggestion = message.content
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
    msg = (
        "**Hydra Chest Requirements**\n"
        "Normal – Over 6.66M\n"
        "Hard – Over 20.4M\n"
        "Brutal – Over 29.4M\n"
        "Nightmare – Over 36.6M"
    )
    await ctx.send(msg)
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
        await ctx.send("Usage: `$remindme 10m take the bins out`")
        return

    unit = time[-1]
    amount = time[:-1]

    if not amount.isdigit():
        await ctx.send("Time must be a number followed by m/h/d.")
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
    reminders.setdefault(user_id, [])

    reminder_id = len(reminders[user_id]) + 1
    reminders[user_id].append({"id": reminder_id, "text": reminder, "time": time})

    await ctx.send(f"⏰ Reminder **#{reminder_id}** set for **{time}**.")

    await asyncio.sleep(seconds)
    await ctx.send(f"{ctx.author.mention} 🔔 Reminder #{reminder_id}: **{reminder}**")

    reminders[user_id] = [r for r in reminders[user_id] if r["id"] != reminder_id]

@bot.command(name="reminders")
async def list_reminders(ctx):
    await ctx.message.delete()
    user_id = ctx.author.id

    if user_id not in reminders or not reminders[user_id]:
        await ctx.send("You have no active reminders.")
        return

    msg = "**Your Active Reminders:**\n"
    for r in reminders[user_id]:
        msg += f"• #{r['id']} – {r['text']} (in {r['time']})\n"

    await ctx.send(msg)

@bot.command()
async def cancelreminder(ctx, reminder_id: int):
    await ctx.message.delete()
    user_id = ctx.author.id

    if user_id not in reminders or not reminders[user_id]:
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

    yes = [
        "Yes — send it.",
        "Absolutely. This shard is calling your name.",
        "Yep. You will regret skipping more than pulling."
    ]
    no = [
        "No — save your resources.",
        "Skip. This shard is not worth it.",
        "Not this one. Your future self will thank you."
    ]

    decision = random.choice(["yes", "no"])
    answer = random.choice(yes if decision == "yes" else no)
    colour = discord.Color.green() if decision == "yes" else discord.Color.red()

    embed = discord.Embed(title="🎲 Should you pull?", description=answer, color=colour)
    embed.add_field(name="Requested by", value=ctx.author.mention, inline=False)
    if event:
        embed.add_field(name="Event", value=event, inline=False)
    embed.set_footer(text="Decision generated by HydraBot RNG")

    await ctx.send(embed=embed)

# -----------------------------
# GACHA SIMULATOR (PREFIX)
# -----------------------------

def roll_from_rates(rates):
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
        msg = await ctx.send("Specify shard: ancient, void, primal, sacred.")
        return await msg.delete(delay=10)

    shard_type = shard_type.lower()
    if shard_type not in SHARD_RATES:
        msg = await ctx.send("Invalid shard type.")
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
    embed.add_field(name="Results", value="\n".join(results), inline=False)
    embed.add_field(
        name="Summary",
        value="\n".join([f"{rarity}: **{count}**" for rarity, count in summary.items()]),
        inline=False
    )
    embed.add_field(name="Requested by", value=ctx.author.mention, inline=False)
    embed.set_footer(text="HydraBot Simulator")

    await ctx.send(embed=embed)

# ============================================================
#  MERCY PREFIX COMMANDS
# ============================================================

@bot.command(name="mercy")
async def mercy_cmd(ctx, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await ctx.send("Invalid shard type.")

    epic, legendary, mythical = get_mercy_row(ctx.author.id, shard_type)

    embed = discord.Embed(
        title=f"{shard_type.capitalize()} Mercy Status",
        color=discord.Color.gold()
    )

    if shard_type in ("ancient", "void"):
        epic_chance = calc_epic_chance(shard_type, epic)
        embed.add_field(name="Epic", value=f"Pity: {epic}\nChance: {epic_chance:.2f}%", inline=False)

    legendary_chance = calc_legendary_chance(shard_type, legendary)
    embed.add_field(name="Legendary", value=f"Pity: {legendary}\nChance: {legendary_chance:.2f}%", inline=False)

    mythical_chance = None
    if shard_type == "primal":
        mythical_chance = calc_mythical_chance(shard_type, mythical)
        embed.add_field(name="Mythical", value=f"Pity: {mythical}\nChance: {mythical_chance:.2f}%", inline=False)

    color, ready, _ = compute_readiness_color_and_flag(shard_type, legendary_chance, mythical_chance)
    embed.color = color

    if ready:
        embed.add_field(name="🔥 Ready?", value="Looks like you are ready to pull :P", inline=False)

    await ctx.send(embed=embed)

@bot.command(name="mercyall")
async def mercy_all_cmd(ctx):
    user = ctx.author.id
    embed = discord.Embed(
        title=f"{ctx.author.display_name}'s Full Mercy Overview",
        color=discord.Color.blue()
    )

    for shard in BASE_RATES:
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

    for shard in BASE_RATES:
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

        embed.add_field(name=shard.capitalize(), value="\n".join(lines), inline=False)

    await ctx.send(embed=embed)

@bot.command(name="mercycompare")
async def mercy_compare_cmd(ctx, member: discord.Member):
    user1 = ctx.author
    user2 = member

    embed = discord.Embed(
        title=f"Mercy Comparison: {user1.display_name} vs {user2.display_name}",
        color=discord.Color.purple()
    )

    for shard in BASE_RATES:
        epic1, legendary1, mythical1 = get_mercy_row(user1.id, shard)
        epic2, legendary2, mythical2 = get_mercy_row(user2.id, shard)

        lines = []

        if shard in ("ancient", "void"):
            e1 = calc_epic_chance(shard, epic1)
            l1 = calc_legendary_chance(shard, legendary1)
            lines.append(f"**{user1.display_name}:** E:{epic1} ({e1:.2f}%)  L:{legendary1} ({l1:.2f}%)")
        elif shard == "primal":
            l1 = calc_legendary_chance(shard, legendary1)
            m1 = calc_mythical_chance(shard, mythical1)
            lines.append(f"**{user1.display_name}:** L:{legendary1} ({l1:.2f}%)  M:{mythical1} ({m1:.2f}%)")
        else:
            l1 = calc_legendary_chance(shard, legendary1)
            lines.append(f"**{user1.display_name}:** L:{legendary1} ({l1:.2f}%)")

        if shard in ("ancient", "void"):
            e2 = calc_epic_chance(shard, epic2)
            l2 = calc_legendary_chance(shard, legendary2)
            lines.append(f"**{user2.display_name}:** E:{epic2} ({e2:.2f}%)  L:{legendary2} ({l2:.2f}%)")
        elif shard == "primal":
            l2 = calc_legendary_chance(shard, legendary2)
            m2 = calc_mythical_chance(shard, mythical2)
            lines.append(f"**{user2.display_name}:** L:{legendary2} ({l2:.2f}%)  M:{mythical2} ({m2:.2f}%)")
        else:
            l2 = calc_legendary_chance(shard, legendary2)
            lines.append(f"**{user2.display_name}:** L:{legendary2} ({l2:.2f}%)")

        embed.add_field(name=shard.capitalize(), value="\n".join(lines), inline=False)

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
        return await ctx.send("Invalid shard type.")
    if amount <= 0:
        return await ctx.send("Amount must be positive.")
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

# ============================================================
#  SECTION 8: PURGE, ANNOUNCE, SUGGESTBUTTON, GUIDES
# ============================================================

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
            "https://media.giphy.com/media/Ju7l5y9osyymQ/giphy.gif"
        ]
        await ctx.send(random.choice(responses))

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
            "https://media.giphy.com/media/Ju7l5y9osyymQ/giphy.gif"
        ]
        await ctx.send(random.choice(responses))

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

def build_commands_guide_embed():
    embed = discord.Embed(
        title="HYDRABOT — FULL COMMAND GUIDE",
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="GENERAL COMMANDS",
        value="`$test` — Check if HydraBot is online.\n`$chests` — Hydra Clash chest requirements.",
        inline=False
    )
    embed.add_field(
        name="ADMIN / UTILITY COMMANDS",
        value="`$announce <msg>` — Post announcement.\n`$purge <amount>` — Delete messages.",
        inline=False
    )
    embed.add_field(
        name="ANONYMOUS SUGGESTIONS",
        value="Click **Message Me** → DM bot → Confirm → Submit anonymously.",
        inline=False
    )
    embed.add_field(
        name="REMINDERS",
        value="`$remindme 10m task` — Set reminder.\n`$reminders` — List.\n`$cancelreminder <id>` — Cancel.",
        inline=False
    )
    embed.add_field(
        name="SHOULD I PULL?",
        value="`$pull <event>` — Random pull advice.",
        inline=False
    )
    embed.add_field(
        name="GACHA SIMULATOR",
        value="`$sim <shard>` — Simulate 10 pulls.",
        inline=False
    )
    embed.add_field(
        name="MERCY TRACKER",
        value=(
            "`$mercy <shard>`\n`$mercyall`\n`$mercytable`\n"
            "`$mercycompare @user`\n"
            "`$addepic <shard>`\n`$addlegendary <shard>`\n"
            "`$addmythical`\n`$addpull <shard> <amount>`\n`$clearmercy <shard>`"
        ),
        inline=False
    )
    return embed

@bot.command(name="commands")
async def commands_prefix(ctx):
    channels = get_guild_channels(ctx.guild.id)
    commands_channel_id = channels["commands_channel_id"]
    channel = ctx.guild.get_channel(commands_channel_id) if commands_channel_id else ctx.channel
    await channel.send(embed=build_commands_guide_embed())

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
        value="Adds raw pulls to pity counters.",
        inline=False
    )
    embed.add_field(
        name="$addepic <shard>",
        value="Resets Epic pity and increases Legendary pity.",
        inline=False
    )
    embed.add_field(
        name="$addlegendary <shard>",
        value="Resets Epic + Legendary pity.",
        inline=False
    )
    embed.add_field(
        name="$addmythical primal",
        value="Resets all primal pity.",
        inline=False
    )
    embed.add_field(
        name="$mercy <shard>",
        value="Shows pity, chances, and readiness.",
        inline=False
    )
    embed.add_field(
        name="$mercyall / $mercytable",
        value="Full overview of all shards.",
        inline=False
    )
    embed.add_field(
        name="$mercycompare @user",
        value="Compare pity with another player.",
        inline=False
    )
    return embed

@bot.command(name="mercyguide")
@commands.has_permissions(administrator=True)
async def mercy_guide_prefix(ctx):
    await ctx.send(embed=build_mercy_guide_embed())

# ============================================================
#  SECTION 9: SLASH COMMANDS
# ============================================================

async def shard_autocomplete(interaction, current):
    current = current.lower()
    return [
        app_commands.Choice(name=s.capitalize(), value=s)
        for s in SHARD_CHOICES if current in s
    ]

mercy_group = app_commands.Group(
    name="mercy",
    description="Mercy tracking commands."
)

@mercy_group.command(name="check")
@app_commands.describe(shard_type="Shard type")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_check(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message("Invalid shard type.", ephemeral=True)
    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)
    embed = discord.Embed(
        title=f"{shard_type.capitalize()} Mercy Status",
        color=discord.Color.gold()
    )
    if shard_type in ("ancient", "void"):
        epic_chance = calc_epic_chance(shard_type, epic)
        embed.add_field(name="Epic", value=f"Pity: {epic}\nChance: {epic_chance:.2f}%", inline=False)
    legendary_chance = calc_legendary_chance(shard_type, legendary)
    embed.add_field(name="Legendary", value=f"Pity: {legendary}\nChance: {legendary_chance:.2f}%", inline=False)
    mythical_chance = None
    if shard_type == "primal":
        mythical_chance = calc_mythical_chance(shard_type, mythical)
        embed.add_field(name="Mythical", value=f"Pity: {mythical}\nChance: {mythical_chance:.2f}%", inline=False)
    color, ready, _ = compute_readiness_color_and_flag(shard_type, legendary_chance, mythical_chance)
    embed.color = color
    if ready:
        embed.add_field(name="🔥 Ready?", value="Looks like you are ready to pull :P", inline=False)
    await interaction.response.send_message(embed=embed)

@mercy_group.command(name="table")
async def mercy_table_slash(interaction):
    user = interaction.user.id
    embed = discord.Embed(
        title=f"{interaction.user.display_name}'s Mercy Table",
        color=discord.Color.gold()
    )
    for shard in BASE_RATES:
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
        embed.add_field(name=shard.capitalize(), value="\n".join(lines), inline=False)
    await interaction.response.send_message(embed=embed)

@mercy_group.command(name="all")
async def mercy_all_slash(interaction):
    user = interaction.user.id
    embed = discord.Embed(
        title=f"{interaction.user.display_name}'s Full Mercy Overview",
        color=discord.Color.blue()
    )
    for shard in BASE_RATES:
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

@mercy_group.command(name="compare")
@app_commands.describe(member="User to compare with")
async def mercy_compare_slash(interaction, member: discord.Member):
    user1 = interaction.user
    user2 = member
    embed = discord.Embed(
        title=f"Mercy Comparison: {user1.display_name} vs {user2.display_name}",
        color=discord.Color.purple()
    )
    for shard in BASE_RATES:
        epic1, legendary1, mythical1 = get_mercy_row(user1.id, shard)
        epic2, legendary2, mythical2 = get_mercy_row(user2.id, shard)
        lines = []
        if shard in ("ancient", "void"):
            e1 = calc_epic_chance(shard, epic1)
            l1 = calc_legendary_chance(shard, legendary1)
            lines.append(f"**{user1.display_name}:** E:{epic1} ({e1:.2f}%)  L:{legendary1} ({l1:.2f}%)")
        elif shard == "primal":
            l1 = calc_legendary_chance(shard, legendary1)
            m1 = calc_mythical_chance(shard, mythical1)
            lines.append(f"**{user1.display_name}:** L:{legendary1} ({l1:.2f}%)  M:{mythical1} ({m1:.2f}%)")
        else:
            l1 = calc_legendary_chance(shard, legendary1)
            lines.append(f"**{user1.display_name}:** L:{legendary1} ({l1:.2f}%)")
        if shard in ("ancient", "void"):
            e2 = calc_epic_chance(shard, epic2)
            l2 = calc_legendary_chance(shard, legendary2)
            lines.append(f"**{user2.display_name}:** E:{epic2} ({e2:.2f}%)  L:{legendary2} ({l2:.2f}%)")
        elif shard == "primal":
            l2 = calc_legendary_chance(shard, legendary2)
            m2 = calc_mythical_chance(shard, mythical2)
            lines.append(f"**{user2.display_name}:** L:{legendary2} ({l2:.2f}%)  M:{mythical2} ({m2:.2f}%)")
        else:
            l2 = calc_legendary_chance(shard, legendary2)
            lines.append(f"**{user2.display_name}:** L:{legendary2} ({l2:.2f}%)")
        embed.add_field(name=shard.capitalize(), value="\n".join(lines), inline=False)
    await interaction.response.send_message(embed=embed)

@mercy_group.command(name="add-pull")
@app_commands.describe(shard_type="Shard type", amount="Number of pulls")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_add_pull_slash(interaction, shard_type: str, amount: int):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message("Invalid shard type.", ephemeral=True)
    if amount <= 0:
        return await interaction.response.send_message("Amount must be positive.", ephemeral=True)
    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)
    if shard_type in ("ancient", "void"):
        epic += amount
    legendary += amount
    if shard_type == "primal":
        mythical += amount
    set_mercy_row(interaction.user.id, shard_type, epic, legendary, mythical)
    msg = f"Added **{amount}** pulls to **{shard_type}**.\n"
    if shard_type in ("ancient", "void"):
        msg += f"Epic: {epic}, "
    msg += f"Legendary: {legendary}"
    if shard_type == "primal":
        msg += f", Mythical: {mythical}"
    await interaction.response.send_message(msg)

@mercy_group.command(name="add-epic")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_add_epic_slash(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message("Invalid shard type.", ephemeral=True)
    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)
    epic = 0
    legendary += 1
    if shard_type == "primal":
        mythical += 1
    set_mercy_row(interaction.user.id, shard_type, epic, legendary, mythical)
    await interaction.response.send_message(f"Epic recorded for {shard_type}.")

@mercy_group.command(name="add-legendary")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_add_legendary_slash(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message("Invalid shard type.", ephemeral=True)
    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)
    epic = 0
    legendary = 0
    if shard_type == "primal":
        mythical += 1
    set_mercy_row(interaction.user.id, shard_type, epic, legendary, mythical)
    await interaction.response.send_message(f"Legendary recorded for {shard_type}.")

@mercy_group.command(name="add-mythical")
async def mercy_add_mythical_slash(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type != "primal":
        return await interaction.response.send_message("Only primal shards can pull mythical.", ephemeral=True)
    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)
    epic = 0
    legendary = 0
    mythical = 0
    set_mercy_row(interaction.user.id, shard_type, epic, legendary, mythical)
    await interaction.response.send_message("Mythical recorded for primal.")

@mercy_group.command(name="clear")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_clear_slash(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message("Invalid shard type.", ephemeral=True)
    set_mercy_row(interaction.user.id, shard_type, 0, 0, 0)
    await interaction.response.send_message(f"Your {shard_type} mercy has been reset.")

# ============================================================
#  REMINDER SLASH COMMANDS
# ============================================================

reminder_group = app_commands.Group(
    name="reminder",
    description="Reminder commands."
)

@reminder_group.command(name="set")
@app_commands.describe(time="10m, 2h, 1d", reminder="Reminder text")
async def reminder_set(interaction, time: str, reminder: str):
    unit = time[-1]
    amount = time[:-1]

    if not amount.isdigit():
        return await interaction.response.send_message(
            "Time must be a number followed by m/h/d.",
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
    reminders.setdefault(user_id, [])

    reminder_id = len(reminders[user_id]) + 1
    reminders[user_id].append({"id": reminder_id, "text": reminder, "time": time})

    await interaction.response.send_message(
        f"⏰ Reminder **#{reminder_id}** set for **{time}**.",
        ephemeral=True
    )

    async def reminder_task():
        await asyncio.sleep(seconds)
        try:
            await interaction.channel.send(
                f"{interaction.user.mention} 🔔 Reminder #{reminder_id}: **{reminder}**"
            )
        finally:
            reminders[user_id] = [
                r for r in reminders[user_id] if r["id"] != reminder_id
            ]

    bot.loop.create_task(reminder_task())

@reminder_group.command(name="list")
async def reminder_list_slash(interaction):
    user_id = interaction.user.id

    if user_id not in reminders or not reminders[user_id]:
        return await interaction.response.send_message(
            "You have no active reminders.",
            ephemeral=True
        )

    msg = "**Your Active Reminders:**\n"
    for r in reminders[user_id]:
        msg += f"• #{r['id']} – {r['text']} (in {r['time']})\n"

    await interaction.response.send_message(msg, ephemeral=True)

@reminder_group.command(name="cancel")
@app_commands.describe(reminder_id="Reminder ID to cancel")
async def reminder_cancel_slash(interaction, reminder_id: int):
    user_id = interaction.user.id

    if user_id not in reminders or not reminders[user_id]:
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

# ============================================================
#  GACHA SLASH COMMANDS
# ============================================================

gacha_group = app_commands.Group(
    name="gacha",
    description="Gacha simulator and pull advice."
)

@gacha_group.command(name="simulate")
@app_commands.describe(shard_type="Shard type")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def gacha_simulate_slash(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in SHARD_RATES:
        return await interaction.response.send_message(
            "Invalid shard type.",
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
    embed.add_field(name="Results", value="\n".join(results), inline=False)
    embed.add_field(
        name="Summary",
        value="\n".join([f"{rarity}: **{count}**" for rarity, count in summary.items()]),
        inline=False
    )
    embed.add_field(name="Requested by", value=interaction.user.mention, inline=False)
    embed.set_footer(text="HydraBot Simulator")

    await interaction.response.send_message(embed=embed)

@gacha_group.command(name="pull-advice")
@app_commands.describe(event="Optional event or banner")
async def gacha_pull_advice_slash(interaction, event: str | None = None):
    yes = [
        "Yes — send it.",
        "Absolutely. This shard is calling your name.",
        "Yep. You will regret skipping more than pulling."
    ]
    no = [
        "No — save your resources.",
        "Skip. This shard is not worth it.",
        "Not this one. Your future self will thank you."
    ]

    decision = random.choice(["yes", "no"])
    answer = random.choice(yes if decision == "yes" else no)
    colour = discord.Color.green() if decision == "yes" else discord.Color.red()

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

# ============================================================
#  ADMIN SLASH COMMANDS
# ============================================================

admin_group = app_commands.Group(
    name="admin",
    description="Admin-only tools.",
    default_permissions=discord.Permissions(administrator=True)
)

@admin_group.command(name="announce")
@app_commands.describe(message="Announcement text")
async def admin_announce_slash(interaction, message: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission.",
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

@admin_group.command(name="purge")
@app_commands.describe(amount="Number of messages to delete")
async def admin_purge_slash(interaction, amount: int):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission.",
            ephemeral=True
        )

    if amount <= 0:
        return await interaction.response.send_message(
            "Enter a number greater than 0.",
            ephemeral=True
        )

    deleted = await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(
        f"Deleted {len(deleted)} messages.",
        ephemeral=True
    )

@admin_group.command(name="suggest-button")
async def admin_suggest_button_slash(interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission.",
            ephemeral=True
        )

    if interaction.channel.id not in ALLOWED_SUGGEST_BUTTON_CHANNELS:
        return await interaction.response.send_message(
            "This channel is not approved.",
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

@admin_group.command(name="setup")
async def admin_setup_slash(interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission.",
            ephemeral=True
        )
    state = {}
    await start_commands_step(interaction, state)

@admin_group.command(name="commands-guide")
async def admin_commands_guide_slash(interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("No permission.", ephemeral=True)

    channels = get_guild_channels(interaction.guild.id)
    commands_channel_id = channels["commands_channel_id"]
    channel = interaction.guild.get_channel(commands_channel_id) if commands_channel_id else interaction.channel

    await channel.send(embed=build_commands_guide_embed())
    await interaction.response.send_message("Commands guide posted.", ephemeral=True)

@admin_group.command(name="mercy-guide")
async def admin_mercy_guide_slash(interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("No permission.", ephemeral=True)

    await interaction.channel.send(embed=build_mercy_guide_embed())
    await interaction.response.send_message("Mercy guide posted.", ephemeral=True)

@admin_group.command(name="debug-commands")
async def admin_debug_commands_slash(interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("No permission.", ephemeral=True)
# ============================================================
#  SECTION 9: SLASH COMMANDS
# ============================================================

async def shard_autocomplete(interaction, current):
    current = current.lower()
    return [
        app_commands.Choice(name=s.capitalize(), value=s)
        for s in SHARD_CHOICES if current in s
    ]

# ============================================================
#  MERCY SLASH COMMANDS
# ============================================================

mercy_group = app_commands.Group(
    name="mercy",
    description="View and manage your shard mercy counters."
)

@mercy_group.command(
    name="check",
    description="Show your mercy status and pull chances for a specific shard."
)
@app_commands.describe(shard_type="Shard type to check.")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_check(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message("Invalid shard type.", ephemeral=True)

    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)

    embed = discord.Embed(
        title=f"{shard_type.capitalize()} Mercy Status",
        color=discord.Color.gold()
    )

    if shard_type in ("ancient", "void"):
        epic_chance = calc_epic_chance(shard_type, epic)
        embed.add_field(name="Epic", value=f"Pity: {epic}\nChance: {epic_chance:.2f}%", inline=False)

    legendary_chance = calc_legendary_chance(shard_type, legendary)
    embed.add_field(name="Legendary", value=f"Pity: {legendary}\nChance: {legendary_chance:.2f}%", inline=False)

    mythical_chance = None
    if shard_type == "primal":
        mythical_chance = calc_mythical_chance(shard_type, mythical)
        embed.add_field(name="Mythical", value=f"Pity: {mythical}\nChance: {mythical_chance:.2f}%", inline=False)

    color, ready, _ = compute_readiness_color_and_flag(shard_type, legendary_chance, mythical_chance)
    embed.color = color

    if ready:
        embed.add_field(name="🔥 Ready?", value="Looks like you are ready to pull :P", inline=False)

    await interaction.response.send_message(embed=embed)

@mercy_group.command(
    name="table",
    description="Display a detailed mercy table for all shard types."
)
async def mercy_table_slash(interaction):
    user = interaction.user.id
    embed = discord.Embed(
        title=f"{interaction.user.display_name}'s Mercy Table",
        color=discord.Color.gold()
    )

    for shard in BASE_RATES:
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

        embed.add_field(name=shard.capitalize(), value="\n".join(lines), inline=False)

    await interaction.response.send_message(embed=embed)

@mercy_group.command(
    name="all",
    description="Show a full overview of all your mercy counters."
)
async def mercy_all_slash(interaction):
    user = interaction.user.id
    embed = discord.Embed(
        title=f"{interaction.user.display_name}'s Full Mercy Overview",
        color=discord.Color.blue()
    )

    for shard in BASE_RATES:
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

@mercy_group.command(
    name="compare",
    description="Compare your mercy counters with another user."
)
@app_commands.describe(member="User to compare with.")
async def mercy_compare_slash(interaction, member: discord.Member):
    user1 = interaction.user
    user2 = member

    embed = discord.Embed(
        title=f"Mercy Comparison: {user1.display_name} vs {user2.display_name}",
        color=discord.Color.purple()
    )

    for shard in BASE_RATES:
        epic1, legendary1, mythical1 = get_mercy_row(user1.id, shard)
        epic2, legendary2, mythical2 = get_mercy_row(user2.id, shard)

        lines = []

        if shard in ("ancient", "void"):
            e1 = calc_epic_chance(shard, epic1)
            l1 = calc_legendary_chance(shard, legendary1)
            lines.append(f"**{user1.display_name}:** E:{epic1} ({e1:.2f}%)  L:{legendary1} ({l1:.2f}%)")
        elif shard == "primal":
            l1 = calc_legendary_chance(shard, legendary1)
            m1 = calc_mythical_chance(shard, mythical1)
            lines.append(f"**{user1.display_name}:** L:{legendary1} ({l1:.2f}%)  M:{mythical1} ({m1:.2f}%)")
        else:
            l1 = calc_legendary_chance(shard, legendary1)
            lines.append(f"**{user1.display_name}:** L:{legendary1} ({l1:.2f}%)")

        if shard in ("ancient", "void"):
            e2 = calc_epic_chance(shard, epic2)
            l2 = calc_legendary_chance(shard, legendary2)
            lines.append(f"**{user2.display_name}:** E:{epic2} ({e2:.2f}%)  L:{legendary2} ({l2:.2f}%)")
        elif shard == "primal":
            l2 = calc_legendary_chance(shard, legendary2)
            m2 = calc_mythical_chance(shard, mythical2)
            lines.append(f"**{user2.display_name}:** L:{legendary2} ({l2:.2f}%)  M:{mythical2} ({m2:.2f}%)")
        else:
            l2 = calc_legendary_chance(shard, legendary2)
            lines.append(f"**{user2.display_name}:** L:{legendary2} ({l2:.2f}%)")

        embed.add_field(name=shard.capitalize(), value="\n".join(lines), inline=False)

    await interaction.response.send_message(embed=embed)

@mercy_group.command(
    name="add-pull",
    description="Add raw pulls to your mercy counters."
)
@app_commands.describe(shard_type="Shard type to update.", amount="Number of pulls to add.")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_add_pull_slash(interaction, shard_type: str, amount: int):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message("Invalid shard type.", ephemeral=True)
    if amount <= 0:
        return await interaction.response.send_message("Amount must be positive.", ephemeral=True)

    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)

    if shard_type in ("ancient", "void"):
        epic += amount
    legendary += amount
    if shard_type == "primal":
        mythical += amount

    set_mercy_row(interaction.user.id, shard_type, epic, legendary, mythical)

    msg = f"Added **{amount}** pulls to **{shard_type}**.\n"
    if shard_type in ("ancient", "void"):
        msg += f"Epic: {epic}, "
    msg += f"Legendary: {legendary}"
    if shard_type == "primal":
        msg += f", Mythical: {mythical}"

    await interaction.response.send_message(msg)

@mercy_group.command(
    name="add-epic",
    description="Record an Epic pull and update mercy accordingly."
)
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_add_epic_slash(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message("Invalid shard type.", ephemeral=True)

    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)

    epic = 0
    legendary += 1
    if shard_type == "primal":
        mythical += 1

    set_mercy_row(interaction.user.id, shard_type, epic, legendary, mythical)

    await interaction.response.send_message(f"Epic recorded for {shard_type}.")

@mercy_group.command(
    name="add-legendary",
    description="Record a Legendary pull and reset mercy counters."
)
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_add_legendary_slash(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message("Invalid shard type.", ephemeral=True)

    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)

    epic = 0
    legendary = 0
    if shard_type == "primal":
        mythical += 1

    set_mercy_row(interaction.user.id, shard_type, epic, legendary, mythical)

    await interaction.response.send_message(f"Legendary recorded for {shard_type}.")

@mercy_group.command(
    name="add-mythical",
    description="Record a Mythical pull for primal shards."
)
@app_commands.describe(shard_type="Must be 'primal'.")
async def mercy_add_mythical_slash(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type != "primal":
        return await interaction.response.send_message("Only primal shards can pull mythical.", ephemeral=True)

    epic, legendary, mythical = get_mercy_row(interaction.user.id, shard_type)

    epic = 0
    legendary = 0
    mythical = 0

    set_mercy_row(interaction.user.id, shard_type, epic, legendary, mythical)

    await interaction.response.send_message("Mythical recorded for primal.")

@mercy_group.command(
    name="clear",
    description="Reset your mercy counters for a specific shard."
)
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def mercy_clear_slash(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await interaction.response.send_message("Invalid shard type.", ephemeral=True)

    set_mercy_row(interaction.user.id, shard_type, 0, 0, 0)

    await interaction.response.send_message(f"Your {shard_type} mercy has been reset.")

# ============================================================
#  REMINDER SLASH COMMANDS
# ============================================================

reminder_group = app_commands.Group(
    name="reminder",
    description="Set and manage personal reminders."
)

@reminder_group.command(
    name="set",
    description="Create a reminder for a future time."
)
@app_commands.describe(time="Format: 10m, 2h, 1d", reminder="Reminder text.")
async def reminder_set(interaction, time: str, reminder: str):
    unit = time[-1]
    amount = time[:-1]

    if not amount.isdigit():
        return await interaction.response.send_message(
            "Time must be a number followed by m/h/d.",
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
    reminders.setdefault(user_id, [])

    reminder_id = len(reminders[user_id]) + 1
    reminders[user_id].append({"id": reminder_id, "text": reminder, "time": time})

    await interaction.response.send_message(
        f"⏰ Reminder **#{reminder_id}** set for **{time}**.",
        ephemeral=True
    )

    async def reminder_task():
        await asyncio.sleep(seconds)
        try:
            await interaction.channel.send(
                f"{interaction.user.mention} 🔔 Reminder #{reminder_id}: **{reminder}**"
            )
        finally:
            reminders[user_id] = [
                r for r in reminders[user_id] if r["id"] != reminder_id
            ]

    bot.loop.create_task(reminder_task())

@reminder_group.command(
    name="list",
    description="View all active reminders."
)
async def reminder_list_slash(interaction):
    user_id = interaction.user.id

    if user_id not in reminders or not reminders[user_id]:
        return await interaction.response.send_message(
            "You have no active reminders.",
            ephemeral=True
        )

    msg = "**Your Active Reminders:**\n"
    for r in reminders[user_id]:
        msg += f"• #{r['id']} – {r['text']} (in {r['time']})\n"

    await interaction.response.send_message(msg, ephemeral=True)

@reminder_group.command(
    name="cancel",
    description="Cancel one of your active reminders."
)
@app_commands.describe(reminder_id="Reminder ID to cancel.")
async def reminder_cancel_slash(interaction, reminder_id: int):
    user_id = interaction.user.id

    if user_id not in reminders or not reminders[user_id]:
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

# ============================================================
#  GACHA SLASH COMMANDS
# ============================================================

gacha_group = app_commands.Group(
    name="gacha",
    description="Simulate shard pulls and get pull advice."
)

@gacha_group.command(
    name="simulate",
    description="Simulate 10 shard pulls for a chosen shard type."
)
@app_commands.describe(shard_type="Shard type to simulate.")
@app_commands.autocomplete(shard_type=shard_autocomplete)
async def gacha_simulate_slash(interaction, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in SHARD_RATES:
        return await interaction.response.send_message(
            "Invalid shard type.",
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
    embed.add_field(name="Results", value="\n".join(results), inline=False)
    embed.add_field(
        name="Summary",
        value="\n".join([f"{rarity}: **{count}**" for rarity, count in summary.items()]),
        inline=False
    )
    embed.add_field(name="Requested by", value=interaction.user.mention, inline=False)
    embed.set_footer(text="HydraBot Simulator")

    await interaction.response.send_message(embed=embed)

@gacha_group.command(
    name="pull-advice",
    description="Get advice on whether you should pull right now."
)
@app_commands.describe(event="Optional event or banner name.")
async def gacha_pull_advice_slash(interaction, event: str | None = None):
    yes = [
        "Yes — send it.",
        "Absolutely. This shard is calling your name.",
        "Yep. You will regret skipping more than pulling."
    ]
    no = [
        "No — save your resources.",
        "Skip. This shard is not worth it.",
        "Not this one. Your future self will thank you."
    ]

    decision = random.choice(["yes", "no"])
    answer = random.choice(yes if decision == "yes" else no)
    colour = discord.Color.green() if decision == "yes" else discord.Color.red()

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

    # ============================================================
#  ADMIN SLASH COMMANDS
# ============================================================

admin_group = app_commands.Group(
    name="admin",
    description="Administrative tools for server management.",
    default_permissions=discord.Permissions(administrator=True)
)

@admin_group.command(
    name="announce",
    description="Post an announcement to the configured announcement channel."
)
@app_commands.describe(message="The announcement text.")
async def admin_announce_slash(interaction, message: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission.",
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


@admin_group.command(
    name="purge",
    description="Delete a number of messages from the current channel."
)
@app_commands.describe(amount="Number of messages to delete.")
async def admin_purge_slash(interaction, amount: int):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission.",
            ephemeral=True
        )

    if amount <= 0:
        return await interaction.response.send_message(
            "Enter a number greater than 0.",
            ephemeral=True
        )

    deleted = await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(
        f"Deleted {len(deleted)} messages.",
        ephemeral=True
    )


@admin_group.command(
    name="suggest-button",
    description="Post the anonymous suggestion button in the current channel."
)
async def admin_suggest_button_slash(interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission.",
            ephemeral=True
        )

    if interaction.channel.id not in ALLOWED_SUGGEST_BUTTON_CHANNELS:
        return await interaction.response.send_message(
            "This channel is not approved.",
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


@admin_group.command(
    name="setup",
    description="Start the HydraBot setup wizard."
)
async def admin_setup_slash(interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "You do not have permission.",
            ephemeral=True
        )

    state = {}
    await start_commands_step(interaction, state)


@admin_group.command(
    name="commands-guide",
    description="Post the full commands guide in the configured channel."
)
async def admin_commands_guide_slash(interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("No permission.", ephemeral=True)

    channels = get_guild_channels(interaction.guild.id)
    commands_channel_id = channels["commands_channel_id"]
    channel = interaction.guild.get_channel(commands_channel_id) if commands_channel_id else interaction.channel

    await channel.send(embed=build_commands_guide_embed())
    await interaction.response.send_message("Commands guide posted.", ephemeral=True)


@admin_group.command(
    name="mercy-guide",
    description="Post the mercy tracking guide in the current channel."
)
async def admin_mercy_guide_slash(interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("No permission.", ephemeral=True)

    await interaction.channel.send(embed=build_mercy_guide_embed())
    await interaction.response.send_message("Mercy guide posted.", ephemeral=True)


@admin_group.command(
    name="debug-commands",
    description="List all registered slash commands for debugging."
)
async def admin_debug_commands_slash(interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("No permission.", ephemeral=True)

    cmds = await interaction.client.tree.fetch_commands()

    if not cmds:
        return await interaction.response.send_message("No slash commands registered.", ephemeral=True)

    lines = [f"/{cmd.name} — ID: `{cmd.id}`" for cmd in cmds]

    await interaction.response.send_message(
        "**Registered Slash Commands:**\n" + "\n".join(lines),
        ephemeral=True
    )

    # ============================================================
#  SUPPORT & DEVELOPER SLASH COMMANDS
# ============================================================

@tree.command(
    name="support",
    description="Show the Hydra Companion support server link."
)
async def support_slash(interaction):
    await interaction.response.send_message(
        "**Support Server**\n"
        "https://discord.gg/DuemMm57jr"
    )


@tree.command(
    name="developer",
    description="Show Hydra Companion developer resources and GitHub links."
)
async def developer_slash(interaction):
    await interaction.response.send_message(
        "**Hydra Companion Developer Resources**\n\n"
        "**GitHub Profile:** https://github.com/sketeraid\n"
        "**Desktop App:** https://github.com/sketeraid/HydraCompanionApp\n"
        "**Discord Bot:** https://github.com/sketeraid/HydraCompanion-Discord-Bot\n"
        "**Android App:** https://github.com/sketeraid/HydraCompanionAndroidAPK"
    )

    # ============================================================
#  REGISTER GROUPS & RUN BOT
# ============================================================

tree.add_command(mercy_group)
tree.add_command(reminder_group)
tree.add_command(gacha_group)
tree.add_command(admin_group)

bot.run(TOKEN)