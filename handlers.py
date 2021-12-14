'''
Definiton of hander functions for sourcebot.
'''

# Python standard libraries
import asyncio
import datetime
import hashlib
import io
import os
import shlex
from time import perf_counter
from tempfile import TemporaryDirectory
from zipfile import ZipFile

# Third-party libraries
import aiofiles
import discord
import faapi
import xmltodict
import youtube_dl
from aiohttp import ClientSession, BasicAuth

# Local modules
from config import config

# Source fetching
async def pixiv(submission_id):
    '''
    Hander for pixiv.net
    '''
    # Static data for pixiv
    base_url = "https://app-api.pixiv.net"

    # Prepare Access Token
    async with ClientSession() as session:
        session.headers.update({
        "User-Agent": "PixivAndroidApp/5.0.115 (Android 6.0; PixivBot)",
        "Accept-Language": "English"
        })
        client_time = datetime.datetime.utcnow().replace(microsecond=0).replace(tzinfo=datetime.timezone.utc).isoformat()

        # Authenticate using Refresh token
        async with session.post(
            url = "https://oauth.secure.pixiv.net/auth/token",
            data = {
                "client_id": "KzEZED7aC0vird8jWyHM38mXjNTY",
                "client_secret": "W9JZoJe00qPvJsiyCGT3CCtC6ZUtdpKpzMbNlUGP",
                "get_secure_url": 1,
                "grant_type": "refresh_token",
                "refresh_token": config['pixiv']['token']
            },
            headers = {
                "X-Client-Time": client_time,
                "X-Client-Hash": hashlib.md5(
                    (client_time + "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c").encode("utf-8")
                ).hexdigest()
            },
        ) as response:
            data = await response.json()
            session.headers.update({"Authorization": f"Bearer {data['access_token']}"})

        # Get Illustration details
        async with session.get(
            url = f"{base_url}/v1/illust/detail",
            params = { "illust_id": submission_id },
        ) as response:
            data = await response.json()
            session.headers.update({
                "Referer": f"https://www.pixiv.net/member_illust.php?mode=medium&illust_id={submission_id}"
            })

        if data['illust']['type'] == 'ugoira':
            # Get file metadata (framges and zip_url)
            async with session.get(
                url = f"{base_url}/v1/ugoira/metadata",
                params = { "illust_id": submission_id },
            ) as response:
                metadata = await response.json()

            # Download and extract zip archive to temporary directory
            with TemporaryDirectory() as tmpdir:
                async with session.get(metadata['ugoira_metadata']['zip_urls']['medium']) as response:
                    with ZipFile(io.BytesIO(await response.read()), 'r') as zip_ref:
                        zip_ref.extractall(tmpdir)

                # Prepare ffmpeg "concat demuxer" file
                async with aiofiles.open(f"{tmpdir}/ffconcat.txt", 'w') as file:
                    for frame in metadata['ugoira_metadata']['frames']:
                        frame_file = frame['file']
                        frame_duration = round(frame['delay'] / 1000, 4)
                        await file.write(f"file {frame_file}\nduration {frame_duration}\n")

                # Run ffmpeg for the given file/directory
                args = shlex.split(
                    f"ffmpeg -loglevel fatal -hide_banner -y -f concat -i ffconcat.txt "
                    "-vf 'scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse' -loop 0 "
                    f"{submission_id}.gif"
                )
                ffmpeg = await asyncio.create_subprocess_exec(*args, cwd=os.path.abspath(tmpdir))
                await ffmpeg.wait()

                # Prepare attachment file
                embeds, files = [], []
                embed = discord.Embed(title=f"{data['illust']['title']} by {data['illust']['user']['name']}", color=discord.Color(0x40C2FF))
                if os.stat(f"{tmpdir}/{submission_id}.gif").st_size > 8388608: # 8M
                    os.rename(f"{tmpdir}/{submission_id}.gif", f"{config['media']['path']}/pixiv-{submission_id}.gif")
                    embed.set_image(url=f"{config['media']['url']}/pixiv-{submission_id}.gif")
                else:
                    files.append(discord.File(f"{tmpdir}/{submission_id}.gif", filename=f"{submission_id}.gif"))
                    embed.set_image(url=f"attachment://{submission_id}.gif")
                embeds.append(embed)
        else:
            if data['illust']['meta_single_page']:
                urls = [ data['illust']['meta_single_page']['original_image_url'] ]
            else:
                urls = [ url['image_urls']['original'] for url in data['illust']['meta_pages'] ]

            embeds, files = [], []
            for index, url in enumerate(urls):
                # Prepare the embed object
                embed = discord.Embed(title=f"{data['illust']['title']} {index + 1}/{len(urls)} by {data['illust']['user']['name']}", color=discord.Color(0x40C2FF))

                ext = os.path.splitext(url)[1]
                async with session.get(url) as response:
                    files.append(discord.File(io.BytesIO(await response.read()), filename=f"{submission_id}_{index}.{ext}"))
                    embed.set_image(url=f"attachment://{submission_id}_{index}.{ext}")
                    embeds.append(embed)
    return { 'embeds': embeds, 'files': files }

async def inkbunny(submission_id):
    '''
    Hander for inkbunny.net
    '''
    async with ClientSession() as session:
        # Log in to API and get session ID
        async with session.get(f"https://inkbunny.net/api_login.php?username={config['inkbunny']['username']}&password={config['inkbunny']['password']}") as response:
            data = await response.json()
            session_id = data['sid']

        # Request information about the submission
        async with session.get(f"https://inkbunny.net/api_submissions.php?sid={session_id}&submission_ids={submission_id}") as response:
            data = await response.json()

    # Get submission data
    submission = data['submissions'][0]

    # Parse and embed all files
    embeds = []
    for index, file in enumerate(submission['files']):
        embed = discord.Embed(title=f"{submission['title']} {index + 1}/{len(submission['files'])} by {submission['username']}", color=discord.Color(0xFCE4F1))
        embed.set_image(url=file['file_url_screen'])
        embeds.append(embed)
    return { 'embeds': embeds }

async def e621(submission_id):
    '''
    Hander for e621.net
    '''
    async with ClientSession() as session:
        session.headers.update({
            'User-Agent': f"sourcebot by {config['e621']['username']}"
        })

        # Get image data using API Endpoint
        async with session.get(f"https://e621.net/posts/{submission_id}.json", auth=BasicAuth(config['e621']['username'], config['e621']['api_key'])) as response:
            data = await response.json()
            post = data['post']

        # Check for global blacklist (ignore other links as they already come with previews)
        if 'young' not in post['tags']['general'] or post['rating'] == 's':
            return

    embed = discord.Embed(title=f"Picture by {post['tags']['artist'][0]}", color=discord.Color(0x00549E))
    embed.set_image(url=post['sample']['url'])
    return { 'embed': embed }

async def furaffinity(submission_id):
    '''
    Hander for furaffinity.net
    '''
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
    return { 'embed': embed }

async def rule34xxx(submission_id):
    '''
    Hander for rule34.xxx
    '''
    async with ClientSession() as session:
        async with session.get(f"https://rule34.xxx/index.php?page=dapi&s=post&q=index&id={submission_id}") as response:
            data = xmltodict.parse(await response.text())

    embed = discord.Embed(color=discord.Color(0xABE5A4))
    embed.set_image(url=data['posts']['post']['@file_url'])
    return { 'embed': embed }

async def pawoo(submission_id):
    '''
    Hander for pawoo.net
    '''
    async with ClientSession() as session:
        async with session.get(f"https://pawoo.net/api/v1/statuses/{submission_id}") as response:
            data = await response.json()

    # Skip statuses without media attachments
    if 'media_attachments' not in data:
        return

    # Skip account with pawoo.net or artalley.social in profile URL
    if 'pawoo.net' in data['account']['url'] or 'artalley.social' in data['account']['url']:
        return

    embed = discord.Embed(title=f"Picture by {data['account']['display_name']}", color=discord.Color(0xFAAF3A))
    embed.set_image(url=data['media_attachments'][0]['url'])
    return { 'embed': embed }

async def baraag(submission_id):
    '''
    Hander for baraag.net
    '''
    async with ClientSession() as session:
        async with session.get(f"https://baraag.net/api/v1/statuses/{submission_id}") as response:
            data = await response.json()

    # Skip statuses without media attachments
    if 'media_attachments' not in data:
        return

    # Skip account with baraag.net or artalley.social in profile URL
    if 'baraag.net' in data['account']['url'] or 'artalley.social' in data['account']['url']:
        return

    embed = discord.Embed(title=f"Picture by {data['account']['display_name']}", color=discord.Color(0xFAAF3A))
    embed.set_image(url=data['media_attachments'][0]['url'])
    return { 'embed': embed }

async def twitter(submission_id):
    '''
    Hander for twitter.com
    '''
    # Tweet ID from URL
    tweet_id = submission_id.split('/')[-1]
    async with ClientSession() as session:
        session.headers.update({'Authorization': f"Bearer {config['twitter']['token']}"})
        async with session.get(f"https://api.twitter.com/2/tweets/{tweet_id}?expansions=attachments.media_keys&media.fields=type") as response:
            tweet_data = await response.json()

            if 'includes' not in tweet_data:
                return

            if tweet_data['includes']['media'][0]['type'] != 'video' and tweet_data['includes']['media'][0]['type'] != 'animated_gif':
                return

    # Download video to temporary directory
    with TemporaryDirectory() as tmpdir:
        with youtube_dl.YoutubeDL({'format': 'best', 'quiet': True, 'extract_flat': True, 'outtmpl': f"{tmpdir}/{tweet_id}.%(ext)s"}) as ydl:
            try:
                meta = ydl.extract_info(f"https://twitter.com/{submission_id}")
                filename = f"{tweet_id}.{meta['ext']}"
            except Exception:
                print(f"{tweet_id}: ytdl exception, that shouldn't happen..")
                return

            # Convert Animated GIFs to .gif so they loop in Discord
            if tweet_data['includes']['media'][0]['type'] == 'animated_gif':
                args = shlex.split(
                    f"ffmpeg -loglevel fatal -hide_banner -y -i {filename} "
                    "-vf 'scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse' -loop 0 "
                    f"{tweet_id}.gif"
                )
                ffmpeg = await asyncio.create_subprocess_exec(*args, cwd=os.path.abspath(tmpdir))
                await ffmpeg.wait()
                filename = f"{tweet_id}.gif"

            if os.stat(f"{tmpdir}/{filename}").st_size > 8388608: # 8M
                os.rename(f"{tmpdir}/{filename}", f"{config['media']['path']}/tweet-{filename}")
                return { 'content': f"{config['media']['url']}/tweet-{filename}"}

            with open(f"{tmpdir}/{filename}", 'rb') as file:
                return { 'file': discord.File(file, filename=filename) }

# File converter
async def convert(filename, url):
    '''
    ffmpeg media converter for .mp4 and .webm
    '''
    with TemporaryDirectory() as tmpdir:
        init_time = perf_counter()
        async with ClientSession() as session, session.get(url) as response:
            async with aiofiles.open(f"{tmpdir}/{filename}", "wb") as file:
                await file.write(await response.read())
                args = shlex.split(
                    f"ffmpeg -loglevel fatal -hide_banner -y -i {filename} "
                    "-c:v libx264 -preset medium -crf 23 -c:a aac -b:a 128k "
                    f"discord-{filename}"
                )
                ffmpeg = await asyncio.create_subprocess_exec(*args, cwd=os.path.abspath(tmpdir))
                await ffmpeg.wait()
                filename = f"discord-{filename}"

                os.rename(f"{tmpdir}/{filename}", f"{config['media']['path']}/{filename}")
                return { 'content': f"Converted {filename} to x264 in {perf_counter() - init_time:.2f}s\n{config['media']['url']}/{filename}" }
