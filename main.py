#!/home/discordbot/sourcebot-env/bin/python3.8
import datetime
import discord
import faapi
import glob
import io
import json
import logging
import os
import pixivapi
import re
import requests
import shlex
import subprocess
import yaml
import xmltodict

from dateutil import tz
from discord.ext import commands
from pprint import pprint
from pathlib import Path
from saucenao_api import SauceNao
from zipfile import ZipFile
from TikTokApi import TikTokApi

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
            f.write(f"[{asctime}] [{message.guild.name}/{message.channel.name}]\n{attachment.url} -> {results[0].urls[0]} ({results[0].similarity}%)\n")
    
    if len(sources) == 0:
        return
    
    source_urls = '\n'.join(sources)
    await message.reply(f"Source(s):\n{source_urls}")


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

async def handlePawooContent(message, submission_id):
    #async with message.channel.typing():
        r = requests.get(f"https://pawoo.net/api/v1/statuses/{submission_id}")
        data = r.json()

        with open(f"media/data/pawoo_{submission_id}.json", 'w') as outfile:
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

        with open(f"media/data/baraag_{submission_id}.json", 'w') as outfile:
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
                    f.write(f"[{asctime}] [{message.guild.name}/{message.channel.name}]\n{short_url}, {url}, size: {size:.2f} MB\n")

                # Check for Discord filesize limit
                if size > 8.0:
                    await message.reply('I\'m sorry but this video is too large for Discord to handle :sob:')
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

@bot.command()
async def now(ctx):
    embed = discord.Embed(title="Current time", colour=discord.Colour(0x8ba089))
    now = datetime.datetime.now()

    for zone in ['US/Pacific', 'US/Central', 'US/Eastern', 'Europe/London', 'Europe/Warsaw', 'Asia/Singapore']:
        embed.add_field(name=zone, value=now.astimezone(tz.gettz(zone)).strftime('%A, %B %-d, %Y, %-I:%M %p'), inline=False)

    await ctx.send(embed=embed)

if __name__ == '__main__':
    logging.basicConfig(filename='logs/error.log', format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s')

    # Main Loop
    bot.run(config['discord']['token'])
