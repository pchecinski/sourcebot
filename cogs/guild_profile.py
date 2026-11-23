import hashlib
import pathlib

from aiohttp import ClientSession
from discord.ext import commands

class GuildProfile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        CONFIG_DIR = pathlib.Path("code/config")
        settings = (
            ("avatar", CONFIG_DIR / "avatars", "guild_avatar", "avatar", ".png"),
            ("banner", CONFIG_DIR / "banners", "guild_banner", "banner", ".png"),
            ("nickname", CONFIG_DIR / "nicknames", "nick", "nick", ".txt"),
        )

        async with ClientSession() as session:
            for guild in self.bot.guilds:
                me = guild.me

                for name, directory, attribute, parameter, extension in settings:
                    path = directory / f"{guild.id}{extension}"
                    current = getattr(me, attribute)

                    if path.is_file():
                        desired = path.read_text(encoding="utf-8").strip() if name == "nickname" else path.read_bytes()

                        if name == "nickname":
                            if current == (desired or None):
                                continue
                        else:
                                async with session.get(current.replace(size=4096).url) as response:
                                    response.raise_for_status()
                                    current_bytes = await response.read()

                                if hashlib.sha256(current_bytes).digest() == hashlib.sha256(desired).digest():
                                    continue

                        await me.edit(**{parameter: desired or None})
                        print(f"{guild.name} ({guild.id}): {name} set")
                    elif current is not None:
                        await me.edit(**{parameter: None})
                        print(f"{guild.name} ({guild.id}): {name} removed")

def setup(bot):
    bot.add_cog(GuildProfile(bot))