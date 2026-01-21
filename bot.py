import os
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler

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
async def on_ready():
    print(f"Logged in as {bot.user}")

    scheduler.start()
    scheduler.add_job(
        send_weekly_warning,
        "cron",
        day_of_week="tue",
        hour=12,
        minute=0
    )

@bot.command()
async def test(ctx):
    await ctx.send("Hydra warning test successful.")

bot.run(TOKEN)