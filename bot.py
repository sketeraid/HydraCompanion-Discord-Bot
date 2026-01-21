import os
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
reminders = {}

TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="$", intents=intents)
scheduler = AsyncIOScheduler(timezone="Europe/London")

async def send_weekly_warning():
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await channel.send("24 HOUR WARNING FOR HYDRA CLASH, Don't forget or you'll miss out on rewards!")

@bot.event
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
async def remindme(ctx, time: str, *, reminder: str):
    await ctx.message.delete()

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

    try:
        await ctx.author.send(f"🔔 Reminder #{reminder_id}: **{reminder}**")
    except:
        await ctx.send(f"{ctx.author.mention} I couldn't DM you, but here's your reminder:\n**{reminder}**")

    reminders[user_id] = [r for r in reminders[user_id] if r["id"] != reminder_id]


@bot.command()
async def reminders(ctx):
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
bot.run(TOKEN)