import os
import random
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
import sqlite3
from datetime import date

reminders = {}

TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
TEST_CHANNEL_ID = int(os.getenv("TESTCHANNEL_ID"))
PULL_CHANNEL_ID = int(os.getenv("PULL_CHANNEL_ID"))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="$", intents=intents)
scheduler = AsyncIOScheduler(timezone="Europe/London")

ALLOWED_CHANNEL = 1463963620483530784
SUGGEST_BUTTON_CHANNELS = [1463963533640335423, 1463963575780507669]
WORDLE_CHANNEL = 1253815983400030339

@bot.check
async def global_gatekeeper(ctx):
    # Allow announce anywhere
    if ctx.command and ctx.command.name == "announce":
        return True

    # Allow suggestbutton in its own channels
    if ctx.command and ctx.command.name == "suggestbutton":
        if ctx.channel.id in SUGGEST_BUTTON_CHANNELS:
            return True
        await ctx.send("Silly human, this command can only be used in the suggestion channels.")
        return False

    # Allow Wordle commands in the Wordle channel
    if ctx.command and ctx.command.name in ("wordle", "guess", "wordlestats"):
        if ctx.channel.id == WORDLE_CHANNEL:
            return True
        await ctx.send(f"Wordle can only be played in <#{WORDLE_CHANNEL}>.")
        return False

    # Everything else must be in ALLOWED_CHANNEL
    if ctx.channel.id != ALLOWED_CHANNEL:
        await ctx.send(f"Silly human, these commands can only be used in <#{ALLOWED_CHANNEL}>.")
        return False

    return True

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

# -----------------------------
# COOLDOWN HANDLER
# -----------------------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        msg = await ctx.send("Nice try but I am on cooldown :D")
        return await msg.delete(delay=30)
    raise error

# -----------------------------
# HYDRA WARNING SCHEDULER
# -----------------------------
async def send_weekly_warning():
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await channel.send("24 HOUR WARNING FOR HYDRA CLASH, Don't forget or you'll miss out on rewards!")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    channel = bot.get_channel(CHANNEL_ID)
    print("Channel resolved:", channel)

    try:
        scheduler.start()
    except:
        pass

    scheduler.add_job(send_weekly_warning, "cron", day_of_week="tue", hour=8, minute=0)
    scheduler.add_job(send_weekly_warning, "cron", day_of_week="tue", hour=12, minute=0)

# -----------------------------
# BASIC COMMANDS
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
# REMINDER SYSTEM
# -----------------------------
@bot.command()
async def remindme(ctx, time: str, *, reminder: str = None):
    await ctx.message.delete()

    if reminder is None:
        await ctx.send("You need to tell me what to remind you about.\nExample: `$remindme 10m take the bins out`")
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
# SHOULD I PULL?
# -----------------------------
@bot.command(name="pull")
async def should_i_pull(ctx, *, event: str = None):
    await ctx.message.delete(delay=15)

    if ctx.channel.id != PULL_CHANNEL_ID:
        return

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
# GACHA SIMULATOR
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

# ============================================================
#                FULL MERCY SYSTEM (FINAL VERSION)
# ============================================================

# -----------------------------
# DATABASE SETUP (MERCY)
# -----------------------------
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
conn.commit()

# -----------------------------
# BASE RATES FOR MERCY
# -----------------------------
BASE_RATES = {
    "ancient": {"epic": 8.0, "legendary": 0.5, "mythical": 0.0},
    "void": {"epic": 8.0, "legendary": 0.5, "mythical": 0.0},
    "primal": {"epic": 16.0, "legendary": 1.0, "mythical": 0.5},
    "sacred": {"epic": 94.0, "legendary": 6.0, "mythical": 0.0}  # Sacred has NO epic pity
}

# -----------------------------
# MERCY CALCULATION FUNCTIONS
# -----------------------------
def calc_epic_chance(shard_type, pity):
    # Ancient & Void: +2% per shard AFTER 20 pulls
    if shard_type in ("ancient", "void"):
        base = BASE_RATES[shard_type]["epic"]
        if pity <= 20:
            return base
        extra = pity - 20
        return min(100.0, base + extra * 2.0)

    # Primal & Sacred: no epic scaling
    return BASE_RATES[shard_type]["epic"]


def calc_legendary_chance(shard_type, pity):
    # Ancient & Void: +5% per shard AFTER 200 pulls
    if shard_type in ("ancient", "void"):
        base = BASE_RATES[shard_type]["legendary"]
        if pity <= 200:
            return base
        extra = pity - 200
        return min(100.0, base + extra * 5.0)

    # Primal: +1% per shard AFTER 75 pulls
    if shard_type == "primal":
        base = BASE_RATES["primal"]["legendary"]
        if pity <= 75:
            return base
        extra = pity - 75
        return min(100.0, base + extra * 1.0)

    # Sacred: +2% per shard AFTER 12 pulls
    if shard_type == "sacred":
        base = BASE_RATES["sacred"]["legendary"]
        if pity <= 12:
            return base
        extra = pity - 12
        return min(100.0, base + extra * 2.0)

    return BASE_RATES[shard_type]["legendary"]


def calc_mythical_chance(shard_type, pity):
    # Primal: +10% per shard AFTER 200 pulls
    if shard_type == "primal":
        base = BASE_RATES["primal"]["mythical"]
        if pity <= 200:
            return base
        extra = pity - 200
        return min(100.0, base + extra * 10.0)

    # Other shards: no mythical pity
    return BASE_RATES[shard_type]["mythical"]

# -----------------------------
# DB HELPERS (MERCY)
# -----------------------------
def get_mercy_row(user_id, shard_type):
    shard_type = shard_type.lower()
    c.execute("SELECT epic_pity, legendary_pity, mythical_pity FROM mercy WHERE user_id=? AND shard_type=?", (str(user_id), shard_type))
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

# -----------------------------
# MERCY COMMAND
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

    highest_chance = 0

    # Epic ONLY for Ancient/Void
    if shard_type in ("ancient", "void"):
        epic_chance = calc_epic_chance(shard_type, epic)
        highest_chance = max(highest_chance, epic_chance)
        embed.add_field(
            name="Epic",
            value=f"Pity: **{epic}**\nChance: **{epic_chance:.2f}%**",
            inline=False
        )

    # Legendary for all shards
    legendary_chance = calc_legendary_chance(shard_type, legendary)
    highest_chance = max(highest_chance, legendary_chance)
    embed.add_field(
        name="Legendary",
        value=f"Pity: **{legendary}**\nChance: **{legendary_chance:.2f}%**",
        inline=False
    )

    # Mythical only for Primal
    if shard_type == "primal":
        mythical_chance = calc_mythical_chance(shard_type, mythical)
        highest_chance = max(highest_chance, mythical_chance)
        embed.add_field(
            name="Mythical",
            value=f"Pity: **{mythical}**\nChance: **{mythical_chance:.2f}%**",
            inline=False
        )

    # Ready to pull message
    if highest_chance > 51:
        embed.add_field(
            name="🔥 Ready?",
            value="Looks like you are ready to pull :P",
            inline=False
        )

    await ctx.send(embed=embed)

# -----------------------------
# MERCYALL COMMAND
# -----------------------------
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
        highest_chance = 0

        # Epic only for Ancient/Void
        if shard in ("ancient", "void"):
            epic_chance = calc_epic_chance(shard, epic)
            highest_chance = max(highest_chance, epic_chance)
            text += f"**Epic:** {epic} pulls — {epic_chance:.2f}%\n"

        # Legendary for all shards
        legendary_chance = calc_legendary_chance(shard, legendary)
        highest_chance = max(highest_chance, legendary_chance)
        text += f"**Legendary:** {legendary} pulls — {legendary_chance:.2f}%"

        # Mythical only for Primal
        if shard == "primal":
            mythical_chance = calc_mythical_chance(shard, mythical)
            highest_chance = max(highest_chance, mythical_chance)
            text += f"\n**Mythical:** {mythical} pulls — {mythical_chance:.2f}%"

        # Ready to pull message
        if highest_chance > 51:
            text += "\n🔥 **Looks like you are ready to pull :P**"

        embed.add_field(name=shard.capitalize(), value=text, inline=False)

    await ctx.send(embed=embed)

# -----------------------------
# CLEAR MERCY
# -----------------------------
@bot.command(name="clearmercy")
async def clear_mercy_cmd(ctx, shard_type: str):
    shard_type = shard_type.lower()
    if shard_type not in BASE_RATES:
        return await ctx.send("Invalid shard type.")

    set_mercy_row(ctx.author.id, shard_type, 0, 0, 0)
    await ctx.send(f"{ctx.author.mention}, your {shard_type} mercy has been reset.")

# -----------------------------
# MANUAL TRACKING COMMANDS
# -----------------------------
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

# -----------------------------
# ADDPULL COMMAND
# -----------------------------
@bot.command(name="addpull")
async def add_pull_cmd(ctx, shard_type: str, amount: int):
    shard_type = shard_type.lower()

    if shard_type not in BASE_RATES:
        return await ctx.send("Invalid shard type. Use: ancient, void, primal, sacred.")

    if amount <= 0:
        return await ctx.send("Amount must be a positive number.")

    epic, legendary, mythical = get_mercy_row(ctx.author.id, shard_type)

    # Epic pity only for Ancient/Void
    if shard_type in ("ancient", "void"):
        epic += amount

    # Legendary pity for all shards
    legendary += amount

    # Mythical pity only for Primal
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
# PURGE COMMAND
# -----------------------------
@bot.command(name="purge")
@commands.has_permissions(administrator=True)
async def purge_cmd(ctx, amount: int):
    # Delete the command message first
    await ctx.message.delete()

    if amount <= 0:
        warn = await ctx.send("Please enter a number greater than 0.")
        return await warn.delete(delay=5)

    # Purge the requested number of messages
    deleted = await ctx.channel.purge(limit=amount)

    # Confirmation message
    confirm = await ctx.send(f"Deleted {len(deleted)} messages.")
    await confirm.delete(delay=5)

@purge_cmd.error
async def purge_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):

        responses = [
            "Nuh uh, I do not think so, peasant XD",
            "https://media.tenor.com/4ZC0u8T8n5MAAAAC/rickroll.gif"
        ]

        choice = random.choice(responses)
        await ctx.send(choice)

# -----------------------------
# ANNOUNCE COMMAND
# -----------------------------
ANNOUNCE_CHANNEL_ID = 1461342242470887546

@bot.command(name="announce")
@commands.has_permissions(administrator=True)
async def announce_cmd(ctx, *, message: str):
    # Delete the admin's command message
    await ctx.message.delete()

    # Get the announcement channel
    channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)

    # Build the embed
    embed = discord.Embed(
        title="📢 Announcement",
        description=message,
        color=discord.Color.blue()
    )

    embed.set_footer(
        text=f"Posted by {ctx.author}",
        icon_url=ctx.author.avatar.url
    )

    embed.timestamp = discord.utils.utcnow()

    # Send the announcement to the correct channel
    await channel.send(embed=embed)

@announce_cmd.error
async def announce_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):

        responses = [
            "Nuh uh, I do not think so, peasant XD",
            "https://media.tenor.com/4ZC0u8T8n5MAAAAC/rickroll.gif"
        ]

        choice = random.choice(responses)
        await ctx.send(choice)

# -----------------------------
# ANONYMOUS SUGGESTIONS (DM)
# -----------------------------
SUGGESTION_CHANNEL_ID = 1464216800651640893  # replace this

@bot.event
async def on_message(message):
    # Ignore bot messages
    if message.author.bot:
        return

    # Check if the message is a DM to the bot
    if isinstance(message.channel, discord.DMChannel):
        suggestion = message.content

        # Get the suggestion review channel
        channel = bot.get_channel(SUGGESTION_CHANNEL_ID)

        # Build the anonymous suggestion embed
        embed = discord.Embed(
            title="💡 New Anonymous Suggestion (DM)",
            description=suggestion,
            color=discord.Color.green()
        )

        embed.set_footer(text="Anonymous submission")

        # Send the suggestion to the private channel
        await channel.send(embed=embed)

        # Confirm to the user
        await message.author.send("Your anonymous suggestion has been submitted.")
        return

    # Allow normal commands to work
    await bot.process_commands(message)

ALLOWED_SUGGEST_BUTTON_CHANNELS = {
    1463963533640335423,
    1463963575780507669
}

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

@bot.command(name="suggestbutton")
@commands.has_permissions(administrator=True)
async def suggest_button_cmd(ctx):
    # Restrict command to the two allowed channels
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

# ============================================================
#                     WORDLE SYSTEM (TIER 4)
# ============================================================

WORDLE_DB_PATH = "wordle.db"
WORD_LENGTH = 5
MAX_GUESSES = 6

# Simple demo word list – you can expand this
WORD_LIST = [
    "apple", "brick", "crane", "flame", "ghost",
    "light", "sound", "track", "world", "pride",
]

ALLOWED_GUESSES = set(WORD_LIST)

def get_wordle_db():
    conn_w = sqlite3.connect(WORDLE_DB_PATH)
    conn_w.row_factory = sqlite3.Row
    return conn_w

def init_wordle_db():
    conn_w = get_wordle_db()
    cur = conn_w.cursor()

    # Per-user stats
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER PRIMARY KEY,
            played INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            streak INTEGER NOT NULL DEFAULT 0,
            max_streak INTEGER NOT NULL DEFAULT 0,
            dist1 INTEGER NOT NULL DEFAULT 0,
            dist2 INTEGER NOT NULL DEFAULT 0,
            dist3 INTEGER NOT NULL DEFAULT 0,
            dist4 INTEGER NOT NULL DEFAULT 0,
            dist5 INTEGER NOT NULL DEFAULT 0,
            dist6 INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Per-user game for a given day
    cur.execute("""
        CREATE TABLE IF NOT EXISTS games (
            user_id INTEGER NOT NULL,
            game_date TEXT NOT NULL,
            target_word TEXT NOT NULL,
            guesses TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active', -- active, win, loss
            hard_mode INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, game_date)
        )
    """)

    conn_w.commit()
    conn_w.close()

init_wordle_db()

def get_daily_word_for_date(d: date) -> str:
    idx = d.toordinal() % len(WORD_LIST)
    return WORD_LIST[idx]

def today_str():
    return date.today().isoformat()

def score_guess(guess: str, target: str):
    result = ['b'] * WORD_LENGTH
    target_chars = list(target)

    # First pass: greens
    for i in range(WORD_LENGTH):
        if guess[i] == target[i]:
            result[i] = 'g'
            target_chars[i] = None

    # Second pass: yellows
    for i in range(WORD_LENGTH):
        if result[i] == 'g':
            continue
        if guess[i] in target_chars:
            result[i] = 'y'
            target_chars[target_chars.index(guess[i])] = None

    return result

def markers_to_emoji(markers):
    mapping = {
        'g': "🟩",
        'y': "🟨",
        'b': "⬛"
    }
    return "".join(mapping[m] for m in markers)

def parse_guesses_str(guesses_str: str):
    if not guesses_str:
        return []
    return guesses_str.split(",")

def append_guess(guesses_str: str, guess: str):
    if not guesses_str:
        return guess
    return guesses_str + "," + guess

def get_hard_mode_constraints(guesses, target):
    greens = {}
    yellows = set()

    for guess in guesses:
        markers = score_guess(guess, target)
        for i, m in enumerate(markers):
            if m == 'g':
                greens[i] = guess[i]
            elif m == 'y':
                yellows.add(guess[i])

    return greens, yellows

def validate_hard_mode_guess(guess, greens, yellows):
    for pos, letter in greens.items():
        if guess[pos] != letter:
            return False, f"Hard mode: position {pos+1} must be `{letter}`."

    for letter in yellows:
        if letter not in guess:
            return False, f"Hard mode: your guess must include `{letter}`."

    return True, None

def get_or_create_wordle_stats(user_id: int):
    conn_w = get_wordle_db()
    cur = conn_w.cursor()
    cur.execute("SELECT * FROM stats WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO stats (user_id) VALUES (?)", (user_id,))
        conn_w.commit()
        cur.execute("SELECT * FROM stats WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
    conn_w.close()
    return row

def update_wordle_stats_after_game(user_id: int, won: bool, guesses_count):
    conn_w = get_wordle_db()
    cur = conn_w.cursor()
    stats = get_or_create_wordle_stats(user_id)

    played = stats["played"] + 1
    wins = stats["wins"] + (1 if won else 0)
    losses = stats["losses"] + (0 if won else 1)
    streak = stats["streak"]
    max_streak = stats["max_streak"]

    if won:
        streak += 1
        if streak > max_streak:
            max_streak = streak
    else:
        streak = 0

    dist1 = stats["dist1"]
    dist2 = stats["dist2"]
    dist3 = stats["dist3"]
    dist4 = stats["dist4"]
    dist5 = stats["dist5"]
    dist6 = stats["dist6"]

    if won and guesses_count is not None:
        if guesses_count == 1:
            dist1 += 1
        elif guesses_count == 2:
            dist2 += 1
        elif guesses_count == 3:
            dist3 += 1
        elif guesses_count == 4:
            dist4 += 1
        elif guesses_count == 5:
            dist5 += 1
        elif guesses_count == 6:
            dist6 += 1

    cur.execute("""
        UPDATE stats SET
            played = ?,
            wins = ?,
            losses = ?,
            streak = ?,
            max_streak = ?,
            dist1 = ?,
            dist2 = ?,
            dist3 = ?,
            dist4 = ?,
            dist5 = ?,
            dist6 = ?
        WHERE user_id = ?
    """, (
        played, wins, losses, streak, max_streak,
        dist1, dist2, dist3, dist4, dist5, dist6,
        user_id
    ))

    conn_w.commit()
    conn_w.close()

@bot.command(name="wordle")
async def wordle_start(ctx, mode: str = None):
    """
    Start today's Wordle.
    Usage: $wordle [hard]
    """
    user_id = ctx.author.id
    today = today_str()
    target = get_daily_word_for_date(date.today())
    hard_mode = (mode is not None and mode.lower() == "hard")

    conn_w = get_wordle_db()
    cur = conn_w.cursor()
    cur.execute("SELECT * FROM games WHERE user_id = ? AND game_date = ?", (user_id, today))
    game = cur.fetchone()

    if game is not None:
        if game["status"] == "active":
            await ctx.send("You already have an active game for today. Use `$guess <word>` to continue.")
        else:
            await ctx.send("You've already finished today's Wordle. Come back tomorrow!")
        conn_w.close()
        return

    cur.execute("""
        INSERT INTO games (user_id, game_date, target_word, hard_mode)
        VALUES (?, ?, ?, ?)
    """, (user_id, today, target, 1 if hard_mode else 0))
    conn_w.commit()
    conn_w.close()

    msg = f"Started today's Wordle! Word length: **{WORD_LENGTH}**. You have **{MAX_GUESSES}** guesses.\n"
    if hard_mode:
        msg += "Hard mode is **ON**: you must reuse revealed hints correctly.\n"
    msg += "Use `$guess <word>` to make your first guess."
    await ctx.send(msg)

@bot.command(name="guess")
async def wordle_guess(ctx, guess: str):
    """
    Make a guess for today's Wordle.
    Usage: $guess apple
    """
    guess = guess.lower()
    if len(guess) != WORD_LENGTH:
        await ctx.send(f"Your guess must be {WORD_LENGTH} letters long.")
        return

    if guess not in ALLOWED_GUESSES:
        await ctx.send("That word is not in the allowed word list.")
        return

    user_id = ctx.author.id
    today = today_str()

    conn_w = get_wordle_db()
    cur = conn_w.cursor()
    cur.execute("SELECT * FROM games WHERE user_id = ? AND game_date = ?", (user_id, today))
    game = cur.fetchone()

    if game is None:
        await ctx.send("You don't have an active game today. Start one with `$wordle`.")
        conn_w.close()
        return

    if game["status"] != "active":
        await ctx.send("Today's game is already finished. Wait for tomorrow's word!")
        conn_w.close()
        return

    target = game["target_word"]
    guesses_str = game["guesses"]
    guesses = parse_guesses_str(guesses_str)

    # Hard mode validation
    if game["hard_mode"]:
        greens, yellows = get_hard_mode_constraints(guesses, target)
        ok, reason = validate_hard_mode_guess(guess, greens, yellows)
        if not ok:
            await ctx.send(reason)
            conn_w.close()
            return

    markers = score_guess(guess, target)
    emoji_row = markers_to_emoji(markers)

    guesses.append(guess)
    new_guesses_str = append_guess(guesses_str, guess)

    # Win
    if guess == target:
        status = "win"
        cur.execute("""
            UPDATE games
            SET guesses = ?, status = ?
            WHERE user_id = ? AND game_date = ?
        """, (new_guesses_str, status, user_id, today))
        conn_w.commit()
        conn_w.close()

        grid = []
        for g in guesses:
            m = score_guess(g, target)
            grid.append(markers_to_emoji(m))
        grid_str = "\n".join(grid)

        await ctx.send(
            f"{emoji_row}\n\nYou guessed it in **{len(guesses)}** tries! 🎉\n\n{grid_str}"
        )
        update_wordle_stats_after_game(user_id, True, len(guesses))
        return

    # Loss
    if len(guesses) >= MAX_GUESSES:
        status = "loss"
        cur.execute("""
            UPDATE games
            SET guesses = ?, status = ?
            WHERE user_id = ? AND game_date = ?
        """, (new_guesses_str, status, user_id, today))
        conn_w.commit()
        conn_w.close()

        grid = []
        for g in guesses:
            m = score_guess(g, target)
            grid.append(markers_to_emoji(m))
        grid_str = "\n".join(grid)

        await ctx.send(
            f"{emoji_row}\n\nNo more guesses left. The word was **{target.upper()}**.\n\n{grid_str}"
        )
        update_wordle_stats_after_game(user_id, False, None)
        return

    # Still active
    cur.execute("""
        UPDATE games
        SET guesses = ?
        WHERE user_id = ? AND game_date = ?
    """, (new_guesses_str, user_id, today))
    conn_w.commit()
    conn_w.close()

    await ctx.send(
        f"{emoji_row}\nGuess {len(guesses)}/{MAX_GUESSES}. Keep going!"
    )

@bot.command(name="wordlestats")
async def wordle_stats(ctx):
    """
    Show your Wordle stats.
    """
    user_id = ctx.author.id
    stats = get_or_create_wordle_stats(user_id)

    played = stats["played"]
    wins = stats["wins"]
    losses = stats["losses"]
    streak = stats["streak"]
    max_streak = stats["max_streak"]

    if played > 0:
        win_rate = round((wins / played) * 100, 1)
    else:
        win_rate = 0.0

    dist = [
        stats["dist1"],
        stats["dist2"],
        stats["dist3"],
        stats["dist4"],
        stats["dist5"],
        stats["dist6"],
    ]

    dist_lines = []
    for i, v in enumerate(dist, start=1):
        dist_lines.append(f"{i}: {'█' * v} ({v})")

    dist_block = "\n".join(dist_lines) if dist_lines else "No wins yet."

    msg = (
        f"**Wordle Stats for {ctx.author.display_name}**\n"
        f"Played: **{played}**\n"
        f"Wins: **{wins}**\n"
        f"Losses: **{losses}**\n"
        f"Win rate: **{win_rate}%**\n"
        f"Current streak: **{streak}**\n"
        f"Max streak: **{max_streak}**\n\n"
        f"**Guess Distribution**\n{dist_block}"
    )

    await ctx.send(msg)

# -----------------------------
# RUN BOT
# -----------------------------
bot.run(TOKEN)