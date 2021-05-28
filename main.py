#!/home/discordbot/sourcebot-env/bin/python3.8
# -*- coding: utf-8 -*-

import datetime
import discord
import faapi
import hashlib
import io
import json
import logging
import os
import re
import requests
import shlex
import subprocess
import xmltodict
import yaml

from dateutil import tz
from discord.ext import commands
from saucenao_api import SauceNao
from tempfile import TemporaryDirectory
from TikTokApi import TikTokApi
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

# Role reactions
async def handle_reaction(payload):
    # Check if reaction was added/removed in the right channel
    channel = bot.get_channel(payload.channel_id)
    if not channel.name == config['discord']['role_channel']:
        return

    # Parse emoji as string (works for custom emojis and unicode)
    emoji = str(payload.emoji)

    # Fetch message and and member
    message = await channel.fetch_message(payload.message_id)
    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)

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

async def provideSources(message): 
    sauce = SauceNao(config['saucenao']['token'])
    sources = []

    for attachment in message.attachments:
        results = sauce.from_url(attachment.url)

        # for result in results:
        #     pprint(result)
        #     pprint(result.urls)

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

# Source fetching functions
async def handlePixivUrl(message, submission_id):
    async with message.channel.typing():
        # Prepare Access Token
        session = requests.session()
        session.headers.update(HEADERS)
        client_time = datetime.datetime.utcnow().replace(microsecond=0).replace(tzinfo=datetime.timezone.utc).isoformat()

        # Authenticate using Refresh token
        response = session.post(
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
        )
        data = response.json()
        session.headers.update({"Authorization": f"Bearer {data['access_token']}"})

        # Get Illustration details
        response = session.get(
            url = f"{BASE_URL}/v1/illust/detail",
            params = { "illust_id": submission_id },
        )
        data = response.json()
        session.headers.update({"Referer": f"https://www.pixiv.net/member_illust.php?mode=medium&illust_id={submission_id}"})

        # Skip safe work
        if data['illust']['x_restrict'] == 0:
            return 

        if data['illust']['x_restrict'] == 2:
            await message.reply("Please don't post this kind of art on this server. (R-18G)", mention_author=True)
            await message.delete()
            return

        # Prepare the embed object
        embed = discord.Embed(title=f"{data['illust']['title']} by {data['illust']['user']['name']}", color=discord.Color(0x40C2FF))

        if data['illust']['type'] == 'ugoira':
            busy_message = await message.channel.send("Oh hey, that's an animated one, it will take me a while!")

            # Get file metadata (framges and zip_url)
            response = session.get(
                url = f"{BASE_URL}/v1/ugoira/metadata",
                params = { "illust_id": submission_id },
            )
            data = response.json()

            # Download and extract zip archive to temporary directory
            with TemporaryDirectory() as tmpdir:
                with session.get(data['ugoira_metadata']['zip_urls']['medium'], stream=True) as r:
                    with ZipFile(io.BytesIO(r.content), 'r') as zip_ref: 
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
            with session.get(url, stream=True) as r:
                file = discord.File(io.BytesIO(r.content), filename=f"{submission_id}.{ext}")
                embed.set_image(url=f"attachment://{submission_id}.{ext}")

    await message.channel.send(embed=embed, file=file)

async def handleInkbunnyUrl(message, submission_id):
    async with message.channel.typing():
        # Log in to API and get session ID
        r = requests.get(f"https://inkbunny.net/api_login.php?username={config['inkbunny']['username']}&password={config['inkbunny']['password']}")
        data = r.json()
        session = data['sid']

        # Request information about the submission
        r = requests.get(f"https://inkbunny.net/api_submissions.php?sid={session}&submission_ids={submission_id}")
        data = r.json()

        if len(data['submissions']) != 1:
            return

        # Get image url and send it
        submission = data['submissions'][0]

        embed = discord.Embed(title=f"{submission['title']} by {submission['username']}", color=discord.Color(0xFCE4F1))
        embed.set_image(url=submission['file_url_full'])

    await message.channel.send(embed=embed)

async def handleE621Url(message, submission_id):
    async with message.channel.typing():
        headers = {
            'User-Agent': f"{bot.user.name} by {config['e621']['username']}"
        }

        # Get image data using API Endpoint
        r = requests.get(f"https://e621.net/posts/{submission_id}.json", headers=headers, auth=(config['e621']['username'], config['e621']['api_key']))
        data = r.json()
        post = data['post']

        # Check for global blacklist (ignore other links as they already come with previews)
        if 'young' not in post['tags']['general'] or post['rating'] != 'e':
            return
        
        embed = discord.Embed(title=f"Picture by {post['tags']['artist'][0]}", color=discord.Color(0x00549E))
        embed.set_image(url=post['sample']['url'])

    await message.channel.send(embed=embed)

async def handleFuraffinityUrl(message, submission_id):
    async with message.channel.typing():
        cookies = [
            {"name": "a", "value": config['furaffinity']['cookie']['a']},
            {"name": "b", "value": config['furaffinity']['cookie']['b']},
        ]

        api = faapi.FAAPI(cookies)
        submission, _ = api.get_submission(submission_id)

        if submission.rating == 'General':
            return

        embed = discord.Embed(title=f"{submission.title} by {submission.author}", color=discord.Color(0xFAAF3A))
        embed.set_image(url=submission.file_url)

    await message.channel.send(embed=embed)

async def handleRule34xxxUrl(message, submission_id):
    async with message.channel.typing(): 
        r = requests.get(f"https://rule34.xxx/index.php?page=dapi&s=post&q=index&id={submission_id}")
        data = xmltodict.parse(r.text)

        embed = discord.Embed(color=discord.Color(0xABE5A4)) # TODO: Title? Maybe try to use source from the webiste if provided for other handers?
        embed.set_image(url=data['posts']['post']['@file_url'])

    await message.channel.send(embed=embed)

async def handlePawooContent(message, submission_id):
    #async with message.channel.typing():
        r = requests.get(f"https://pawoo.net/api/v1/statuses/{submission_id}")
        data = r.json()

        with open(f"logs/pawoo_{submission_id}.json", 'w') as outfile:
            json.dump(data, outfile)

        # Skip statuses without media attachments
        if 'media_attachments' not in data:
            return

        embed = discord.Embed(title=f"Picture by {data['account']['display_name']}", color=discord.Color(0xFAAF3A))
        embed.set_image(url=data['media_attachments'][0]['url'])

    #await message.channel.send(embed=embed)

async def handleBaraagContent(message, submission_id):
    #async with message.channel.typing():
        r = requests.get(f"https://baraag.net/api/v1/statuses/{submission_id}")
        data = r.json()

        with open(f"logs/baraag_{submission_id}.json", 'w') as outfile:
            json.dump(data, outfile)

        # Skip statuses without media attachments
        if 'media_attachments' not in data:
            return

        embed = discord.Embed(title=f"Picture by {data['account']['display_name']}", color=discord.Color(0xFAAF3A))
        embed.set_image(url=data['media_attachments'][0]['url'])

    #await message.channel.send(embed=embed)

# Events 
@bot.event
async def on_ready():
    print(f"The great and only {bot.user.name} has connected to Discord API!")

def tiktokHandler(url):
    api = TikTokApi.get_instance()
    return api.get_video_by_url(url)

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
            for match in re.finditer(r"(?<=https://vm.tiktok.com/)(\w+)", content):
                short_url = 'https://vm.tiktok.com/' + match.group(1)

                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36'}
                s = requests.Session()

                r = s.head(short_url, headers=headers)
                r = s.head(r.headers['Location'], headers=headers)
                url = r.headers['Location'].split('?')[0] # remove all the junk in query data

                data = await bot.loop.run_in_executor(None, tiktokHandler, url)
                size = len(data) / 1048576

                # Log tiktok urls to tiktok.log
                asctime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                with open('logs/tiktok.log', 'a') as f:
                    location = f"{message.author} (dm)" if isinstance(message.channel, discord.DMChannel) else f"{message.guild.name}/{message.channel.name}"
                    f.write(f"[{asctime}] [{location}]\n{short_url}, {url}, size: {size:.2f} MB\n")

                if size == 0:
                    await message.reply('Tiktot returned an empty file, please try again.', delete_after = 20.0)
                    continue

                # Check for Discord filesize limit
                if size > 8.0:
                    await message.reply('I\'m sorry but this video is too large for Discord to handle :sob:', delete_after = 20.0)
                    continue

                await message.reply(file=discord.File(io.BytesIO(data), filename='tiktok-video.mp4'))

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

    # Main Loop
    bot.run(config['discord']['token'])
