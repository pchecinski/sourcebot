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

from pprint import pprint
from pathlib import Path
from zipfile import ZipFile

config = yaml.safe_load(open("config.yml"))

async def handlePixivUrl(message, submission_id):
    await message.channel.trigger_typing()

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

        # Run ffmpeg for the given file/directory
        subprocess.call(
            shlex.split(f"ffmpeg -loglevel fatal -hide_banner -y -f concat -i {submission_id}/ffconcat.txt {submission_id}.webm"),
            cwd=os.path.abspath(f"./media/")
        )

        # Remove source files
        for name in os.listdir(f"./media/{submission_id}/"):
            os.remove(f"./media/{submission_id}/{name}")
        os.rmdir(f"./media/{submission_id}/")

        path = f"./media/{submission_id}.webm"

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
    await message.channel.trigger_typing()

    # Log in to API and get session ID
    r = requests.get(f"https://inkbunny.net/api_login.php?username={config['inkbunny']['username']}&password={config['inkbunny']['password']}")
    data = r.json()
    session = data['sid']

    # Request information about the submission
    r = requests.get(f'https://inkbunny.net/api_submissions.php?sid={session}&submission_ids={submission_id}')
    data = r.json()

    if len(data['submissions']) != 1:
        return

    # Download and send file
    submission = data['submissions'][0]
    r = requests.get(submission['file_url_full'])
    with open(f"./media/{submission['file_name']}", 'wb') as f:
        f.write(r.content)

    await message.channel.send(content=f"{submission['title']} by {submission['username']}", file=discord.File(f"./media/{submission['file_name']}"))

async def handleFuraffinityUrl(message, submission_id):
    cookies = [
        {"name": "a", "value": config['furaffinity']['cookie']['a']},
        {"name": "b", "value": config['furaffinity']['cookie']['b']},
    ]

    api = faapi.FAAPI(cookies)
    submission, _ = api.get_submission(submission_id)

    if submission.rating == 'General':
       return

    await message.channel.trigger_typing()
    sub_file = api.get_submission_file(submission)

    path = './media/' + submission.file_url.split('/')[-1]
    with open(path, 'wb') as f:
        f.write(sub_file)

    await message.channel.send(content=f"{submission.title} by {submission.author}", file=discord.File(path))

class DiscordClient(discord.Client):
    async def on_ready(self):
        print(f"{self.user.name} has connected to Discord!")

    async def on_message(self, message):
        if message.author == self.user:
            return

        if message.channel.name not in config['discord']['chanells']:
            return

        for match in re.finditer("(?<=https://www.pixiv.net/en/artworks/)\w+", message.content):
            await handlePixivUrl(message, match.group(0))

        for match in re.finditer("(?<=https://inkbunny.net/s/)\w+", message.content):
            await handleInkbunnyUrl(message, match.group(0))

        for match in re.finditer("(?<=https://www.furaffinity.net/view/)\w+", message.content):
            await handleFuraffinityUrl(message, match.group(0))

# Main Loop
client = DiscordClient()
client.run(config['discord']['token'])
