#!/usr/bin/env python3.8
import discord
import faapi
import glob
import os
import pixivapi
import re
import requests
import shlex
import subprocess
import yaml
import xmltodict

from discord.ext import commands
from pprint import pprint
from pathlib import Path
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

# Source fetching functions
async def handlePixivUrl(message, submission_id):
    async with message.channel.typing():
        pixiv = pixivapi.Client()
        pixiv.authenticate(config['pixiv']['token']) 
        # pixiv.login(config['pixiv']['username'], config['pixiv']['password'])

        illustration = pixiv.fetch_illustration(submission_id)

        # Skip safe work
        if illustration.x_restrict == 0:
            return 

        if illustration.x_restrict == 2:
            await message.reply("Please don't post this kind of art on this server. (R-18G)", mention_author=True)
            await message.delete()
            return

        path = None
        if illustration.type == pixivapi.enums.ContentType.UGOIRA:
            busy_message = await message.channel.send("Oh hey, that's an animated one, it will take me a while!")

            # Dealing with UGOIRA file
            # Get file metadata (framges and zip_url)
            metadata = pixiv._request_json(method = "get", url = "https://app-api.pixiv.net/v1/ugoira/metadata", params = {"illust_id": submission_id})

            # Download and extract zip archive
            pixiv.download(metadata['ugoira_metadata']['zip_urls']['medium'], Path(f"./media/{submission_id}.zip"))

            with ZipFile(f"./media/{submission_id}.zip", 'r') as zip_ref:
                zip_ref.extractall(f"./media/{submission_id}/")

            os.remove(f"./media/{submission_id}.zip")

            # Prepare ffmpeg "concat demuxer" file
            with open(f"./media/{submission_id}/ffconcat.txt", 'w') as f:
                for frame in metadata['ugoira_metadata']['frames']:
                    frame_file = frame['file']
                    frame_duration = round(frame['delay'] / 1000, 4)

                    f.write(f"file {frame_file}\nduration {frame_duration}\n")
                f.write(f"file {metadata['ugoira_metadata']['frames'][-1]['file']}")

            if len(metadata['ugoira_metadata']['frames']) > 60:
                ext, ext_params = 'webm', ""
            else:
                ext, ext_params = 'gif', "-vf 'scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse' -loop 0"

            # Run ffmpeg for the given file/directory
            subprocess.call(
                shlex.split(f"ffmpeg -loglevel fatal -hide_banner -y -f concat -i {submission_id}/ffconcat.txt {ext_params} {submission_id}.{ext}"),
                cwd=os.path.abspath(f"./media/")
            )

            # Remove source files
            for name in os.listdir(f"./media/{submission_id}/"):
                os.remove(f"./media/{submission_id}/{name}")
            os.rmdir(f"./media/{submission_id}/")

            path = f"./media/{submission_id}.{ext}"

            # Delete information about dealing with longer upload
            await busy_message.delete()

        else:
            # Normal download method
            illustration.download(Path('./media/'))

            # Deal with multiple page submissions
            if illustration.page_count == 1:
                path = glob.glob(f'./media/{submission_id}.*')[0]
            else:
                path = glob.glob(f'./media/{submission_id}/{submission_id}_p0.*')[0]

    await message.channel.send(content=f'{illustration.title} by {illustration.user.name}', file=discord.File(path))

async def handleInkbunnyUrl(message, submission_id):
    async with message.channel.typing():
        # Log in to API and get session ID
        r = requests.get(f"https://inkbunny.net/api_login.php?username={config['inkbunny']['username']}&password={config['inkbunny']['password']}")
        data = r.json()
        session = data['sid']

        # Request information about the submission
        r = requests.get(f'https://inkbunny.net/api_submissions.php?sid={session}&submission_ids={submission_id}')
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
        if 'young' not in post['tags']['general'] and post['tags']['rating'] != 'e':
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

async def handleBaraagContent(message, submission_id):
    async with message.channel.typing():
        r = requests.get(f"https://baraag.net/api/v1/statuses/{submission_id}")
        data = r.json()

        # Skip statuses without media attachments
        if 'media_attachments' not in data:
            return

        embed = discord.Embed(title=f"Picture by {data['account']['display_name']}", color=discord.Color(0xFAAF3A))
        embed.set_image(url=data['media_attachments'][0]['url'])

    await message.channel.send(embed=embed)

# Events 
@bot.event
async def on_ready():
    print(f"The great and only {bot.user.name} has connected to Discord!")

@bot.event 
async def on_message(message):
    if message.author == bot.user:
        return

    if not isinstance(message.channel, discord.DMChannel) and message.channel.id not in config['discord']['art_channels']:
        return

    for match in re.finditer(r"(?<=https://www.pixiv.net/en/artworks/)(\w+)", message.content):
        await handlePixivUrl(message, match.group(1))

    for match in re.finditer(r"(?<=https://inkbunny.net/s/)(\w+)", message.content):
        await handleInkbunnyUrl(message, match.group(1))

    for match in re.finditer(r"(?<=https://www.furaffinity.net/view/)(\w+)", message.content):
        await handleFuraffinityUrl(message, match.group(1))

    for match in re.finditer(r"(?<=https://e621.net/posts/)(\w+)", message.content):
        await handleE621Url(message, match.group(1))

    for match in re.finditer(r"(?<=https://rule34.xxx/index.php\?page\=post\&s\=view\&id\=)(\w+)", message.content): # TODO: better regex?
        await handleRule34xxxUrl(message, match.group(1))

    for match in re.finditer(r"(?<=https://baraag.net/web/statuses/)(\w+)", message.content):
        await handleBaraagContent(message, match.group(1))

    for match in re.finditer(r"(?<=https://baraag.net/)@\w+/(\w+)", message.content):
        await handleBaraagContent(message, match.group(1))

    await bot.process_commands(message)

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

# Main Loop
bot.run(config['discord']['token'])
