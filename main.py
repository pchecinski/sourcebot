#!/home/discordbot/sourcebot-env/bin/python3.8
# -*- coding: utf-8 -*-
'''
Main source code / entry point for sourcebot
'''

# Python standard libraries
import asyncio
import queue
import re
from pprint import pprint

# Third-party libraries
import discord
from discord.errors import NotFound
from discord.ext.commands import has_permissions
from pymongo import MongoClient
from saucenao_api import SauceNao

# Local modules
import handlers
from config import config

# Prepare bot with intents
intents = discord.Intents.default()
intents.members = True
intents.reactions = True
bot = discord.Bot(intents=intents)

# Tiktok queue
tiktok_queue = queue.Queue()

# Spoiler regular expression
spoiler_regex = re.compile(r"(\|\|.*?\|\||\<.*?\>)", re.DOTALL)

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
    client = MongoClient("mongodb://127.0.0.1/sourcebot")
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
    { 'pattern': re.compile(r"(?:pixiv\.net[\/\w]*)\/artworks\/(\w+)"), 'function': handlers.pixiv },
    { 'pattern': re.compile(r"(?<=https://inkbunny.net/s/)(\w+)"), 'function': handlers.inkbunny },
    { 'pattern': re.compile(r"(?<=https://www.furaffinity.net/view/)(\w+)"), 'function': handlers.furaffinity },
    { 'pattern': re.compile(r"(?<=https://e621.net/posts/)(\w+)"), 'function': handlers.e621 },
    { 'pattern': re.compile(r"(?<=https://e621.net/pools/)(\w+)"), 'function': handlers.e621_pools },
    { 'pattern': re.compile(r"(?<=https://rule34.xxx/index.php\?page\=post\&s\=view\&id\=)(\w+)"), 'function': handlers.rule34xxx },
    { 'pattern': re.compile(r"(?<=https://gelbooru.com/index.php\?page\=post\&s\=view\&id\=)(\w+)"), 'function': handlers.gelbooru },
    { 'pattern': re.compile(r"(?:pawoo.net\/@\w+|pawoo.net\/web\/statuses)\/(\w+)"), 'function': handlers.pawoo },
    { 'pattern': re.compile(r"(?:baraag.net\/@\w+|baraag.net\/web\/statuses)\/(\w+)"), 'function': handlers.baraag },
    { 'pattern': re.compile(r"(?:twitter.com\/)(\w+\/status\/\w+)"), 'function': handlers.twitter },
    { 'pattern': re.compile(r"(?:youtu\.be\/|youtube\.com\/(?:embed\/|shorts\/|v\/|watch\?v=|watch\?.+&v=))([\w-]{11})"), 'function': handlers.youtube },
    { 'pattern': re.compile(r"((?:https:\/\/vm.tiktok.com\/|https:\/\/www.tiktok.com\/t\/)\w+)"), 'function': handlers.tiktok },
    { 'pattern': re.compile(r"(https:\/\/www.tiktok.com\/@\w+\/video\/\w+)"), 'function': handlers.tiktok },
    { 'pattern': re.compile(r"(https:\/\/www.deviantart.com\/[0-9a-zA-z\-\/]+)"), 'function': handlers.deviantart }
]

@bot.event
async def on_message(message):
    '''
    Events for each message (main functionality of the bot)
    '''
    if message.author == bot.user:
        return

    # Ignore text in valid spoiler tag
    content = re.sub(spoiler_regex, '', message.content)

    # Source providing service handlers
    if message.channel.id in config['discord']['sauce_channels'] and len(message.attachments) > 0:
        sauce = SauceNao(config['saucenao']['token'])
        sources = []

        for attachment in message.attachments:
            results = sauce.from_url(attachment.url)

            if not results or results[0].similarity < 80:
                continue

            try:
                sources.append(f"<{results[0].urls[0]}>")
            except IndexError:
                pprint(f"{attachment.url}, {results}")

        # if len(sources) == 0:
        #     return

        source_urls = '\n'.join(sources)
        await message.channel.send(f"Source(s):\n{source_urls}")

    # Detect if message has embeds before lookups
    if not message.embeds:
        await asyncio.sleep(2.5)
        try:
            message = await message.channel.fetch_message(message.id)
        except NotFound:
            # Skip further parsing on immediately deleted messages
            return

    # Match and run all supported handers
    for parser in parsers:
        for match in re.finditer(parser['pattern'], content):
            print(f"[debug]: {parser['function'].__name__} -> {match.group(1)}")
            output = await parser['function'](
                match = match.group(1), 
                embeds = len(message.embeds),
                is_dm = isinstance(message.channel, discord.DMChannel)
            )

            if isinstance(output, list):
                for kwargs in output:
                    await message.channel.send(**kwargs)
            elif output:
                await message.channel.send(**output)

    # Video conversion functionality
    if isinstance(message.channel, discord.DMChannel) and message.attachments:
        for attachment in message.attachments:
            if attachment.filename.endswith('mp4'):
                kwargs = await handlers.convert(attachment.filename, attachment.url)
                await message.channel.send(**kwargs)

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
@bot.slash_command(guild_ids = config['discord']['guild_ids'], name='tiktok')
async def _tiktok(ctx):
    '''
    Posts a random tiktok from sourcebot's collection.
    '''
    client = MongoClient("mongodb://127.0.0.1/sourcebot")
    tiktok = client['sourcebot']['tiktok_db'].aggregate([{ "$sample": { "size": 1 } }]).next()
    await ctx.respond(f"{config['media']['url']}/tiktok-{tiktok['tiktok_id']}.mp4")

# Roles commands
@bot.slash_command(guild_ids = config['discord']['guild_ids'], name='list')
@has_permissions(administrator=True)
async def _list(ctx):
    '''
    Returns current list of roles configured for sourcebot.
    '''
    embed = discord.Embed(title="Current settings", colour=discord.Colour(0x8ba089))
    client = MongoClient("mongodb://127.0.0.1/sourcebot")
    for role in client['sourcebot']['roles'].find({'guild': ctx.guild.id}):
        embed.add_field(name=role['emoji'], value=f"<@&{role['role']}>")
    await ctx.respond(embed=embed)

@bot.slash_command(guild_ids = config['discord']['guild_ids'], name='add')
@has_permissions(administrator=True)
async def _add(ctx, emoji: str, *, role: discord.Role):
    '''
    Adds a new role reaction to the sourcebot.
    '''
    client = MongoClient("mongodb://127.0.0.1/sourcebot")
    client['sourcebot']['roles'].insert_one({
        'guild': ctx.guild.id,
        'emoji': emoji,
        'role': role.id
    })
    await ctx.respond(f"{bot.user.name} added: {emoji} -> {role}")

@bot.slash_command(guild_ids = config['discord']['guild_ids'], name = 'remove')
@has_permissions(administrator=True)
async def _remove(ctx, emoji: str):
    '''
    Removes a role reaction from sourcebot list.
    '''
    client = MongoClient("mongodb://127.0.0.1/sourcebot")
    client['sourcebot']['roles'].delete_one({
        'guild': ctx.guild.id,
        'emoji': emoji
    })
    await ctx.respond(f"{bot.user.name} deleted: {emoji}")

if __name__ == '__main__':
    # Main Loop
    bot.run(config['discord']['token'])
