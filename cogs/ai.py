# cogs/roles.py
import discord
import re

from discord.ext import commands
from discord.ext.commands import has_permissions
from pymongo import MongoClient
from config import config
from aiohttp import ClientSession, BasicAuth, ContentTypeError
import asyncio
from config import config
from datetime import datetime

client = MongoClient(config['mongo']['uri'])
ai_col = client['sourcebot']['ai_profiles']

class Ai(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.twitter_pattern = re.compile(r"(?:twitter\.com|x\.com)\/\w+\/status\/(\w+)")

    @commands.message_command(name="Confirmed AI?")
    @has_permissions(manage_messages=True)
    async def _list(self, ctx: discord.ApplicationContext, message: discord.Message):
        ''''''

        tweet_ids = re.findall(self.twitter_pattern, message.content)

        if len(tweet_ids) == 0:
            await ctx.respond("Found 0 twitter links.")
            return

        if len(tweet_ids) > 1:
            await ctx.respond("Found more than 1 twitter link.")
            return

        tweet_id = tweet_ids[0]

        async with ClientSession() as session:
            async with session.get(f"https://api.fxtwitter.com/2/status/{tweet_id}") as response:
                tweet_data = await response.json()

        if ai_col.find_one({
            'twitter_id': tweet_data['author']['id']
        }):
            await ctx.respond("This user is already in the confirmed AI list.")
            return

        ai_col.insert_one({
            'twitter_screen_name': tweet_data['author']['screen_name'],
            'twitter_id': tweet_data['author']['id'],
            'discord_name': ctx.author.name,
            'discord_id': ctx.author.id,
            'ban_time': datetime.now()
        })

        await ctx.respond(f"Added <https://x.com/{tweet_data['author']['screen_name']}> (ID: {tweet_data['author']['id'] }) to confirmed AI list.")

def setup(bot):
    bot.add_cog(Ai(bot))