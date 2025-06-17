import random
import asyncio
import datetime

import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from pytz import timezone

from cogs.database import (
    set_winner, get_previous_winner, get_current_winner,
    set_lottery_channel, get_lottery_channel
)
from cogs.gif_generator import generate_lottery_gif


class Commands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Таймзона Москвы для расписания и отображения
        self.tz = timezone('Europe/Moscow')
        # Инициализируем планировщик с таймзоной МСК
        self.scheduler = AsyncIOScheduler(timezone=self.tz)
        self.scheduler.start()
        # Храним задачи для каждого сервера: date and weekly
        self.jobs = {}  # guild_id -> {'oneoff': job, 'weekly': job}

    @commands.command(name="set_lottery_channel")
    @commands.has_role('Владыка Петухов')
    async def set_lottery_channel_cmd(self, ctx):
        await set_lottery_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(f"✅ Канал для розыгрыша установлен: {ctx.channel.mention}")

    @commands.command(name="start_weekly_lottery_now")
    @commands.has_role('Владыка Петухов')
    async def start_weekly_lottery_now(self, ctx, interval_seconds: int = 604800):
        guild_id = ctx.guild.id

        if guild_id in self.jobs:
            for job in self.jobs[guild_id].values():
                try:
                    self.scheduler.remove_job(job.id)
                except Exception:
                    pass
            self.jobs.pop(guild_id)

        channel_id = await get_lottery_channel(guild_id)
        if not channel_id:
            await ctx.send("Сначала установи канал командой !set_lottery_channel")
            return

        await self.run_lottery_for_guild(guild_id)

        now = datetime.datetime.now(self.tz)
        next_run = now + datetime.timedelta(seconds=interval_seconds)
        next_run = next_run.replace(microsecond=0)

        trigger = CronTrigger(second=next_run.second, minute=next_run.minute, hour=next_run.hour, day=next_run.day,
                              month=next_run.month, year=next_run.year, timezone=self.tz, start_date=next_run)

        job = self.scheduler.add_job(lambda: asyncio.create_task(self.run_lottery_for_guild(guild_id)), trigger)
        self.jobs[guild_id] = {'weekly': job}

        await ctx.send(f"Лотерея проведена, до скорой встречи!")
        # await ctx.send(f"✅ Моментальный запуск проведён. Следующий розыгрыш через {interval_seconds} сек. — {next_run.strftime('%Y-%m-%d %H:%M:%S')} МСК")

    @commands.command(name="schedule_lottery")
    @commands.has_role('Владыка Петухов')
    async def schedule_lottery(self, ctx, day_of_week: str, hour: int, minute: int, start_date: str = None):
        valid_days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        day = day_of_week.lower()
        if day not in valid_days:
            await ctx.send(f"Неверный день недели! Используй: {', '.join(valid_days)}")
            return
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            await ctx.send("Неверное время! Час: 0-23, минута: 0-59")
            return
        guild_id = ctx.guild.id
        if guild_id in self.jobs:
            for job in self.jobs[guild_id].values():
                try:
                    self.scheduler.remove_job(job.id)
                except Exception:
                    pass
            self.jobs.pop(guild_id)
        channel_id = await get_lottery_channel(guild_id)
        if not channel_id:
            await ctx.send("Сначала установи канал командой !set_lottery_channel")
            return
        weekday_index = valid_days.index(day)
        now = datetime.datetime.now(self.tz)
        first_dt = None
        if start_date:
            try:
                dt_naive = datetime.datetime.strptime(start_date, "%Y-%m-%d")
                dt_with_time = dt_naive.replace(hour=hour, minute=minute, second=0, microsecond=0)
                dt_local = self.tz.localize(dt_with_time)
            except Exception:
                await ctx.send("Неверный формат даты. Используй YYYY-MM-DD")
                return
            if dt_local >= now and dt_local.weekday() == weekday_index:
                first_dt = dt_local
            else:
                base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if base < now:
                    base = base + datetime.timedelta(days=1)
                days_ahead = (weekday_index - base.weekday() + 7) % 7
                if days_ahead == 0:
                    if base < now:
                        days_ahead = 7
                first_dt = base + datetime.timedelta(days=days_ahead)
                first_dt = self.tz.localize(first_dt.replace(tzinfo=None))
        else:
            base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if base < now:
                base = base + datetime.timedelta(days=1)
            days_ahead = (weekday_index - base.weekday() + 7) % 7
            if days_ahead == 0 and base < now:
                days_ahead = 7
            first_dt = base + datetime.timedelta(days=days_ahead)
            first_dt = self.tz.localize(first_dt.replace(tzinfo=None))

        jobs = {}
        trigger_one = DateTrigger(run_date=first_dt)
        job_one = self.scheduler.add_job(lambda: asyncio.create_task(self.run_lottery_for_guild(guild_id)), trigger_one)
        jobs['oneoff'] = job_one
        next_start = first_dt + datetime.timedelta(days=7)
        trigger_weekly = CronTrigger(day_of_week=day, hour=hour, minute=minute, timezone=self.tz, start_date=next_start)
        job_week = self.scheduler.add_job(lambda: asyncio.create_task(self.run_lottery_for_guild(guild_id)), trigger_weekly)
        jobs['weekly'] = job_week
        self.jobs[guild_id] = jobs
        msg = f"✅ Розыгрыш запланирован: первый запуск {first_dt.strftime('%Y-%m-%d %H:%M:%S')} МСК, далее еженедельно по {day.capitalize()} в {hour:02d}:{minute:02d} МСК."
        await ctx.send(msg)

    @commands.command(name="time_to_lottery")
    async def time_to_lottery(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.jobs:
            await ctx.send("Расписание розыгрыша не установлено.")
            return
        now = datetime.datetime.now(self.tz)
        next_runs = []
        for job in self.jobs[guild_id].values():
            nr = job.next_run_time
            if nr:
                nr_local = nr.astimezone(self.tz)
                if nr_local >= now:
                    next_runs.append(nr_local)
        if not next_runs:
            await ctx.send("Нет запланированных запусков.")
            return
        next_run = min(next_runs)
        delta = next_run - now
        days = delta.days
        hours, rem = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days} дн.")
        if hours:
            parts.append(f"{hours} ч.")
        if minutes:
            parts.append(f"{minutes} мин.")
        if not parts:
            parts.append(f"{seconds} сек.")
        await ctx.send(f"До следующего розыгрыша осталось: {' '.join(parts)} (запуск: {next_run.strftime('%Y-%m-%d %H:%M:%S')} МСК)")

    async def run_lottery_for_guild(self, guild_id):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        channel_id = await get_lottery_channel(guild_id)
        if not channel_id:
            return
        channel = guild.get_channel(int(channel_id))
        if not channel:
            return
        await self.execute_lottery(channel)

    async def execute_lottery(self, channel):
        guild = channel.guild
        role = discord.utils.get(guild.roles, name="Главный петух")
        if role is None:
            await channel.send("⚠️ Роль 'Главный петух' не найдена на сервере!")
            return
        prev = await get_previous_winner(guild.id)
        if prev:
            prev_id = prev[0]
            if prev_id:
                prev_member = guild.get_member(int(prev_id))
                if prev_member and any(r.id == role.id for r in prev_member.roles):
                    try:
                        await prev_member.remove_roles(role)
                    except Exception as e:
                        print(f"Error removing role: {e}")
        members = [m for m in guild.members if not m.bot]
        if not members:
            await channel.send("🚫 Нет участников для розыгрыша!")
            return
        usernames = [m.display_name for m in members]
        try:
            bio, winner_name = await generate_lottery_gif(usernames)
            winner_member = next((m for m in members if m.display_name == winner_name), None)
            if winner_member is None:
                winner_member = random.choice(members)
        except Exception as e:
            print(f"[GIF] Ошибка при генерации гифки: {e}")
            winner_member = random.choice(members)
            bio = None
        try:
            await winner_member.add_roles(role)
        except Exception as e:
            await channel.send(f"Ошибка при выдаче роли: {e}")
            return
        await set_winner(guild.id, winner_member)
        await channel.send(f"@everyone, начинаем розыгрыш роли **Главный петух**!")
        if bio:
            try:
                bio.seek(0)
                await channel.send(file=discord.File(fp=bio, filename="lottery.gif"))
            except Exception as e:
                await channel.send(f"Ошибка при отправке гифки: {e}")
        await channel.send(f"🎉 Поздравляем победителя: {winner_member.mention} 🥳🥳🥳")

async def setup(bot):
    await bot.add_cog(Commands(bot))