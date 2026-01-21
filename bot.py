import os
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TOKEN = os.getenv("a21ef1a054f0106b935dd74366101e87bb85a47d1b02cbde83835861e03da5f1")
CHANNEL_ID = int(os.getenv("1463574113829519585"))

TOKEN = "a21ef1a054f0106b935dd74366101e87bb85a47d1b02cbde83835861e03da5f1"
 CHANNEL_ID = 1463574113829519585

 intents = discord.Intents.default()
 bot = commands.Bot(command_prefix="!", intents=intents)

 scheduler = AsyncIOScheduler()

 @bot.event
 async def on_ready():
     print(f"Logged in as {bot.user}")

     # Start the scheduler once the bot is ready
     scheduler.start()

     # Schedule the weekly message
     scheduler.add_job(
         send_weekly_warning,
         "cron",
         day_of_week="tue",
         hour=8,             # 24h format (18 = 6pm)
         minute=0
     )

 async def send_weekly_warning():
     channel = bot.get_channel(CHANNEL_ID)
     if channel:
         await channel.send("24 HOUR WARNING FOR HYDRA CLASH, Don't forget or you'll miss out on rewards!")

bot.run(TOKEN)
