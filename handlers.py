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
from random import choices, randint
from tempfile import TemporaryDirectory
from time import perf_counter, time_ns
from zipfile import ZipFile

# Third-party libraries
import aiofiles
import discord
import faapi
import xmltodict
import youtube_dl
from aiohttp import ClientSession, BasicAuth
from pymongo import MongoClient


# Local modules
from config import config

# Source fetching
async def pixiv(**kwargs):
    '''
    Hander for pixiv.net
    '''
    # Static data for pixiv
    base_url = "https://app-api.pixiv.net"

    # Illustration ID from params
    illust_id = kwargs['match'].group(1)

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
            params = { "illust_id": illust_id },
        ) as response:
            data = await response.json()
            session.headers.update({
                "Referer": f"https://www.pixiv.net/member_illust.php?mode=medium&illust_id={illust_id}"
            })

        if data['illust']['type'] == 'ugoira':
            # Get file metadata (framges and zip_url)
            async with session.get(
                url = f"{base_url}/v1/ugoira/metadata",
                params = { "illust_id": illust_id },
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
                    f"{illust_id}.gif"
                )
                ffmpeg = await asyncio.create_subprocess_exec(*args, cwd=os.path.abspath(tmpdir))
                await ffmpeg.wait()

                # Prepare attachment file
                embeds, files = [], []
                embed = discord.Embed(title=f"{data['illust']['title']} by {data['illust']['user']['name']}", color=discord.Color(0x40C2FF))
                if os.stat(f"{tmpdir}/{illust_id}.gif").st_size > 8388608: # 8M
                    os.rename(f"{tmpdir}/{illust_id}.gif", f"{config['media']['path']}/pixiv-{illust_id}.gif")
                    embed.set_image(url=f"{config['media']['url']}/pixiv-{illust_id}.gif")
                else:
                    files.append(discord.File(f"{tmpdir}/{illust_id}.gif", filename=f"{illust_id}.gif"))
                    embed.set_image(url=f"attachment://{illust_id}.gif")
                embeds.append(embed)
        else:
            if data['illust']['meta_single_page']:
                urls = [ data['illust']['meta_single_page']['original_image_url'] ]
            else:
                urls = [ url['image_urls']['original'] for url in data['illust']['meta_pages'] ]

            embeds, files = [], []
            for index, url in enumerate(urls):
                # Prepare the embed object
                embed = discord.Embed(
                    title=f"{data['illust']['title']} {index + 1}/{len(urls)} by {data['illust']['user']['name']}",
                    color=discord.Color(0x40C2FF)
                )

                ext = os.path.splitext(url)[1]
                async with session.get(url) as response:
                    files.append(discord.File(io.BytesIO(await response.read()), filename=f"{illust_id}_{index}.{ext}"))
                    embed.set_image(url=f"attachment://{illust_id}_{index}.{ext}")
                    embeds.append(embed)

    # Parse and embed all files
    return [ { 'embeds': embeds[i:i+10], 'files': files[i:i+10] } for i in range(0, len(embeds), 10) ]

async def inkbunny(**kwargs):
    '''
    Hander for inkbunny.net
    '''
    # Submission ID from params
    submission_id = kwargs['match'].group(1)

    async with ClientSession() as session:
        # Log in to API and get session ID
        async with session.get("https://inkbunny.net/api_login.php",
                params = { 'username': config['inkbunny']['username'], 'password': config['inkbunny']['password'] }
            ) as response:
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
    return [ { 'embeds': embeds[i:i+10] } for i in range(0, len(embeds), 10) ]

async def e621(**kwargs):
    '''
    Hander for e621.net
    '''
    # Post ID from params
    post_id = kwargs['match'].group(1)

    async with ClientSession(auth = BasicAuth(config['e621']['username'], config['e621']['api_key'])) as session:
        session.headers.update({
            'User-Agent': f"sourcebot by {config['e621']['username']}"
        })

        # Get image data using API Endpoint
        async with session.get(f"https://e621.net/posts/{post_id}.json") as response:
            data = await response.json()
            post = data['post']

        # Check for global blacklist (ignore other links as they already come with previews)
        if 'young' not in post['tags']['general'] or post['rating'] == 's':
            return

    embed = discord.Embed(title=f"Picture by {post['tags']['artist'][0]}", color=discord.Color(0x00549E))
    embed.set_image(url=post['sample']['url'])
    return { 'embed': embed }

async def e621_pools(**kwargs):
    '''
    Hander for e621.net pools (galleries)
    '''
    # Pool ID from params
    pool_id = kwargs['match'].group(1)

    # Parse and embed all files
    embeds = []
    async with ClientSession(auth = BasicAuth(config['e621']['username'], config['e621']['api_key'])) as session:
        session.headers.update({
            'User-Agent': f"sourcebot by {config['e621']['username']}"
        })

        # Get image data using API Endpoint
        async with session.get(f"https://e621.net/pools/{pool_id}.json") as response:
            pool_data = await response.json()

            for index, submission_id in enumerate(pool_data['post_ids']):
                async with session.get(f"https://e621.net/posts/{submission_id}.json") as response:
                    data = await response.json()
                    post = data['post']

                embed = discord.Embed(
                    title=f"{pool_data['name']} {index + 1}/{pool_data['post_count']} by {pool_data['creator_name']}",
                    color=discord.Color(0x00549E)
                )
                embed.set_image(url=post['sample']['url'])
                embeds.append(embed)

    return [ { 'embeds': embeds[i:i+10] } for i in range(0, len(embeds), 10) ]

async def furaffinity(**kwargs):
    '''
    Hander for furaffinity.net
    '''
    # Submission ID from params
    submission_id = kwargs['match'].group(1)

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

async def booru(**kwargs):
    '''
    Hander for booru sites (rule34.xxx, gelbooru.com)
    '''
    # URL and ID from params
    page_url = kwargs['match'].group(1)
    post_id = kwargs['match'].group(2)

    if not kwargs['embeds'] or kwargs['embeds'][0].type == 'article':
        return

    async with ClientSession() as session:
        async with session.get(f"https://{page_url}/index.php?page=dapi&s=post&q=index&id={post_id}") as response:
            data = xmltodict.parse(await response.text())

    url = data['posts']['post']['@file_url'] if '@file_url' in data['posts']['post'] else data['posts']['post']['file_url']

    embed = discord.Embed(color=discord.Color(0xABE5A4))
    embed.set_image(url=url)
    return { 'embed': embed }

async def deviantart(**kwargs):
    '''
    Handler for deviantart.com
    '''
    # Post URL from params
    url = kwargs['match'].group(1)

    if not kwargs['embeds']:
        async with ClientSession() as session:
            async with session.get(f"https://backend.deviantart.com/oembed?url={url}") as response:
                data = await response.json()

        embed = discord.Embed(color=discord.Color(0xABE5A4))
        embed.set_image(url=data['url'])
        return { 'embed': embed }

async def mastodon(**kwargs):
    '''
    Hander for mastodon (baraag.net, pawoo.net)
    '''

    # URL and ID from params
    page_url = kwargs['match'].group(1)
    post_id = kwargs['match'].group(2)

    async with ClientSession() as session:
        async with session.get(f"https://{page_url}/api/v1/statuses/{post_id}") as response:
            data = await response.json()

    # Skip statuses without media attachments
    if 'media_attachments' not in data:
        return

    if not kwargs['embeds'] or kwargs['embeds'][0].type == 'article':
        return

    embed = discord.Embed(title=f"Picture by {data['account']['display_name']}", color=discord.Color(0xFAAF3A))
    embed.set_image(url=data['media_attachments'][0]['url'])
    return { 'embed': embed }

async def twitter_ffmpeg(partial_url, tweet_type):
    '''
    Helper for twitter functionality, downloading twitter gifs & videos
    '''
    # Tweet ID from URL
    tweet_id = partial_url.split('/')[-1]

    with TemporaryDirectory() as tmpdir:
        with youtube_dl.YoutubeDL({'format': 'best', 'quiet': True, 'extract_flat': True, 'outtmpl': f"{tmpdir}/{tweet_id}.%(ext)s"}) as ydl:
            meta = ydl.extract_info(f"https://twitter.com/{partial_url}")
            filename = f"{tweet_id}.{meta['ext']}"

            # Convert Animated GIFs to .gif so they loop in Discord
            if tweet_type == 'animated_gif':
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

async def twitter(**kwargs):
    '''
    Hander for twitter.com
    '''
    # Tweet ID from URL
    tweet_path = kwargs['match'].group(1)
    tweet_id = tweet_path.split('/')[-1]

    async with ClientSession() as session:
        session.headers.update({'Authorization': f"Bearer {config['twitter']['token']}"})
        async with session.get(f"https://api.twitter.com/2/tweets/{tweet_id}?expansions=attachments.media_keys,author_id&media.fields=type,url") as response:
            tweet_data = await response.json()

            if 'includes' not in tweet_data or 'media' not in tweet_data['includes']:
                return

            if tweet_data['includes']['media'][0]['type'] == 'video' or tweet_data['includes']['media'][0]['type'] == 'animated_gif':
                return await twitter_ffmpeg(tweet_path, tweet_data['includes']['media'][0]['type'])

            if not kwargs['embeds']:
                username = tweet_data['includes']['users'][0]['username']
                embeds = []
                for index, file in enumerate(tweet_data['includes']['media']):
                    embed = discord.Embed(title=f"Picture {index + 1}/{len(tweet_data['includes']['media'])} by {username}", color=discord.Color(0x1DA1F2))
                    embed.set_image(url=file['url'])
                    embeds.append(embed)
                return [ { 'embeds': embeds[i:i+10] } for i in range(0, len(embeds), 10) ]

async def tiktok(**kwargs):
    '''
    Handler for tiktok
    '''
    # Tiktok URL from params
    message_url = kwargs['match'].group(1)

    async with ClientSession() as session:
        # Fetch tiktok_id
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:99.0) Gecko/20100101 Firefox/99.0'
        })
        async with session.head(message_url, allow_redirects=True) as response:
            url = str(response.url).split('?', maxsplit=1)[0] # remove all the junk in query data

        tiktok_id = url.split('/')[-1]

        # Prepare mongodb connection
        client = MongoClient("mongodb://127.0.0.1/sourcebot")
        cached_data = client['sourcebot']['tiktok_db'].find_one({
            'tiktok_id': int(tiktok_id)
        })

        if not cached_data:
            print(f'[debug]: tiktok -> cache not found for {tiktok_id}, fetching')
            time = time_ns()
            params = {
                'aweme_id': tiktok_id, 'region': 'US', 'sys_region': 'US', 'op_region': 'US',
                'ts' : int(time / 1000000000), '_rticket': int(time / 1000000), 'timezone_name': "Etc%2FGMT", 'timezone_offset': 0,
                'device_type': "Pixel%20" + "".join(choices('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', k=8)),
                'iid': randint(6000000000000000000, 7000000000000000000), 'device_id': randint(6000000000000000000, 7000000000000000000),
                'locale': 'en', 'app_language': 'en', 'language': 'en', 'resolution': '1080*1920', 'version_code': 100000, 'dpi': 441,
                'cpu_support64': '0', 'pass-route': 1, 'pass-region': 1, 'app_type': 'normal', 'aid': 1180, 'app_name': 'musical_ly',
                'device_platform': 'android', 'device_brand': 'google', 'os_version': '8.0.0', 'channel': 'googleplay'
            }

            session.headers.update({
                'User-Agent': 'okhttp'
            })
            async with session.get('https://api-t2.tiktokv.com/aweme/v1/aweme/detail/', params=params) as response:
                data = await response.json()

            with open(f"{config['media']['path']}/tiktok-{tiktok_id}.mp4", 'wb') as file:
                async with session.get(data['aweme_detail']['video']['play_addr']['url_list'][0]) as response:
                    file.write(await response.read())

            client['sourcebot']['tiktok_db'].insert_one({
                'tiktok_id': int(tiktok_id),
                'size': os.stat(f"{config['media']['path']}/tiktok-{tiktok_id}.mp4").st_size
            })

    return { 'content': f"{config['media']['url']}/tiktok-{tiktok_id}.mp4" }

async def youtube(**kwargs):
    '''
    Youtube downloading via url
    '''
    # Youtube video path from params
    video = kwargs['match'].group(1)

    # Only trigger this for direct messages
    if not kwargs['is_dm']:
        return

    # Download video to temporary directory
    with TemporaryDirectory() as tmpdir:
        with youtube_dl.YoutubeDL({'format': 'best', 'quiet': True, 'extract_flat': True, 'outtmpl': f"{tmpdir}/{video}.%(ext)s"}) as ydl:
            meta = ydl.extract_info(f"https://youtube.com/watch?v={video}")
            filename = f"{video}.{meta['ext']}"

            os.rename(f"{tmpdir}/{filename}", f"{config['media']['path']}/youtube-{filename}")
            return { 'content': f"{config['media']['url']}/youtube-{filename}"}


# Video files converter
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
