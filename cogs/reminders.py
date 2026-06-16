import asyncio
import discord
from datetime import datetime
from discord.ext import bridge, commands
from pymongo import MongoClient

client = MongoClient('mongodb://127.0.0.1/sourcebot')
reminders_col = client['sourcebot']['reminders']

class Reminders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _schedule(self, reminder):
        asyncio.create_task(self._fire(reminder))

    async def _fire(self, reminder):
        now = datetime.now()
        delay = (reminder['target'] - now).total_seconds()

        if delay > 0:
            await asyncio.sleep(delay)

        user = self.bot.get_user(reminder['user_id'])
        if not user:
            return

        channel = self.bot.get_channel(reminder['channel_id']) or await user.create_dm()
        await channel.send(f"⏰ {user.mention} Reminder: **{reminder['message']}**")

        reminders_col.delete_one({'_id': reminder['_id']})

    @commands.Cog.listener()
    async def on_ready(self):
        pending = reminders_col.find({'target': {'$gt': datetime.now()}})
        count = 0
        for reminder in pending:
            self._schedule(reminder)
            count += 1
        if count:
            print(f"[reminders] Rescheduled {count} pending reminder(s).")

    @bridge.bridge_command(name='remind')
    async def _remind(self, ctx, *, args: str):
        '''Set a reminder. Usage: /remind 22:00 message or /remind 2026-06-17 22:00 message'''
        now = datetime.now()
        parts = args.split()

        if len(parts) >= 2 and '-' in parts[0] and ':' in parts[1]:
            try:
                target = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M")
                message = ' '.join(parts[2:])
            except ValueError:
                await ctx.respond("❌ Invalid format. Use `HH:MM message` or `YYYY-MM-DD HH:MM message`.")
                return

        elif ':' in parts[0] and '-' not in parts[0]:
            try:
                target = datetime.strptime(parts[0], "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
                if target < now:
                    target = target.replace(day=now.day + 1)
                message = ' '.join(parts[1:])
            except ValueError:
                await ctx.respond("❌ Invalid format. Use `HH:MM message` or `YYYY-MM-DD HH:MM message`.")
                return

        else:
            await ctx.respond("❌ Invalid format. Use `HH:MM message` or `YYYY-MM-DD HH:MM message`.")
            return

        if not message:
            await ctx.respond("❌ Please provide a reminder message.")
            return

        delay = (target - now).total_seconds()
        if delay <= 0:
            await ctx.respond("❌ That time is in the past.")
            return

        reminder = {
            'target': target,
            'message': message,
            'channel_id': ctx.channel.id,
            'user_id': ctx.author.id,
        }
        result = reminders_col.insert_one(reminder)
        reminder['_id'] = result.inserted_id

        self._schedule(reminder)
        await ctx.respond(f"✅ I'll remind you at **{target.strftime('%Y-%m-%d %H:%M')}**: *{message}*")

    @bridge.bridge_command(name='reminders')
    async def _reminders(self, ctx):
        '''List your pending reminders.'''
        pending = list(reminders_col.find({
            'user_id': ctx.author.id,
            'target': {'$gt': datetime.now()}
        }).sort('target', 1))

        if not pending:
            await ctx.respond("You have no pending reminders.")
            return

        embed = discord.Embed(title="Your pending reminders", colour=discord.Colour(0x8ba089))
        for reminder in pending:
            embed.add_field(
                name=reminder['target'].strftime('%Y-%m-%d %H:%M'),
                value=reminder['message'],
                inline=False
            )

        await ctx.respond(embed=embed)

def setup(bot):
    bot.add_cog(Reminders(bot))