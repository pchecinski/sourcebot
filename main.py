#!/opt/sourcebot/env/bin/python3
# -*- coding: utf-8 -*-
'''
Main source code / entry point for sourcebot
'''

# Python standard libraries
import os
import re

# Third-party libraries
import discord
from discord.ext import commands
from pymongo import MongoClient
from pysaucenao import SauceNao

# Local modules
import handlers
from config import config

# Prepare bot with intents
bot = commands.Bot(intents=discord.Intents.all())

# Spoiler regular expression
spoiler_regex = re.compile(r"(\|\|.*?\|\||\<.*?\>|\`.*?\`)", re.DOTALL)

# Parser regular expressions list
parsers = [
    { 'pattern': re.compile(r"(?:pixiv\.net[\/\w]*)\/artworks\/(\w+)"), 'function': handlers.pixiv },
    { 'pattern': re.compile(r"(?<=https://www.furaffinity.net/view/)(\w+)"), 'function': handlers.furaffinity },
    { 'pattern': re.compile(r"(gelbooru.com|rule34.xxx)\/.*id\=(\w+)"), 'function': handlers.booru },
    { 'pattern': re.compile(r"https:\/\/(?:(pawoo\.net)[.@/\w]*)\/(\w+)"), 'function': handlers.mastodon },
    { 'pattern': re.compile(r"(?:youtu\.be\/|youtube\.com\/(?:embed\/|shorts\/|v\/|watch\?v=|watch\?.+&v=))([\w-]{11})"), 'function': handlers.youtube },
    { 'pattern': re.compile(r"(https:\/\/(?:(?:v[mt]\.|www\.)tiktok.com(?:\/t)*\/\w+|www.tiktok.com\/@[\w\.]+\/video\/\w+))"), 'function': handlers.tiktok },
    # { 'pattern': re.compile(r"(https:\/\/www.deviantart.com\/[0-9a-zA-z\-\/]+)"), 'function': handlers.deviantart },
    # { 'pattern': re.compile(r"(https:\/\/(?:www\.)*reddit.com\/r\/.+?\/comments\/.+?\/.+?)\/\?*"), 'function': handlers.reddit },
    { 'pattern': re.compile(r"(https?:\/\/(?:www\.)?instagram\.com\/(?:reel|reels|p|tv|share)\/([A-Za-z0-9_\-]+))"), 'function': handlers.instagram },
    { 'pattern': re.compile(r"https:\/\/bsky\.app\/profile\/([\w.:-]+)\/post\/(\w+)"), 'function': handlers.bsky }
]

parsers_new = [
    { 'pattern': re.compile(r"(?<=https://e621.net/pools/)(\w+)"), 'function': handlers.e621_pools },
    { 'pattern': re.compile(r"(?<=https://inkbunny.net/s/)(\w+)(?:-p)?(\d+)?"), 'function': handlers.inkbunny },
    { 'pattern': re.compile(r"(fx|vx|fixv|fixup|zz)?(?:twitter\.com|x\.com)\/(\w+\/status\/\w+)"), 'function': handlers.twitter },
]

@bot.event
async def on_ready():
    print("Client is ready!")

async def handle_snail(message: discord.Message, match: re.Match):
    if isinstance(message.channel, discord.DMChannel):
        return

    client = MongoClient(config['mongo']['uri'])
    snail_col = client['sourcebot']['snail']

    result = snail_col.find_one({
        'guild_id': message.guild.id,
        'match': match.group(0)
    })

    if result:
        await message.add_reaction('🐌')

    else:
        snail_col.insert_one({
            'guild_id': message.guild.id,
            'channel_id': message.channel.id,
            'message_id': message.id,
            'match': match.group(0)
        })

@bot.event
async def on_message(message: discord.Message):
    '''
    Events for each message (main functionality of the bot)
    '''
    if message.author == bot.user:
        return

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

    # oc-refs "automod"
    if message.channel.id == 1479519364721017044:
        if len(message.attachments) == 0:
            await message.delete(delay=3)

    # Match and run new parser functions
    for parser in parsers_new:
        for match in re.finditer(parser['pattern'], content):
            files, embed = await parser['function'](
                match = match, message = message
            )
            await handle_snail(message, match)

            if isinstance(files, list):
                # Debug logs
                logs_channel = bot.get_channel(config['discord']['logs_channel'])
                await logs_channel.send(f"```\n{message.author=}\n{message.channel=}\n{match.groups()=}\n```")

                # 10MB limit per message / file
                limit = 10 * 1024 * 1024 * 0.95

                # Split files to batches up to 10 files or 10MB, use URLs for too large files
                batches, current, size, links = [], [], 0, []
                for file in files:
                    file_size = os.path.getsize(file)
                    if file_size > limit:
                        links.append(f"{config['media']['url']}/{os.path.basename(file)}")
                        continue
                    if current and (len(current) == 10 or size + file_size > limit):
                        batches.append(current)
                        current, size = [], 0
                    current.append(file)
                    size += file_size
                if current:
                    batches.append(current)

                # Send everything to the original channel first, then mirror it to logs
                for channel in (message.channel, logs_channel):
                    for i, batch in enumerate(batches):
                        is_last = i == len(batches) - 1
                        await channel.send(
                            embed=embed if is_last else None,
                            files=[discord.File(file) for file in batch],
                        )

                    if not batches and embed:
                        await channel.send(embed=embed)

                    for link in links:
                        await channel.send(link)

    # Match and run all supported handers
    for parser in parsers:
        for match in re.finditer(parser['pattern'], content):
            output = await parser['function'](
                match = match, message = message
            )
            if parser['function'] is not handlers.youtube:
                await handle_snail(message, match)

            if isinstance(output, list):
                # Debug logs
                logs_channel = bot.get_channel(config['discord']['logs_channel'])
                if parser['function'] is not handlers.youtube:
                    await logs_channel.send(f"```\n{message.author=}\n{message.channel=}\n{match.groups()=}\n```")

                for kwargs in output:
                    await message.channel.send(**kwargs)
                    if parser['function'] is not handlers.youtube:
                        await logs_channel.send(**kwargs)

# Load cogs
bot.load_extension('cogs.guild_profile')
bot.load_extension('cogs.ai')
bot.load_extension('cogs.fun')
bot.load_extension('cogs.roles')
bot.load_extension('cogs.reminders')

if __name__ == '__main__':
    # Main Loop
    bot.run(config['discord']['token'])
