#!/var/lib/sourcebot/env/bin/python3
# -*- coding: utf-8 -*-
'''
Main source code / entry point for sourcebot
'''

# Python standard libraries
import asyncio
import datetime
import re

# Third-party libraries
import discord
from discord.errors import NotFound
from discord.ext import bridge
from discord.ext.commands import has_permissions
from pymongo import MongoClient
from pysaucenao import SauceNao

# Local modules
import handlers
from config import config

# Prepare bot with intents
intents = discord.Intents.all()
bot = bridge.Bot(command_prefix='$', intents=intents)

# Spoiler regular expression
spoiler_regex = re.compile(r"(\|\|.*?\|\||\<.*?\>|\`.*?\`)", re.DOTALL)

# Role reactions
async def handle_reaction(payload):
    '''
    Hander for reactions (removing bot's messages & roles in guilds)
    '''
    # Parse emoji as string (works for custom emojis and unicode)
    emoji = str(payload.emoji)

    # Get channel object, pass on None
    channel = bot.get_channel(payload.channel_id)
    if channel is None:
        return

    # Fetch message and guild
    message = await channel.fetch_message(payload.message_id)
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    # Fetch member
    member = guild.get_member(payload.user_id)

    # Remove bots message on "x" reaction
    if payload.event_type == 'REACTION_ADD' and message.author == bot.user and emoji == '❌':
        await message.delete()
        return

    # Check if reaction was added/removed in the right channel
    if not channel.name == config['discord']['role_channel']:
        return

    # Search for role in mongodb
    client = MongoClient(config['mongodb']['uri'])
    result = client['sourcebot']['roles'].find_one({
        'guild': payload.guild_id,
        'emoji': emoji
    })

    # Handle reaction if role was found
    if result:
        role = guild.get_role(result['role'])
        if payload.event_type == 'REACTION_ADD':
            await member.add_roles(role, reason='emoji_role_add')

        if payload.event_type == 'REACTION_REMOVE':
            await member.remove_roles(role, reason='emoji_role_remove')

    # Otherwise remove reaction from the message
    else:
        await message.remove_reaction(payload.emoji, member)

# Parser regular expressions list
parsers = [
    # { 'pattern': re.compile(r"(?:pixiv\.net[\/\w]*)\/artworks\/(\w+)"), 'function': handlers.pixiv },
    { 'pattern': re.compile(r"(?:https:\/\/inkbunny.net\/s\/)(\w+)(?:-p)?(\d+)?"), 'function': handlers.inkbunny },
    { 'pattern': re.compile(r"(?<=https://www.furaffinity.net/view/)(\w+)"), 'function': handlers.furaffinity },
    # { 'pattern': re.compile(r"(?<=https://e621.net/posts/)(\w+)"), 'function': handlers.e621 },
    { 'pattern': re.compile(r"(gelbooru.com|rule34.xxx)\/.*id\=(\w+)"), 'function': handlers.booru },
    { 'pattern': re.compile(r"https:\/\/(?:(baraag\.net|pawoo\.net)[.@/\w]*)\/(\w+)"), 'function': handlers.mastodon },
    { 'pattern': re.compile(r"(fx|vx|fixv|fixup|zz)?(?:twitter\.com|x\.com)\/(\w+\/status\/\w+)"), 'function': handlers.twitter },
    { 'pattern': re.compile(r"(?:youtu\.be\/|youtube\.com\/(?:embed\/|shorts\/|v\/|watch\?v=|watch\?.+&v=))([\w-]{11})"), 'function': handlers.youtube },
    { 'pattern': re.compile(r"(https:\/\/(?:(?:v[mt]\.|www\.)tiktok.com(?:\/t)*\/\w+|www.tiktok.com\/@[\w\.]+\/video\/\w+))"), 'function': handlers.tiktok },
    { 'pattern': re.compile(r"(https:\/\/www.deviantart.com\/[0-9a-zA-z\-\/]+)"), 'function': handlers.deviantart },
    { 'pattern': re.compile(r"(https:\/\/(?:www\.)*reddit.com\/r\/.+?\/comments\/.+?\/.+?)\/\?*"), 'function': handlers.reddit },
    { 'pattern': re.compile(r"\.instagram.com\/reel\/([\w-]+)"), 'function': handlers.instagram },
    { 'pattern': re.compile(r"https:\/\/bsky.app\/profile\/([.\w]+)\/post\/(\w+)"), 'function': handlers.bsky }
]

parsers_new = [
    { 'pattern': re.compile(r"(?<=https://e621.net/pools/)(\w+)"), 'function': handlers.e621_pools }
]

@bot.event
async def on_ready():
    print(bot.guilds)

@bot.event
async def on_message(message: discord.Message):
    '''
    Events for each message (main functionality of the bot)
    '''
    # Optional logging - DEBUG USE ONLY, not recommended for production
    #print(f"(Diagnostic) Message from {message.author}: {message.content}")

    if message.author == bot.user:
        return

    # Process prefix commands
    await bot.process_commands(message)

    # Ignore text in valid spoiler tag
    content = re.sub(spoiler_regex, '', message.content)

    # Video conversion functionality
    if isinstance(message.channel, discord.DMChannel) and message.attachments:
        video_attachments = False
        for attachment in message.attachments:
            if attachment.filename.endswith(('mp4', 'webm')):
                video_attachments = True
                kwargs = await handlers.convert(attachment.filename.replace('webm', 'mp4'), attachment.url)
                await message.channel.send(**kwargs)
        
        if video_attachments:
            return

    # Source providing service handlers
    if len(message.attachments) > 0 and isinstance(message.channel, discord.DMChannel) or message.channel.id in config['discord']['sauce_channels']:
        sauce = SauceNao(api_key=config['saucenao']['token'], min_similarity=80.0)
        sources = []

        for attachment in message.attachments:
            results = await sauce.from_url(attachment.url)

            try:
                sources.append(f"<{results[0].urls[0]}>")
            except IndexError:
                print(f"{attachment.url}, {results}")

        if sources:
            source_urls = '\n'.join(sources)
            await message.channel.send(f"Source(s):\n{source_urls}")

    # Detect if message has embeds before lookups
    # if not message.embeds:
    #     await asyncio.sleep(4)
    #     try:
    #         message = await message.channel.fetch_message(message.id)
    #     except NotFound:
    #         # Skip further parsing on immediately deleted messages
    #         return

    # Match and run new parser functions
    for parser in parsers_new:
        for match in re.finditer(parser['pattern'], content):
            files = await parser['function'](
                match = match, message = message
            )

            if isinstance(files, list):
                # Debug logs
                logs_channel = bot.get_channel(config['discord']['logs_channel'])
                await logs_channel.send(f"```\n{message.author=}\n{message.channel=}\n{match.groups()=}\n```")

                for i in range(0, len(files), 10):
                    await message.channel.send(files=[ discord.File(file) for file in files[i:i+10] ])
                    await logs_channel.send(files=[ discord.File(file) for file in files[i:i+10] ])

    # Match and run all supported handers
    for parser in parsers:
        for match in re.finditer(parser['pattern'], content):
            output = await parser['function'](
                match = match, message = message
            )

            if isinstance(output, list):
                # Debug logs
                logs_channel = bot.get_channel(config['discord']['logs_channel'])
                if parser['function'] is not handlers.youtube:
                    await logs_channel.send(f"```\n{message.author=}\n{message.channel=}\n{match.groups()=}\n```")

                for kwargs in output:
                    await message.channel.send(**kwargs)
                    if parser['function'] is not handlers.youtube:
                        await logs_channel.send(**kwargs)

@bot.event
async def on_raw_reaction_add(payload):
    '''
    Reaction hander (adding reactions)
    '''
    await handle_reaction(payload)

@bot.event
async def on_raw_reaction_remove(payload):
    '''
    Reaction hander (removing reactions)
    '''
    await handle_reaction(payload)

# Various Commands
@bot.bridge_command(name='tiktok')
async def _tiktok(ctx):
    '''
    Posts a random tiktok from sourcebot's collection.
    '''
    client = MongoClient(config['mongodb']['uri'])
    tiktok = client['sourcebot']['tiktok_db'].aggregate([{ "$sample": { "size": 1 } }]).next()
    await ctx.respond(f"{config['media']['url']}/tiktok-{tiktok['tiktok_id']}.mp4")

@bot.bridge_command(name='friday')
async def _friday(ctx):
    '''
    Today is Friday in California!
    '''
    await ctx.respond(f"{config['media']['url']}/discord-friday.mp4")

@bot.bridge_command(name='flat')
async def _flat(ctx):
    '''
    Today is Flat Fuck Friday!
    '''
    await ctx.respond(f"{config['media']['url']}/discord-flat.mov")

@bot.bridge_command(name='pies')
async def _pies(ctx):
    '''
    Initiate dog protolol.
    '''
    await ctx.respond(f"{config['media']['url']}/protocol-dog.jpg")

@bot.bridge_command(name='siec')
async def _siec(ctx):
    '''
    Robicie coś z siecią?.
    '''
    await ctx.respond(f"{config['media']['url']}/network.png")

@bot.bridge_command(name='summon')
async def _summon(ctx, allowed_mentions = True):
    '''
    Summon DI.
    '''
    await ctx.defer()
    await ctx.send(f"<@&1156175038043652106> summon", )

@bot.bridge_command(name='ping')
async def _ping(ctx, addr: str):
    '''
    Ping ip address or hostname.
    '''
    from ping3 import ping
    r = ping(addr)
    await ctx.respond(f"Ping to {addr} result: {r}")

# Roles commands
@bot.bridge_command(name='list')
@has_permissions(administrator=True)
async def _list(ctx):
    '''
    Returns current list of roles configured for sourcebot.
    '''
    embed = discord.Embed(title="Current settings", colour=discord.Colour(0x8ba089))
    client = MongoClient(config['mongodb']['uri'])
    for role in client['sourcebot']['roles'].find({'guild': ctx.guild.id}):
        embed.add_field(name=role['emoji'], value=f"<@&{role['role']}>")
    await ctx.respond(embed=embed)

@bot.bridge_command(name='add')
@has_permissions(administrator=True)
async def _add(ctx, emoji: str, *, role: discord.Role):
    '''
    Adds a new role reaction to the sourcebot.
    '''
    client = MongoClient(config['mongodb']['uri'])
    client['sourcebot']['roles'].insert_one({
        'guild': ctx.guild.id,
        'emoji': emoji,
        'role': role.id
    })
    await ctx.respond(f"{bot.user.name} added: {emoji} -> {role}")

@bot.bridge_command(name = 'remove')
@has_permissions(administrator=True)
async def _remove(ctx, emoji: str):
    '''
    Removes a role reaction from sourcebot list.
    '''
    client = MongoClient(config['mongodb']['uri'])
    client['sourcebot']['roles'].delete_one({
        'guild': ctx.guild.id,
        'emoji': emoji
    })
    await ctx.respond(f"{bot.user.name} deleted: {emoji}")

if __name__ == '__main__':
    # Main Loop
    bot.run(config['discord']['token'])
