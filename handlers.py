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
from re import sub
from tempfile import TemporaryDirectory
from time import perf_counter
from zipfile import ZipFile

# Third-party libraries
import aiofiles
import discord
import faapi
import xmltodict
from aiohttp import ClientSession, BasicAuth
from twitter import Twitter
from twitter.oauth import OAuth
from mastodon import Mastodon
from pymongo import MongoClient
from yt_dlp import DownloadError, YoutubeDL

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

                # Move converted file to media path from temporary directory
                os.rename(f"{tmpdir}/{illust_id}.gif", f"{config['media']['path']}/pixiv-{illust_id}.gif")

                embed = discord.Embed(title=f"{data['illust']['title']} by {data['illust']['user']['name']}", color=discord.Color(0x40C2FF))
                embed.set_image(url=f"{config['media']['url']}/pixiv-{illust_id}.gif")
                return [ { 'embed': embed } ]
        else:
            if data['illust']['meta_single_page']:
                urls = [ data['illust']['meta_single_page']['original_image_url'] ]
            else:
                urls = [ url['image_urls']['original'] for url in data['illust']['meta_pages'] ]

            embeds = []
            for index, url in enumerate(urls):
                # Prepare the embed object
                embed = discord.Embed(
                    title=f"{data['illust']['title']} {index + 1}/{len(urls)} by {data['illust']['user']['name']}",
                    color=discord.Color(0x40C2FF)
                )

                ext = os.path.splitext(url)[1]
                async with session.get(url) as response:
                    with open(f"{config['media']['path']}/pixiv-{illust_id}_{index}{ext}", 'wb') as file:
                        file.write(await response.read())

                    embed.set_image(url=f"{config['media']['url']}/pixiv-{illust_id}_{index}{ext}")
                    embeds.append(embed)

    # Parse and embed all files
    return [ { 'embeds': embeds[i:i+10] } for i in range(0, len(embeds), 10) ]

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

    # Skip source for already embeded posts
    if kwargs['message'].embeds and kwargs['message'].embeds[0].thumbnail.url is not discord.Embed.Empty:
        return

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

    embed = discord.Embed(title=f"Picture by {post['tags']['artist'][0]}", color=discord.Color(0x00549E))
    embed.set_image(url=post['sample']['url'])
    return [ { 'embed': embed } ]

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
    return [ { 'embed': embed } ]

async def booru(**kwargs):
    '''
    Hander for booru sites (rule34.xxx, gelbooru.com)
    '''
    # URL and ID from params
    page_url = kwargs['match'].group(1)
    post_id = kwargs['match'].group(2)

    # Skip source for already embeded posts
    if kwargs['message'].embeds and kwargs['message'].embeds[0].thumbnail.url is not discord.Embed.Empty:
        return

    async with ClientSession() as session:
        async with session.get(f"https://{page_url}/index.php?page=dapi&s=post&q=index&id={post_id}") as response:
            data = xmltodict.parse(await response.text())

    url = data['posts']['post']['@file_url'] if '@file_url' in data['posts']['post'] else data['posts']['post']['file_url']

    embed = discord.Embed(color=discord.Color(0xABE5A4))
    embed.set_image(url=url)
    return [ { 'embed': embed } ]

async def deviantart(**kwargs):
    '''
    Handler for deviantart.com
    '''
    # Post URL from params
    url = kwargs['match'].group(1)

    if not kwargs['message'].embeds:
        async with ClientSession() as session:
            async with session.get(f"https://backend.deviantart.com/oembed?url={url}") as response:
                data = await response.json()

        embed = discord.Embed(color=discord.Color(0xABE5A4))
        embed.set_image(url=data['url'])
        return [ { 'embed': embed } ]

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

    if page_url == 'baraag.net':
        # Code used to setup the app/access to account:
        # Mastodon.create_app('baraag_sourcebot', api_base_url = 'https://baraag.net', to_file = 'config/baraag_clientcred.secret')
        # mastodon = Mastodon(client_id = 'config/baraag_clientcred.secret')
        # mastodon.log_in('email', 'password', to_file = 'config/baraag_usercred.secret')

        # Alternative data source for baraag
        try:
            await kwargs['message'].edit(suppress=True)
            del kwargs['message'].embeds[0]
        except IndexError:
            pass

        baraag_api = Mastodon(access_token = 'code/config/baraag_usercred.secret')
        data = baraag_api.status(post_id)

    # Skip statuses without media attachments
    if 'media_attachments' not in data:
        return

    # Skip source for already embeded posts
    if kwargs['message'].embeds and kwargs['message'].embeds[0].thumbnail.url is not discord.Embed.Empty:
        return

    # Parse and embed all files
    embeds = []
    for attachment in data['media_attachments']:
        embed = discord.Embed(title=f"Picture by {data['account']['display_name']}", color=discord.Color(0x191B22))
        embed.set_image(url=attachment['url'])
        embeds.append(embed)
    return [ { 'embeds': embeds[i:i+10] } for i in range(0, len(embeds), 10) ]

async def twitter_ffmpeg(partial_url, tweet_type):
    '''
    Helper for twitter functionality, downloading twitter gifs & videos
    '''
    # Tweet ID from URL
    tweet_id = partial_url.split('/')[-1]

    with TemporaryDirectory() as tmpdir:
        try:
            with YoutubeDL({'format': 'best', 'quiet': True, 'extract_flat': True, 'outtmpl': f"{tmpdir}/{tweet_id}.%(ext)s"}) as ydl:
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
                else:
                    raise Exception('Unsupported code called, twitter video should be parsed by new API method')

                if os.stat(f"{tmpdir}/{filename}").st_size > 8388608: # 8M
                    os.rename(f"{tmpdir}/{filename}", f"{config['media']['path']}/tweet-{filename}")
                    return [ { 'content': f"{config['media']['url']}/tweet-{filename}"} ]

                with open(f"{tmpdir}/{filename}", 'rb') as file:
                    return [ { 'file': discord.File(file, filename=filename) } ]
                
        except DownloadError as e:
            print('ytdl download failed')

async def twitter(**kwargs):
    '''
    Hander for twitter.com
    '''
    # Tweet ID from URL
    tweet_path = kwargs['match'].group(1)
    tweet_id = tweet_path.split('/')[-1]

    # Twitter API call for NSFW videos parsing
    api = Twitter(auth=OAuth(
            config['twitter']['access_token'],
            config['twitter']['access_token_secret'],
            config['twitter']['api_key'],
            config['twitter']['api_key_secret']
        )
    )
    tweet = api.statuses.show(_id=tweet_id, tweet_mode="extended")

    ret = []
    for media in tweet['extended_entities']['media']:
        if media['type'] == 'video':
            variants = sorted(filter(lambda k: k['content_type'] == 'video/mp4', media['video_info']['variants']), key=lambda k: k['bitrate'], reverse = True)
            ret.append({ 'content' : f"{variants[0]['url']}"})
    
    if ret:
        return ret

    # "Legacy" method, http api call
    async with ClientSession() as session:
        session.headers.update({'Authorization': f"Bearer {config['twitter']['token']}"})
        async with session.get(f"https://api.twitter.com/2/tweets/{tweet_id}?expansions=attachments.media_keys,author_id&media.fields=type,url") as response:
            tweet_data = await response.json()

            if 'includes' not in tweet_data or 'media' not in tweet_data['includes']:
                return

            if tweet_data['includes']['media'][0]['type'] == 'video' or tweet_data['includes']['media'][0]['type'] == 'animated_gif':
                return await twitter_ffmpeg(tweet_path, tweet_data['includes']['media'][0]['type'])

            if not kwargs['message'].embeds:
                username = tweet_data['includes']['users'][0]['username']
                embeds = []
                for index, file in enumerate(tweet_data['includes']['media']):
                    embed = discord.Embed(title=f"Picture {index + 1}/{len(tweet_data['includes']['media'])} by {username}", color=discord.Color(0x1DA1F2))
                    embed.set_image(url=file['url'])
                    embeds.append(embed)
                return [ { 'embeds': embeds[i:i+10] } for i in range(0, len(embeds), 10) ]

def tiktok_parseurl(url):
    '''
    Helper function for tiktok handler that returns downloadable video
    '''
    with YoutubeDL() as ydl:
        videoInfo = ydl.extract_info(url, download=False)

        for format in videoInfo['formats']:
            if format['format_id'] == 'download_addr-0':
                return format

        # not found, search for the next best one
        for format in videoInfo['formats']:
            if format['url'].startswith('http://api'):
                return format

        # not found, return the first one
        return videoInfo['formats'][0]

async def tiktok(**kwargs):
    '''
    Handler for tiktok
    '''
    # Tiktok URL from params
    message_url = kwargs['match'].group(1)
    print(f"{message_url=}")
    async with ClientSession() as session:
        # Fetch tiktok_id
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/109.0'
        })
        async with session.get(message_url, allow_redirects=True) as response:
            url = str(response.url).split('?', maxsplit=1)[0] # remove all the junk in query data

        tiktok_id = url.split('/')[-1]

        # Prepare mongodb connection
        client = MongoClient("mongodb://127.0.0.1/sourcebot")
        cached_data = client['sourcebot']['tiktok_db'].find_one({
            'tiktok_id': int(tiktok_id)
        })

        print(f"{cached_data=}")
        if not cached_data:
            tiktok_video_url = tiktok_parseurl(url)['url']

            print(f"{tiktok_video_url=}")
            with TemporaryDirectory() as tmpdir:
                perf_count = perf_counter()
                async with aiofiles.open(f"{tmpdir}/{tiktok_id}", "wb") as file, session.get(tiktok_video_url) as response:
                    await file.write(await response.read())
                    args = shlex.split(
                        f"ffmpeg -loglevel fatal -hide_banner -y -i {tiktok_id} "
                        "-c:v libx264 -preset medium -crf 23 -c:a aac -b:a 128k "
                        f"tiktok-{tiktok_id}.mp4"
                    )
                    ffmpeg = await asyncio.create_subprocess_exec(*args, cwd=os.path.abspath(tmpdir))
                    await ffmpeg.wait()

                    os.rename(f"{tmpdir}/tiktok-{tiktok_id}.mp4", f"{config['media']['path']}/tiktok-{tiktok_id}.mp4")
                    perf_count = perf_counter() - perf_count
                    print(f"{perf_count=}s")

            client['sourcebot']['tiktok_db'].insert_one({
                'tiktok_id': int(tiktok_id),
                'size': os.stat(f"{config['media']['path']}/tiktok-{tiktok_id}.mp4").st_size
            })

    return [ { 'content': f"{config['media']['url']}/tiktok-{tiktok_id}.mp4" } ]

async def reddit(**kwargs):
    '''
    Handler for reddit
    '''
    async with ClientSession() as session:
        async with session.get(kwargs['match'].group(1) + '.json') as response:
            data_raw = await response.json()
            data = data_raw[0]['data']['children'][0]['data']
            unique_id = data['subreddit_id'] + data['id']
            video_url = data['secure_media']['reddit_video']['fallback_url']
            audio_url = sub(r'DASH_[0-9]+\.', 'DASH_audio.', video_url)

            print(unique_id, video_url, audio_url)

            with TemporaryDirectory() as tmpdir:
                async with session.get(video_url) as video, session.get(audio_url) as audio:
                    async with aiofiles.open(f"{tmpdir}/video.mp4", 'wb') as video_f, aiofiles.open(f"{tmpdir}/audio.mp4", 'wb') as audio_f:
                        await video_f.write(await video.read())
                        await audio_f.write(await audio.read())

                args = shlex.split(
                    'ffmpeg -loglevel fatal -hide_banner -y -i video.mp4 -i audio.mp4 -c:v copy -c:a aac output.mp4'
                )
                ffmpeg = await asyncio.create_subprocess_exec(*args, cwd=os.path.abspath(tmpdir))
                await ffmpeg.wait()

                os.rename(f"{tmpdir}/output.mp4", f"{config['media']['path']}/reddit-{unique_id}.mp4")

    return [ { 'content': f"{config['media']['url']}/reddit-{unique_id}.mp4" } ]

async def youtube(**kwargs):
    '''
    Youtube downloading via url
    '''
    # Youtube video path from params
    video = kwargs['match'].group(1)

    # Only trigger this for direct messages
    if not isinstance(kwargs['message'].channel, discord.DMChannel):
        return

    # Download video to temporary directory
    with TemporaryDirectory() as tmpdir:
        with YoutubeDL({'format': 'best', 'quiet': True, 'extract_flat': True, 'outtmpl': f"{tmpdir}/{video}.%(ext)s"}) as ydl:
            meta = ydl.extract_info(f"https://youtube.com/watch?v={video}")
            filename = f"{video}.{meta['ext']}"

            os.rename(f"{tmpdir}/{filename}", f"{config['media']['path']}/youtube-{filename}")
            return [ { 'content': f"{config['media']['url']}/youtube-{filename}"} ]

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
