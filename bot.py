import os
import random
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
reminders = {}

TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
TEST_CHANNEL_ID = int(os.getenv("TESTCHANNEL_ID"))
PULL_CHANNEL_ID = int(os.getenv("PULL_CHANNEL_ID"))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="$", intents=intents)
scheduler = AsyncIOScheduler(timezone="Europe/London")

async def send_weekly_warning():
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await channel.send("24 HOUR WARNING FOR HYDRA CLASH, Don't forget or you'll miss out on rewards!")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    channel = bot.get_channel(CHANNEL_ID)
    print("Channel resolved:", channel)

    # Start scheduler only once
    try:
        scheduler.start()
    except:
        pass

    # Add jobs (safe to add even if scheduler is already running)
    scheduler.add_job(
        send_weekly_warning,
        "cron",
        day_of_week="tue",
        hour=8,
        minute=0
    )

    scheduler.add_job(
        send_weekly_warning,
        "cron",
        day_of_week="tue",
        hour=12,
        minute=0
    )
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


@bot.command()
async def remindme(ctx, time: str, *, reminder: str = None):
    await ctx.message.delete()

    # If user forgets the reminder text
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

        from discord.ext import commands

@bot.command(name="pull")
async def should_i_pull(ctx, *, event: str = None):
    await ctx.message.delete(delay=15)

    # Only allow in one channel
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

    msg = await ctx.send(embed=embed)
    await msg.delete(delay=15)

bot.run(TOKEN)