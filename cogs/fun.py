import discord
from discord.ext import commands
from config import config
from pymongo import MongoClient

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name='tiktok')
    async def _tiktok(self, ctx):
        '''Posts a random tiktok from sourcebot's collection.'''
        client = MongoClient(config['mongo']['uri'])
        tiktok = client['sourcebot']['tiktok_db'].aggregate([{"$sample": {"size": 1}}]).next()
        await ctx.respond(f"{config['media']['url']}/tiktok-{tiktok['tiktok_id']}.mp4")

    @commands.slash_command(name='friday')
    async def _friday(self, ctx):
        '''Today is Friday in California!'''
        await ctx.respond(f"{config['media']['url']}/discord-friday.mp4")

    @commands.slash_command(name='flat')
    async def _flat(self, ctx):
        '''Today is Flat Fuck Friday!'''
        await ctx.respond(f"{config['media']['url']}/discord-flat.mov")

    @commands.slash_command(name='pies')
    async def _pies(self, ctx):
        '''Initiate dog protocol.'''
        await ctx.respond(f"{config['media']['url']}/protocol-dog.jpg")

    @commands.slash_command(name='siec')
    async def _siec(self, ctx):
        '''Robicie coś z siecią?'''
        await ctx.respond(f"{config['media']['url']}/network.png")

    @commands.slash_command(name='cinema')
    async def _siec(self, ctx):
        '''Absolute cinema'''
        await ctx.respond(f"{config['media']['url']}/absolute-cinema.png")

    @commands.slash_command(name='summon')
    async def _summon(self, ctx):
        '''Summon DI.'''
        role_id = 1364549167619375114
        await ctx.respond(f"<@&{role_id}> summon", allowed_mentions=discord.AllowedMentions(roles=True))

def setup(bot):
    bot.add_cog(Fun(bot))