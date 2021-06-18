#!/home/discordbot/sourcebot-env/bin/python3.8
# -*- coding: utf-8 -*-

import aiohttp
import asyncio
import datetime
import discord
import faapi
import hashlib
import io
import json
import logging
import magic
import os
import queue
import random
import re
import requests
import shlex
import string
import subprocess
import threading
import xmltodict
import yaml
import youtube_dl

from TikTokApi import TikTokApi
from dateutil import tz
from discord.ext import commands
from html.parser import HTMLParser
from saucenao_api import SauceNao
from tempfile import TemporaryDirectory
from zipfile import ZipFile

MAIN_CONFIG = "config/main.yml"
ROLES_SETTINGS = "config/roles.yml"

# Load config files
config = yaml.safe_load(open(MAIN_CONFIG))
roles_settings = yaml.safe_load(open(ROLES_SETTINGS))

# Prepare bot with intents
intents = discord.Intents.default()
intents.members = True
intents.reactions = True
bot = commands.Bot(command_prefix='$', intents=intents)

# Tiktok queue
tiktok_queue = queue.Queue()

def tiktok_worker():
    while True:
        # Get a task from queue
        message, url = tiktok_queue.get()

        api = TikTokApi.get_instance(custom_did="".join(random.choices(string.digits, k=19)))
        try:
            data = api.get_video_by_url(url)
        except Exception as e:
            logging.exception("TIKTOK THREAD: Exception occurred", exc_info=True) # api.clean_up() # TODO: possible fix for some errors

            coro = message.add_reaction('<:boterror:854665168889184256>')
            task = asyncio.run_coroutine_threadsafe(coro, bot.loop)
            result = task.result()

            tiktok_queue.task_done()
            continue

        size = len(data) / 1048576
        mime = magic.from_buffer(io.BytesIO(data).read(2048), mime=True)

        # Log tiktok urls to tiktok.log
        asctime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open('logs/tiktok.log', 'a') as f:
            location = f"{message.author} (dm)" if isinstance(message.channel, discord.DMChannel) else f"{message.guild.name}/{message.channel.name}"
            f.write(f"[{asctime}] [{location}]\n{url}, size: {size:.2f} MB, mime: {mime}\n")

        if mime != 'video/mp4':
            coro = message.add_reaction('<:boterror:854665168889184256>')
        elif size == 0:
            coro = message.add_reaction('<:botempty:854665168888528896>')
        elif size > 8.0:
            coro = message.add_reaction('<:botlarge:854665168831381504>')
        else:
            coro = message.reply(file=discord.File(io.BytesIO(data), filename='tiktok-video.mp4')) 

        # Run async task on the bot thread
        task = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        result = task.result()

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
async def provideSources(message): 
    sauce = SauceNao(config['saucenao']['token'])
    sources = []

    for attachment in message.attachments:
        results = sauce.from_url(attachment.url)

        if len(results) == 0:
            continue

        if results[0].similarity < 80:
            continue

        sources.append(f"<{results[0].urls[0]}>")

        # Log source to sources.log
        asctime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open('logs/sources.log', 'a') as f:
            location = f"{message.author} (dm)" if isinstance(message.channel, discord.DMChannel) else f"{message.guild.name}/{message.channel.name}"
            f.write(f"[{asctime}] [{location}]\n{attachment.url} -> {results[0].urls[0]} ({results[0].similarity}%)\n")
    
    if len(sources) == 0:
        return
    
    source_urls = '\n'.join(sources)
    await message.reply(f"Source(s):\n{source_urls}")

# Source fetching
async def handlePixivUrl(message, submission_id):
    # Static data for pixiv
    AUTH_URL = "https://oauth.secure.pixiv.net/auth/token"
    BASE_URL = "https://app-api.pixiv.net"

    CLIENT_ID = "KzEZED7aC0vird8jWyHM38mXjNTY"
    CLIENT_SECRET = "W9JZoJe00qPvJsiyCGT3CCtC6ZUtdpKpzMbNlUGP"
    LOGIN_SECRET = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"

    HEADERS = {
        "User-Agent": "PixivAndroidApp/5.0.115 (Android 6.0; PixivBot)",
        "Accept-Language": "English"
    }

    # Prepare Access Token
    async with aiohttp.ClientSession() as session:
        session.headers.update(HEADERS)
        client_time = datetime.datetime.utcnow().replace(microsecond=0).replace(tzinfo=datetime.timezone.utc).isoformat()

        # Authenticate using Refresh token
        async with session.post(
            url = AUTH_URL,
            data = {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "get_secure_url": 1,
                "grant_type": "refresh_token",
                "refresh_token": config['pixiv']['token']
            },
            headers = {
                "X-Client-Time": client_time,
                "X-Client-Hash": hashlib.md5(
                    (client_time + LOGIN_SECRET).encode("utf-8")
                ).hexdigest()
            },
        ) as response:
            data = await response.json()
            session.headers.update({"Authorization": f"Bearer {data['access_token']}"})

        # Get Illustration details
        async with session.get(
            url = f"{BASE_URL}/v1/illust/detail",
            params = { "illust_id": submission_id },
        ) as response:
            data = await response.json()
            session.headers.update({"Referer": f"https://www.pixiv.net/member_illust.php?mode=medium&illust_id={submission_id}"})

        # Skip safe work
        if data['illust']['x_restrict'] == 0:
            return 

        if data['illust']['x_restrict'] == 2:
            await message.reply("Please don't post this kind of art on this server. (R-18G)", mention_author=True)
            await message.delete()
            return

        async with message.channel.typing():
            # Prepare the embed object
            embed = discord.Embed(title=f"{data['illust']['title']} by {data['illust']['user']['name']}", color=discord.Color(0x40C2FF))

            if data['illust']['type'] == 'ugoira':
                busy_message = await message.channel.send("Oh hey, that's an animated one, it will take me a while!")

                # Get file metadata (framges and zip_url)
                async with session.get(
                    url = f"{BASE_URL}/v1/ugoira/metadata",
                    params = { "illust_id": submission_id },
                ) as response:
                    data = await response.json()

                # Download and extract zip archive to temporary directory
                with TemporaryDirectory() as tmpdir:
                    async with session.get(data['ugoira_metadata']['zip_urls']['medium']) as response:
                        with ZipFile(io.BytesIO(await response.read()), 'r') as zip_ref: 
                            zip_ref.extractall(tmpdir)

                    # Prepare ffmpeg "concat demuxer" file
                    with open(f"{tmpdir}/ffconcat.txt", 'w') as f:
                        for frame in data['ugoira_metadata']['frames']:
                            frame_file = frame['file']
                            frame_duration = round(frame['delay'] / 1000, 4)

                            f.write(f"file {frame_file}\nduration {frame_duration}\n")
                        f.write(f"file {data['ugoira_metadata']['frames'][-1]['file']}")

                    if len(data['ugoira_metadata']['frames']) > 60:
                        ext, ext_params = "webm", ""
                    else:
                        ext, ext_params = "gif", "-vf 'scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse' -loop 0"

                    # Run ffmpeg for the given file/directory
                    subprocess.call(
                        shlex.split(f"ffmpeg -loglevel fatal -hide_banner -y -f concat -i ffconcat.txt {ext_params} {submission_id}.{ext}"),
                        cwd=os.path.abspath(tmpdir)
                    )

                    file = discord.File(f"{tmpdir}/{submission_id}.{ext}", filename=f"{submission_id}.{ext}")
                    embed.set_image(url=f"attachment://{submission_id}.{ext}")

                # Delete information about dealing with longer upload
                await busy_message.delete()

            else:
                if data['illust']['meta_single_page']:
                    url = data['illust']['meta_single_page']['original_image_url']
                else:
                    url = data['illust']['meta_pages'][0]['image_urls']['original']
                ext = os.path.splitext(url)[1]
                async with session.get(url) as response:
                    file = discord.File(io.BytesIO(await response.read()), filename=f"{submission_id}.{ext}")
                    embed.set_image(url=f"attachment://{submission_id}.{ext}")

    await message.channel.send(embed=embed, file=file)

async def handleInkbunnyUrl(message, submission_id):
    async with aiohttp.ClientSession() as session:
        # Log in to API and get session ID
        async with session.get(f"https://inkbunny.net/api_login.php?username={config['inkbunny']['username']}&password={config['inkbunny']['password']}") as r:
            data = await r.json()
            session_id = data['sid']

        # Request information about the submission
        async with session.get(f"https://inkbunny.net/api_submissions.php?sid={session_id}&submission_ids={submission_id}") as r:
            data = await r.json()

    if len(data['submissions']) != 1:
        return

    # Get image url and send it
    submission = data['submissions'][0]

    async with message.channel.typing():
        embed = discord.Embed(title=f"{submission['title']} by {submission['username']}", color=discord.Color(0xFCE4F1))
        embed.set_image(url=submission['file_url_full'])
    await message.channel.send(embed=embed)

async def handleE621Url(message, submission_id):
    async with aiohttp.ClientSession() as session:
        session.headers.update({
            'User-Agent': f"{bot.user.name} by {config['e621']['username']}"
        })

        # Get image data using API Endpoint
        async with session.get(f"https://e621.net/posts/{submission_id}.json", auth=aiohttp.BasicAuth(config['e621']['username'], config['e621']['api_key'])) as r:
            data = await r.json()
            post = data['post']

            # Check for global blacklist (ignore other links as they already come with previews)
            if 'young' not in post['tags']['general'] or post['rating'] != 'e':
                return

    async with message.channel.typing():
        embed = discord.Embed(title=f"Picture by {post['tags']['artist'][0]}", color=discord.Color(0x00549E))
        embed.set_image(url=post['sample']['url'])
    await message.channel.send(embed=embed)

async def handleFuraffinityUrl(message, submission_id):
    cookies = [
        {"name": "a", "value": config['furaffinity']['cookie']['a']},
        {"name": "b", "value": config['furaffinity']['cookie']['b']},
    ]

    api = faapi.FAAPI(cookies)
    submission, _ = api.get_submission(submission_id)

    if submission.rating == 'General':
        return

    async with message.channel.typing():
        embed = discord.Embed(title=f"{submission.title} by {submission.author}", color=discord.Color(0xFAAF3A))
        embed.set_image(url=submission.file_url)
    await message.channel.send(embed=embed)

async def handleRule34xxxUrl(message, submission_id):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://rule34.xxx/index.php?page=dapi&s=post&q=index&id={submission_id}") as r:
            data = xmltodict.parse(await r.text())

    async with message.channel.typing(): 
        embed = discord.Embed(color=discord.Color(0xABE5A4)) # TODO: Title? Maybe try to use source from the webiste if provided for other handers?
        embed.set_image(url=data['posts']['post']['@file_url'])
    await message.channel.send(embed=embed)

async def handlePawooContent(message, submission_id):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://pawoo.net/api/v1/statuses/{submission_id}") as r:
            data = await r.json()

    with open(f"logs/pawoo_{submission_id}.json", 'w') as outfile:
        json.dump(data, outfile)

    # Skip statuses without media attachments
    if 'media_attachments' not in data:
        return

    embed = discord.Embed(title=f"Picture by {data['account']['display_name']}", color=discord.Color(0xFAAF3A))
    embed.set_image(url=data['media_attachments'][0]['url'])

    #async with message.channel.typing():
    #await message.channel.send(embed=embed)

async def handleBaraagContent(message, submission_id):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://baraag.net/api/v1/statuses/{submission_id}") as r:
            data = await r.json()

    with open(f"logs/baraag_{submission_id}.json", 'w') as outfile:
        json.dump(data, outfile)

    # Skip statuses without media attachments
    if 'media_attachments' not in data:
        return

    embed = discord.Embed(title=f"Picture by {data['account']['display_name']}", color=discord.Color(0xFAAF3A))
    embed.set_image(url=data['media_attachments'][0]['url'])

    #async with message.channel.typing():
    #await message.channel.send(embed=embed)

async def handleTwitterVideo(message, submission_id):
    # Tweet ID from URL
    tweet_id = submission_id.split('/')[-1]
    async with aiohttp.ClientSession() as session:
        session.headers.update({'Authorization': f"Bearer {config['twitter']['token']}"})

        async with session.get(f"https://api.twitter.com/2/tweets/{tweet_id}?expansions=attachments.media_keys&media.fields=type") as response:
            tweet_data = await response.json() 

            if 'includes' not in tweet_data:
                print(f"{tweet_id}: text only")
                return 

            if tweet_data['includes']['media'][0]['type'] != 'video':
                print(f"{tweet_id}: video attachment not found")
                return

    # Download video to temporary directory
    with TemporaryDirectory() as tmpdir:
        with youtube_dl.YoutubeDL({'format': 'best', 'quiet': True, 'extract_flat': True, 'outtmpl': f"{tmpdir}/{tweet_id}.%(ext)s"}) as ydl:
            try:
                meta = ydl.extract_info(f"https://twitter.com/{submission_id}")
            except:
                print(f"{tweet_id}: ytdl exception, that shouldn't happen..")
                return 

            async with message.channel.typing(): 
                # ext, ext_params = "webm", ""
                # subprocess.call(
                #     shlex.split(f"ffmpeg -loglevel fatal -hide_banner -y -i {name}.{meta['ext']} {ext_params} {name}.{ext}"),
                #     cwd=os.path.abspath(tmpdir)
                # )

                with open(f"{tmpdir}/{tweet_id}.{meta['ext']}", 'rb') as f:
                    # embed = discord.Embed(title=f"{name}", color=discord.Color(0x69b005))

                    file = discord.File(f, filename=f"{tweet_id}.{meta['ext']}")
                    # embed.set_image(url=f"attachment://{name}.{ext}")
                await message.channel.send(file=file)

# Events 
@bot.event
async def on_ready():
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]: The great and only {bot.user.name} has connected to Discord API!")

@bot.event 
async def on_message(message):
    try:
        if message.author == bot.user:
            return

        # Process commands (emojis)
        await bot.process_commands(message)

        # Ignore text in valid spoiler tag
        spoiler_regeq = re.compile('\|\|(.*?)\|\|', re.DOTALL)
        content = re.sub(spoiler_regeq, '', message.content)

        # Post tiktok videos
        if message.channel.id in config['discord']['tiktok_channels'] or isinstance(message.channel, discord.DMChannel):
            # Support for short url (mobile links)
            for match in re.finditer(r"(?<=https://vm.tiktok.com/)(\w+)", content):
                short_url = 'https://vm.tiktok.com/' + match.group(1)

                # Parse short url with HTTP HEAD + redirects
                async with aiohttp.ClientSession() as session:
                    session.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.77 Safari/537.36'
                    })
                    async with session.head(short_url, allow_redirects=True) as r:
                        url = str(r.url).split('?')[0] # remove all the junk in query data

                # Add task to tiktok queue
                tiktok_queue.put((message, url))

            # Support for long url (browser links)
            for match in re.finditer(r"(?<=https://www.tiktok.com/)(@\w+\/video\/\w+)", content):
                url = 'https://www.tiktok.com/' + match.group(1)

                # Add task to tiktok queue
                tiktok_queue.put((message, url))

        # Source providing service handlers
        if message.channel.id in config['discord']['art_channels'] or isinstance(message.channel, discord.DMChannel):
            if len(message.attachments) > 0:
                await provideSources(message)
                return 

            for match in re.finditer(r"(?<=https://www.pixiv.net/en/artworks/)(\w+)", content):
                await handlePixivUrl(message, match.group(1))

            for match in re.finditer(r"(?<=https://inkbunny.net/s/)(\w+)", content):
                await handleInkbunnyUrl(message, match.group(1))

            for match in re.finditer(r"(?<=https://www.furaffinity.net/view/)(\w+)", content):
                await handleFuraffinityUrl(message, match.group(1))

            for match in re.finditer(r"(?<=https://e621.net/posts/)(\w+)", content):
                await handleE621Url(message, match.group(1))

            for match in re.finditer(r"(?<=https://rule34.xxx/index.php\?page\=post\&s\=view\&id\=)(\w+)", content): # TODO: better regex?
                await handleRule34xxxUrl(message, match.group(1))

            for match in re.finditer(r"(?<=https://pawoo.net/web/statuses/)(\w+)", content):
                await handlePawooContent(message, match.group(1))

            for match in re.finditer(r"(?<=https://pawoo.net/)@\w+/(\w+)", content):
                await handlePawooContent(message, match.group(1))

            for match in re.finditer(r"(?<=https://baraag.net/web/statuses/)(\w+)", content):
                await handleBaraagContent(message, match.group(1))

            for match in re.finditer(r"(?<=https://baraag.net/)@\w+/(\w+)", content):
                await handleBaraagContent(message, match.group(1))    

            for match in re.finditer(r"(?<=https://twitter.com/)(\w+/status/\w+)", content): 
                await handleTwitterVideo(message, match.group(1))

    except Exception as e:
        logging.exception("Exception occurred", exc_info=True)

@bot.event
async def on_raw_reaction_add(payload):
    await handle_reaction(payload)

@bot.event
async def on_raw_reaction_remove(payload):
    await handle_reaction(payload)

# Commands
@bot.command()
@commands.has_permissions(administrator=True)
async def list(ctx):
    embed = discord.Embed(title="Current settings", colour=discord.Colour(0x8ba089))

    for emoji in roles_settings['roles']:
        embed.add_field(name=emoji, value=f"<@&{roles_settings['roles'][emoji]}>")

    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def add(ctx, emoji: str, *, role: discord.Role):
    print(f"{bot.user.name} added: {emoji} -> {role}")
    roles_settings['roles'][emoji] = role.id
    yaml.dump(roles_settings, open(ROLES_SETTINGS, 'w'))
    await ctx.send(f"{bot.user.name} added: {emoji} -> {role}")

@bot.command()
@commands.has_permissions(administrator=True)
async def remove(ctx, emoji: str):
    del roles_settings['roles'][emoji]
    yaml.dump(roles_settings, open(ROLES_SETTINGS, 'w'))
    await ctx.send(f"{bot.user.name} deleted: {emoji}")

if __name__ == '__main__':
    logging.basicConfig(filename='logs/error.log', format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s')

    # Start tiktok thread
    threading.Thread(target=tiktok_worker, daemon=True).start()

    # Main Loop
    bot.run(config['discord']['token'])
