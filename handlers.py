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
import shutil
from re import sub, search
from tempfile import TemporaryDirectory
from time import perf_counter
from zipfile import ZipFile

# Third-party libraries
import aiofiles
import discord
import faapi
import xmltodict
from aiohttp import ClientSession, BasicAuth, ContentTypeError
from pymongo import MongoClient
from yt_dlp import YoutubeDL

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
                shutil.move(f"{tmpdir}/{illust_id}.gif", f"{config['media']['path']}/pixiv-{illust_id}.gif")

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
    page = kwargs['match'].group(2)

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
    if page:
        page_id = int(page)
        embed = discord.Embed(title=f"{submission['title']} (image {page_id} out of {len(submission['files'])}) by {submission['username']}", color=discord.Color(0xFCE4F1))
        embed.set_image(url=submission['files'][page_id - 1]['file_url_screen'])
        return [ { 'embed': embed } ]
    else:
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
    files = []
    async with ClientSession(auth = BasicAuth(config['e621']['username'], config['e621']['api_key'])) as session:
        session.headers.update({
            'User-Agent': f"sourcebot by {config['e621']['username']}"
        })

        # Get image data using API Endpoint
        async with session.get(f"https://e621.net/pools/{pool_id}.json") as response:
            pool_data = await response.json()
    
            for submission_id in pool_data['post_ids']:
                async with session.get(f"https://e621.net/posts/{submission_id}.json") as response:
                    data = await response.json()
                    post = data['post']
        
                    path = f"{config['media']['path']}/e6-{post['file']['md5']}.{post['file']['ext']}"

                    if not os.path.exists(path):
                        async with session.get(post['file']['url']) as response, aiofiles.open(path, "wb") as file:
                            await file.write(await response.read())    

                    files.append(path)
    return files

async def cohost(**kwargs):
    '''
    Hander for cohost.org
    '''
    cohost_url = kwargs['match'].group(1)

    import requests
    from bs4 import BeautifulSoup

    session = requests.Session()
    session.cookies.set("connect.sid", config['cohost']['sid'], domain="cohost.org")

    page = session.get(cohost_url)
    soup = BeautifulSoup(page.text, "html.parser")

    embeds = []
    for figure_element in soup.find_all("figure"):
        embed = discord.Embed(
            title="image",
            color=discord.Color(0x00549E)
        )
        embed.set_image(url=figure_element.find("img")["src"])
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
    submission, _ = api.submission(submission_id)

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

async def twitter(**kwargs):
    '''
    Hander for twitter.com
    '''

    # Tweet ID from URL
    is_vx = bool(kwargs['match'].group(1))
    tweet_path = kwargs['match'].group(2)
    tweet_id = tweet_path.split('/')[-1]

    async with ClientSession() as session:
        async with session.get(f"https://api.vxtwitter.com/sourcebot/status/{tweet_id}") as response:
            tweet_data = await response.json()

        if 'media_extended' not in tweet_data:
            return

        links = []
        for index, media in enumerate(tweet_data['media_extended']):
            if media['type'] == 'video':
                links.append(media['url'])

            if media['type'] == 'gif':
                with TemporaryDirectory() as tmpdir:
                    async with aiofiles.open(f"{tmpdir}/{tweet_id}-{index}.mp4", "wb") as file, session.get(media['url']) as response:
                        await file.write(await response.read())

                    args = shlex.split(
                        f"ffmpeg -loglevel fatal -hide_banner -y -i {tweet_id}-{index}.mp4 "
                        "-vf 'scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse' -loop 0 "
                        f"{tweet_id}-{index}.gif"
                    )

                    ffmpeg = await asyncio.create_subprocess_exec(*args, cwd=os.path.abspath(tmpdir))
                    await ffmpeg.wait()

                    shutil.move(f"{tmpdir}/{tweet_id}-{index}.gif", f"{config['media']['path']}/tweet-{tweet_id}-{index}.gif")
                    links.append(f"{config['media']['url']}/tweet-{tweet_id}-{index}.gif")

            if media['type'] == 'image':
                async with session.get(f"https://publish.twitter.com/oembed?url=https://x.com/{tweet_path}") as response:
                    try:
                        oEmbed_data = await response.json()
                        if not is_vx and 'error' in oEmbed_data:
                            links.append(media['url'])

                    except ContentTypeError as e:
                        print('ContentTypeError! Forcing.', e.message)
                        links.append(media['url'])

        if links:
            return [ { 'content' : "\n".join(links) } ]

async def tiktok(**kwargs):
    '''
    Handler for tiktok
    '''

    # Tiktok URL from params
    message_url = kwargs['match'].group(1)
    async with ClientSession() as session:
        # Fetch tiktok_id
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0'
        })
        async with session.get(message_url, allow_redirects=True) as response:
            url = str(response.url).split('?', maxsplit=1)[0] # remove all the junk in query data
            vx_url = url.replace('tiktok.com', 'vxtiktok.com')

        tiktok_id = url.split('/')[-1]

        # Prepare mongodb connection
        client = MongoClient(config['mongodb']['uri'])
        cached_data = client['sourcebot']['tiktok_db'].find_one({
            'tiktok_id': int(tiktok_id)
        })

        if not cached_data:
            # Fetch data from vxtiktok
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)'
            })
            async with session.get(vx_url) as response:
                data_bytes = await response.read()
                data = data_bytes.decode('utf-8')
                direct_url = search(r'<meta property="og:video:secure_url" content="(.*?)" \/>', data).group(1)

            # Download url and send it back
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0'
            })
            with TemporaryDirectory() as tmpdir:
                async with aiofiles.open(f"{tmpdir}/tiktok-{tiktok_id}.mp4", "wb") as file, session.get(direct_url) as response:
                    if response.status == 403:
                        return
                    
                    await file.write(await response.read())

                shutil.move(f"{tmpdir}/tiktok-{tiktok_id}.mp4", f"{config['media']['path']}/tiktok-{tiktok_id}.mp4")

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

                shutil.move(f"{tmpdir}/output.mp4", f"{config['media']['path']}/reddit-{unique_id}.mp4")

    return [ { 'content': f"{config['media']['url']}/reddit-{unique_id}.mp4" } ]

async def instagram(**kwargs):
    '''
    Handler for instagram
    '''
    reel_id = kwargs['match'].group(1)

    with TemporaryDirectory() as tmpdir:
        async with ClientSession() as session:
            async with aiofiles.open(f"{tmpdir}/{reel_id}.mp4", "wb") as file:
                async with session.get(f"https://www.ddinstagram.com/videos/{reel_id}/1") as response:
                    await file.write(await response.read())
                    shutil.move(f"{tmpdir}/{reel_id}.mp4", f"{config['media']['path']}/instagram-{reel_id}.mp4")

    return [ { 'content': f"{config['media']['url']}/instagram-{reel_id}.mp4" } ]

from atproto import Client, models
import re

async def bsky(**kwargs):
    '''
    Handler for bsky videos
    '''
    print('ok')

    user_handle, post_id = kwargs['match'].groups()

    # Initialize the client and authenticate
    client = Client()
    client.login(config['bsky']['handle'], config['bsky']['password'])

    # Fetch the specific post using the extracted handle and post ID
    try:
        post = client.get_post(post_id, user_handle)
    except Exception as e:
        return f"Failed to fetch the post: {e}"

    # Access the 'value' attribute where the post details are stored
    record = post.value

    # Extract the DID from the post's URI
    did_match = re.match(r"at://(did:[^/]+)/", post.uri)
    if not did_match:
        return "Unable to extract DID from post URI."
    user_did = did_match.group(1)

    # Check if the record has an 'embed' and if it's of the expected type (e.g., video)
    if record.embed and hasattr(record.embed, 'video'):
        video_blob = record.embed.video

        # Check if the video is of type 'video/mp4' or 'application/vnd.apple.mpegurl' (for .m3u8 files)
        if video_blob.mime_type in ['video/mp4', 'application/vnd.apple.mpegurl']:
            # Construct the video URL using the DID and reference link
            media_url = f"https://video.bsky.app/watch/{user_did}/{video_blob.ref.link}/playlist.m3u8"

            with TemporaryDirectory() as tmpdir:
                filename = f"bsky-{video_blob.ref.link}.mp4"

                args = shlex.split(
                    f"ffmpeg -loglevel fatal -hide_banner -y -i {media_url} "
                    "-c:v libx264 -preset medium -crf 23 -c:a aac -b:a 128k "
                    f"{filename}"
                )
                ffmpeg = await asyncio.create_subprocess_exec(*args, cwd=os.path.abspath(tmpdir))
                await ffmpeg.wait()

                shutil.move(f"{tmpdir}/{filename}", f"{config['media']['path']}/{filename}")
                return [ { 'content': f"{config['media']['url']}/{filename}" } ]

        else:
            return "The media is not an MP4 or compatible HLS video."
    else:
        return "No video found in the post."


async def youtube(**kwargs):
    '''
    Youtube downloading via url
    '''

    # Youtube video path from params
    video = kwargs['match'].group(1)

    # Only trigger this for direct messages
    if not isinstance(kwargs['message'].channel, discord.DMChannel):
        return

    print(f"processing {video=}")

    # Download video to temporary directory
    with TemporaryDirectory() as tmpdir:
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
            'quiet': True,
            'extract_flat': True,
            'outtmpl': f"{tmpdir}/{video}.%(ext)s"
        }

        with YoutubeDL(ydl_opts) as ydl:
            meta = ydl.extract_info(f"https://youtube.com/watch?v={video}")
            filename = f"{video}.{meta['ext']}"

            shutil.move(f"{tmpdir}/{filename}", f"{config['media']['path']}/youtube-{filename}")
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

                shutil.move(f"{tmpdir}/{filename}", f"{config['media']['path']}/{filename}")
                return { 'content': f"Converted {filename} to x264 in {perf_counter() - init_time:.2f}s\n{config['media']['url']}/{filename}" }
