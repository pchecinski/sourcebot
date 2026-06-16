# cogs/roles.py
import discord
from discord.ext import bridge, commands
from discord.ext.commands import has_permissions
from pymongo import MongoClient
from config import config

class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def handle_reaction(self, payload):
        '''Handler for reactions (removing bot's messages & roles in guilds)'''
        emoji = str(payload.emoji)

        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            return

        message = await channel.fetch_message(payload.message_id)
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        member = guild.get_member(payload.user_id)

        # Remove bot's message on "❌" reaction
        if payload.event_type == 'REACTION_ADD' and message.author == self.bot.user and emoji == '❌':
            await message.delete()
            return

        # Check if reaction was in the right channel
        if channel.name != config['discord']['role_channel']:
            return

        # Search for role in mongodb
        client = MongoClient('mongodb://127.0.0.1/sourcebot')
        result = client['sourcebot']['roles'].find_one({
            'guild': payload.guild_id,
            'emoji': emoji
        })

        if result:
            role = guild.get_role(result['role'])
            if payload.event_type == 'REACTION_ADD':
                await member.add_roles(role, reason='emoji_role_add')
            if payload.event_type == 'REACTION_REMOVE':
                await member.remove_roles(role, reason='emoji_role_remove')
        else:
            await message.remove_reaction(payload.emoji, member)

    # listners
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self.handle_reaction(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self.handle_reaction(payload)

    # commands
    @bridge.bridge_command(name='list')
    @has_permissions(administrator=True)
    async def _list(self, ctx):
        '''Returns current list of roles configured for sourcebot.'''
        embed = discord.Embed(title="Current settings", colour=discord.Colour(0x8ba089))
        client = MongoClient('mongodb://127.0.0.1/sourcebot')
        for role in client['sourcebot']['roles'].find({'guild': ctx.guild.id}):
            embed.add_field(name=role['emoji'], value=f"<@&{role['role']}>")
        await ctx.respond(embed=embed)

    @bridge.bridge_command(name='add')
    @has_permissions(administrator=True)
    async def _add(self, ctx, emoji: str, *, role: discord.Role):
        '''Adds a new role reaction to sourcebot.'''
        client = MongoClient('mongodb://127.0.0.1/sourcebot')
        client['sourcebot']['roles'].insert_one({
            'guild': ctx.guild.id,
            'emoji': emoji,
            'role': role.id
        })
        await ctx.respond(f"{self.bot.user.name} added: {emoji} -> {role}")

    @bridge.bridge_command(name='remove')
    @has_permissions(administrator=True)
    async def _remove(self, ctx, emoji: str):
        '''Removes a role reaction from sourcebot list.'''
        client = MongoClient('mongodb://127.0.0.1/sourcebot')
        client['sourcebot']['roles'].delete_one({
            'guild': ctx.guild.id,
            'emoji': emoji
        })
        await ctx.respond(f"{self.bot.user.name} deleted: {emoji}")

def setup(bot):
    bot.add_cog(Roles(bot))