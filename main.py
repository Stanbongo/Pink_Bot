import random
import os
from dotenv import load_dotenv
from cogs.database import setup_database
import discord
from discord.ext import commands
import asyncio

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f'Бот {bot.user} готов! Команды: {[c.name for c in bot.commands]}')

async def main():
    await setup_database()
    load_dotenv()
    token = os.getenv('DISCORD_BOT_TOKEN')
    async with bot:
        await bot.load_extension("cogs.commands")
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
