'''
Definiton of hander functions for sourcebot.
'''

# Python standard libraries
import asyncio
import os
import shlex
import shutil
from atproto import Client
from re import sub
from tempfile import TemporaryDirectory
from time import perf_counter
import re

# Third-party libraries
import aiofiles
import discord
import xmltodict
from aiohttp import ClientSession, BasicAuth, ContentTypeError
from bs4 import BeautifulSoup
from pymongo import MongoClient
from yt_dlp import YoutubeDL

# Local modules
from config import config

# Source fetching
async def pixiv(**kwargs):
    '''
    Handler for pixiv.net via Phixiv
    '''

    illust_id = kwargs['match'].group(1)
    url = f'https://www.phixiv.net/en/artworks/{illust_id}'

    async with ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            html = await response.text()

        soup = BeautifulSoup(html, 'html.parser')

        title = soup.find('meta', property='og:title')['content']
        image_url = soup.find('meta', property='og:image')['content']

        embed = discord.Embed(
            title=title,
            color=discord.Color(0xFCE4F1),
            url=f'https://www.pixiv.net/en/artworks/{illust_id}',
        )
        embed.set_image(url=image_url)

    return [{'embeds': [embed]}]

async def inkbunny(**kwargs):
    '''
    Hander for inkbunny.net
    '''

    # Submission ID from params
    submission_id = kwargs['match'].group(1)
    page = kwargs['match'].group(2)

    headers = {
        "Referer": "https://inkbunny.net"
    }

    async with ClientSession(headers=headers) as session:
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
        files = []
        if page:
            page_id = int(page)
            
            path = f"{config['media']['path']}/inkbunny-{submission['files'][page_id - 1]['file_name']}"
            if not os.path.exists(path):
                async with session.get(submission['files'][page_id - 1]['file_url_full']) as response, aiofiles.open(path, "wb") as file:
                    await file.write(await response.read()) 
            files.append(path)

        else:
            for submission_file in submission['files']:
                path = f"{config['media']['path']}/inkbunny-{submission_file['file_name']}"
                if not os.path.exists(path):
                    async with session.get(submission_file['file_url_full']) as response, aiofiles.open(path, "wb") as file:
                        await file.write(await response.read()) 
                files.append(path)
    
    return files

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

async def furaffinity(**kwargs):
    '''
    Hander for furaffinity.net
    '''

    # Submission ID from params
    submission_id = kwargs['match'].group(1)

    async with ClientSession() as session:
        async with session.get(f"https://www.xfuraffinity.net/view/{submission_id}") as response:
            match = re.search(
                r'<meta\s+property="og:image:secure_url"\s+content="([^"]+)"',
                await response.text(),
            )
            image_url = match.group(1) if match else None

    return [ { 'content' : image_url } ]

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

    # post, domain and ID from params
    post_url = kwargs['match'].group(0)
    domain_url = kwargs['match'].group(1)
    post_id = kwargs['match'].group(2)

    async with ClientSession() as session:
        async with session.get(f"https://{domain_url}/api/oembed?url={post_url}") as response:
            # Skip links that return valid embed
            if response.status == 200:
                return

        async with session.get(f"https://{domain_url}/api/v1/statuses/{post_id}") as response:
            data = await response.json()

    # Skip statuses without media attachments
    if 'media_attachments' not in data:
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
        for i in range(1,6):
            async with session.get(f"https://api.fxtwitter.com/2/status/{tweet_id}") as response:
                tweet_data = await response.json()
                if tweet_data['code'] == 200:
                    break
                else:
                    print(f'retrying {tweet_id=}, {tweet_data['code']=}, {i}/5')
                    await asyncio.sleep(i * 2)

        if 'status' not in tweet_data or 'media' not in tweet_data['status']:
            print(f"skipping {tweet_id=}, {tweet_data=}")
            return

        media = tweet_data['status']['media']

        links = []
        if 'videos' in media:
            for index, video in enumerate(media['videos']):
                if video['type'] == 'gif':
                    with TemporaryDirectory() as tmpdir:
                        async with aiofiles.open(f"{tmpdir}/{tweet_id}-{index}.mp4", "wb") as file, session.get(video['url']) as response:
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
                else:
                    links.append(video['url'])

        if 'photos' in media:
            async with session.get(f"https://publish.twitter.com/oembed?url=https://x.com/{tweet_path}") as response:
                try:
                    oEmbed_data = await response.json()
                    if not is_vx and 'error' in oEmbed_data:
                        for photos in media['photos']:
                            links.append(photos['url'])

                except ContentTypeError as e:
                    print('ContentTypeError! Forcing.', e.message)
                    for photos in media['photos']:
                        links.append(photos['url'])

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
            kk_url = url.replace('tiktok.com', 'kktiktok.com')

        tiktok_id = url.split('/')[-1]

        # Prepare mongodb connection
        client = MongoClient(config['mongo']['uri'])
        cached_data = client['sourcebot']['tiktok_db'].find_one({
            'tiktok_id': int(tiktok_id)
        })

        if not cached_data:
            # Fetch data from kktiktok
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)'
            })

            with TemporaryDirectory() as tmpdir:
                async with aiofiles.open(f"{tmpdir}/tiktok-{tiktok_id}.mp4", "wb") as file, session.get(kk_url) as response:
                    if response.status == 403:
                        return
                    
                    await file.write(await response.read())

                shutil.move(f"{tmpdir}/tiktok-{tiktok_id}.mp4", f"{config['media']['path']}/tiktok-{tiktok_id}.mp4")

            client['sourcebot']['tiktok_db'].insert_one({
                'tiktok_id': int(tiktok_id),
                'size': os.stat(f"{config['media']['path']}/tiktok-{tiktok_id}.mp4").st_size
            })

    return [ { 'content': f"{config['media']['url']}/tiktok-{tiktok_id}.mp4" } ]

async def instagram(**kwargs):
    '''
    Handler for instagram
    '''
    reel_url = kwargs['match'].group(1)
    reel_id = kwargs['match'].group(2)

    debug = {
        'best_size_mb': 0,
        'st_size': 0,
        'response_code': 0
    }

    with TemporaryDirectory() as tmpdir:
        source = f"source-{reel_id}.mp4"
        filename = f"instagram-{reel_id}.mp4"

        ydl_opts = {
            'cookiefile': 'code/cookies/www.instagram.com_cookies.txt',
            'format': 'bv*+ba/best',
            'merge_output_format': 'mp4',
            'quiet': True,
            'noprogress': True,
            'outtmpl': f"{tmpdir}/source-{reel_id}.%(ext)s",
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(reel_url, download=False)

            parts = info.get("requested_formats") or [info]
            total = 0
            for part in parts:
                size = part.get("filesize") or part.get("filesize_approx")
                if size is None:
                    break
                total += size

            best_size_mb = total / 1024 / 1024
            debug['best_size_mb'] = best_size_mb

            if best_size_mb > 100:
                ydl_opts['format'] =  (
                    "bv*[width<=720]+ba/bv*[height<=720]+ba/"
                    "best[width<=720]/best[height<=720]/best"
                )

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download(reel_url)

        shutil.move(
            f"{tmpdir}/{source}",
            f"{config['media']['path']}/{filename}"
        )

        from pathlib import Path
        f = Path(f"{config['media']['path']}/{filename}")
        debug['st_size'] = f.stat().st_size / 1024 / 1024

        async with ClientSession() as session:
            async with session.get(f"{config['media']['url']}/{filename}") as response:
                debug['response_code'] = response.status

        print(f"{debug=}")

    return [{
        'content': f"{config['media']['url']}/{filename}"
    }]

async def bsky(**kwargs):
    '''
    Handler for bsky videos
    '''
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
            'noprogress': True,
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
