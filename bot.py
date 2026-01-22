import os
import random
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
import sqlite3

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

@bot.check
async def globally_block_channels(ctx):
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

import sqlite3
import discord
from discord.ext import commands

# -----------------------------
# DATABASE SETUP
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
# DB HELPERS
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
        msg = await ctx.send("Nuh uh, I do not think so, peasant XD")
        await msg.delete(delay=5)

bot.run(TOKEN)