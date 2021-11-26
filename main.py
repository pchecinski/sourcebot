#!/home/discordbot/sourcebot-env/bin/python3.8
# -*- coding: utf-8 -*-

# Python standard libraries
import asyncio
import io
import logging
import queue
import random
import re
import string
import threading
from pprint import pprint

# Third-party libraries
import discord
import magic
from aiohttp import ClientSession
from TikTokApi import TikTokApi
from discord.ext import commands
from saucenao_api import SauceNao

# Local modules
import handlers
from config import config, roles_settings, roles_update

# Prepare bot with intents
intents = discord.Intents.default()
intents.members = True
intents.reactions = True
bot = commands.Bot(command_prefix='$', intents=intents)

# Tiktok queue
tiktok_queue = queue.Queue()

# Spoiler regular expression
spoiler_regex = re.compile(r"\|\|(.*?)\|\|", re.DOTALL)

def tiktok_worker():
    while True:
        # Get a task from queue
        message, url = tiktok_queue.get()
        tiktok_id = url.split('/')[-1]

        api = TikTokApi.get_instance(custom_did="".join(random.choices(string.digits, k=19)))
        try:
            data = api.get_video_by_url(url)
        except Exception:
            LOGGER_TIKTOK.exception("TIKTOK THREAD: Exception occurred", exc_info=True)

            coro = message.add_reaction('<:boterror:854665168889184256>')
            task = asyncio.run_coroutine_threadsafe(coro, bot.loop)
            task.result()

            tiktok_queue.task_done()
            continue

        size = len(data) / 1048576
        mime = magic.from_buffer(io.BytesIO(data).read(2048), mime=True)

        # Log tiktok urls to tiktok.log
        location = f"{message.author} (dm)" if isinstance(message.channel, discord.DMChannel) else f"{message.guild.name}/{message.channel.name}"
        LOGGER_TIKTOK.info('[%s]\n%s, size: %.2f MB, mime: %s', location, url, size, mime)

        if mime != 'video/mp4':
            coro = message.add_reaction('<:boterror:854665168889184256>')
        elif size == 0:
            coro = message.add_reaction('<:botempty:854665168888528896>')
        elif size > 8.0:
            with open(f"{config['media']['path']}/tiktok-{tiktok_id}.mp4", 'wb') as file:
                file.write(data)
            coro = message.channel.send(f"{config['media']['url']}/tiktok-{tiktok_id}.mp4")

        else:
            coro = message.channel.send(file=discord.File(io.BytesIO(data), filename=f"tiktok-{tiktok_id}.mp4"))

        # Run async task on the bot thread
        task = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        task.result()

        tiktok_queue.task_done()

# Role reactions
async def handle_reaction(payload):
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

    # Remove reaction if it isn't in roles dictionary
    if not emoji in roles_settings['roles']:
        await message.remove_reaction(payload.emoji, member)
        return

    # Get role from settings
    role = guild.get_role(roles_settings['roles'][emoji])

    if payload.event_type == 'REACTION_ADD':
        await member.add_roles(role, reason='emoji_role_add')

    if payload.event_type == 'REACTION_REMOVE':
        await member.remove_roles(role, reason='emoji_role_remove')

# Sourcenao
async def provide_sources(message):
    sauce = SauceNao(config['saucenao']['token'])
    sources = []

    for attachment in message.attachments:
        results = sauce.from_url(attachment.url)

        if len(results) == 0:
            continue

        if results[0].similarity < 80:
            continue

        try:
            sources.append(f"<{results[0].urls[0]}>")

            # Log source to sources.log
            location = f"{message.author} (dm)" if isinstance(message.channel, discord.DMChannel) else f"{message.guild.name}/{message.channel.name}"
            LOGGER_SOURCES.info('[%s]\n%s -> %s (%.2f%%)', location, attachment.url, results[0].urls[0], results[0].similarity)

        except Exception:
            pprint(f"{attachment.url}, {results}")
            LOGGER_SOURCES.exception("Exception occurred (source provider)", exc_info=True)

    if len(sources) == 0:
        return

    source_urls = '\n'.join(sources)
    await message.reply(f"Source(s):\n{source_urls}")

# Parser regular expressions list
parsers = [
    { 'pattern': re.compile(r"(?<=https://www.pixiv.net/en/artworks/)(\w+)"), 'function': handlers.pixiv },
    { 'pattern': re.compile(r"(?<=https://inkbunny.net/s/)(\w+)"), 'function': handlers.inkbunny },
    { 'pattern': re.compile(r"(?<=https://www.furaffinity.net/view/)(\w+)"), 'function': handlers.furaffinity },
    { 'pattern': re.compile(r"(?<=https://e621.net/posts/)(\w+)"), 'function': handlers.e621 },
    { 'pattern': re.compile(r"(?<=https://rule34.xxx/index.php\?page\=post\&s\=view\&id\=)(\w+)"), 'function': handlers.rule34xxx },
    { 'pattern': re.compile(r"(?<=https://pawoo.net/web/statuses/)(\w+)"), 'function': handlers.pawoo },
    { 'pattern': re.compile(r"(?<=https://pawoo.net/)@\w+/(\w+)"), 'function': handlers.pawoo },
    { 'pattern': re.compile(r"(?<=https://baraag.net/web/statuses/)(\w+)"), 'function': handlers.baraag },
    { 'pattern': re.compile(r"(?<=https://baraag.net/)@\w+/(\w+)"), 'function': handlers.baraag },
    { 'pattern': re.compile(r"(?<=https://twitter.com/)(\w+/status/\w+)"), 'function': handlers.twitter },
    { 'pattern': re.compile(r"(?<=https://fxtwitter.com/)(\w+/status/\w+)"), 'function': handlers.twitter },
]

tiktok_patterns = {
    'short': re.compile(r"(?<=https://vm.tiktok.com/)(\w+)"),
    'long': re.compile(r"(?<=https://www.tiktok.com/)(@\w+\/video\/\w+)")
}

# Events
@bot.event
async def on_ready():
    logging.info('%s ready!', bot.user.name)

@bot.event
async def on_message(message):
    try:
        if message.author == bot.user:
            return

        if isinstance(message.channel, discord.DMChannel) and message.attachments:
            for attachment in message.attachments:
                if attachment.filename.endswith('mp4'):
                    kwargs = await handlers.convert(attachment.filename, attachment.url)
                    await message.channel.send(**kwargs)
            return

        # Process commands (emojis)
        await bot.process_commands(message)

        # Ignore text in valid spoiler tag
        content = re.sub(spoiler_regex, '', message.content)

        # Post tiktok videos
        for match in re.finditer(tiktok_patterns['short'], content):
            # Support for short url (mobile links)
            short_url = 'https://vm.tiktok.com/' + match.group(1)

            # Parse short url with HTTP HEAD + redirects
            async with ClientSession() as session:
                session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.71 Safari/537.36'
                })
                async with session.head(short_url, allow_redirects=True) as response:
                    url = str(response.url).split('?')[0] # remove all the junk in query data

            # Add task to tiktok queue
            tiktok_queue.put((message, url))

        for match in re.finditer(tiktok_patterns['long'], content):
            # Support for long url (browser links)
            url = 'https://www.tiktok.com/' + match.group(1)

            # Add task to tiktok queue
            tiktok_queue.put((message, url))

        # Source providing service handlers
        if message.channel.id in config['discord']['art_channels'] or isinstance(message.channel, discord.DMChannel):
            if len(message.attachments) > 0:
                await provide_sources(message)
                return

            # Match and run all supported handers
            for parser in parsers:
                for match in re.finditer(parser['pattern'], content):
                    kwargs = await parser['function'](match.group(1))
                    if kwargs:
                        await message.channel.send(**kwargs)

    except Exception as exception:
        pprint(exception)
        logging.exception("Exception occurred", exc_info=True)

@bot.event
async def on_raw_reaction_add(payload):
    await handle_reaction(payload)

@bot.event
async def on_raw_reaction_remove(payload):
    await handle_reaction(payload)

# Commands
@bot.command(name='list')
@commands.has_permissions(administrator=True)
async def _list(ctx):
    embed = discord.Embed(title="Current settings", colour=discord.Colour(0x8ba089))

    for emoji in roles_settings['roles']:
        embed.add_field(name=emoji, value=f"<@&{roles_settings['roles'][emoji]}>")

    await ctx.send(embed=embed)

@bot.command(name='add')
@commands.has_permissions(administrator=True)
async def _add(ctx, emoji: str, *, role: discord.Role):
    print(f"{bot.user.name} added: {emoji} -> {role}")
    roles_settings['roles'][emoji] = role.id
    roles_update()
    await ctx.send(f"{bot.user.name} added: {emoji} -> {role}")

@bot.command(name='remove')
@commands.has_permissions(administrator=True)
async def _remove(ctx, emoji: str):
    del roles_settings['roles'][emoji]
    roles_update()
    await ctx.send(f"{bot.user.name} deleted: {emoji}")

def setup_logger(name, log_file, level=logging.INFO):
    handler = logging.FileHandler(log_file)
    handler.setFormatter(logging.Formatter('[%(levelname)s] [%(asctime)s]: %(message)s'))

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger

if __name__ == '__main__':
    logging.basicConfig(filename='logs/error.log', format='[%(levelname)s] [%(asctime)s]: %(message)s', level=logging.ERROR)
    LOGGER_TIKTOK = setup_logger('tiktok', 'logs/tiktok.log', level=logging.ERROR)
    LOGGER_SOURCES = setup_logger('sources', 'logs/sources.log', level=logging.ERROR)

    # Start tiktok thread
    threading.Thread(target=tiktok_worker, daemon=True).start()

    # Main Loop
    bot.run(config['discord']['token'])
