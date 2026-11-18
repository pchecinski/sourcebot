# Python standard libraries
import re
from datetime import datetime

# Third-party libraries
import discord
from aiohttp import ClientSession
from discord.ext import commands
from discord.ext.commands import has_permissions
from pymongo import MongoClient

# Local modules
from config import config

class Ai(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ai_col = MongoClient(config['mongo']['uri'])['sourcebot']['ai_profiles']

        self.twitter_pattern = re.compile(r"(?:twitter\.com|x\.com)\/\w+\/status\/(\w+)")
        self.bsky_pattern = re.compile(r"https:\/\/bsky\.app\/profile\/([\w.:-]+)\/post\/(\w+)")

    async def _add_twitter(self, ctx, tweet_id: str):
        async with ClientSession() as session:
            async with session.get(f"https://api.fxtwitter.com/2/status/{tweet_id}") as response:
                tweet_data = await response.json()

        author = tweet_data['author']

        if self.ai_col.find_one({'twitter_id': author['id']}):
            await ctx.respond("This user is already in the confirmed AI list.")
            return

        self.ai_col.insert_one({
            'twitter_screen_name': author['screen_name'],
            'twitter_id': author['id'],
            'discord_name': ctx.author.name,
            'discord_id': ctx.author.id,
            'ban_time': datetime.now()
        })

        await ctx.respond(
            f"<:sourcebot:1443368717588103291> Added <https://x.com/{author['screen_name']}> (ID: {author['id']}) to confirmed AI list."
        )

    async def _add_bsky(self, ctx, actor: str):

        async with ClientSession() as session:
            async with session.get(f"https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor={actor}") as response:
                profile = await response.json()

        if self.ai_col.find_one({'bsky_did': profile['did']}):
            await ctx.respond("<:sourcebot:1443368717588103291> This user is already in the confirmed AI list.")
            return

        self.ai_col.insert_one({
            'bsky_handle': profile['handle'],
            'bsky_did': profile['did'],
            'discord_name': ctx.author.name,
            'discord_id': ctx.author.id,
            'ban_time': datetime.now()
        })

        await ctx.respond(
            f"<:sourcebot:1443368717588103291> Added <https://bsky.app/profile/{profile['handle']}> (DID: {profile['did']}) to confirmed AI list."
        )

    @commands.message_command(name="Confirmed AI?")
    @has_permissions(manage_messages=True)
    async def _save_ai_profile(self, ctx: discord.ApplicationContext, message: discord.Message):
        tweet_ids = self.twitter_pattern.findall(message.content)
        bsky_posts = self.bsky_pattern.findall(message.content)

        total = len(tweet_ids) + len(bsky_posts)

        if total == 0:
            await ctx.respond("<:sourcebot:1443368717588103291> Found 0 twitter/bsky links.")
            return

        if total > 1:
            await ctx.respond("<:sourcebot:1443368717588103291> Found more than 1 twitter/bsky link.")
            return

        await ctx.defer()

        if tweet_ids:
            await self._add_twitter(ctx, tweet_ids[0])
        else:
            actor, _post_id = bsky_posts[0]
            await self._add_bsky(ctx, actor)


def setup(bot):
    bot.add_cog(Ai(bot))