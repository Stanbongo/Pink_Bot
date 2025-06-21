import random
import asyncio
import datetime

import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pytz import timezone, utc

from cogs.database import (
    set_winner, get_previous_winner, get_current_winner,
    set_lottery_channel, get_lottery_channel,
    get_lottery_date, set_lottery_date, delete_lottery_date
)
from cogs.gif_generator import generate_lottery_gif


class Commands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tz = timezone('Etc/GMT+7')
        # Получаем текущий цикл событий
        try:
            self.loop = asyncio.get_event_loop()
        except RuntimeError:
            self.loop = None
        self.scheduler = AsyncIOScheduler(timezone=utc)  # Scheduler в UTC
        self.scheduler.start()
        # словарь guild_id -> {'recurring': job, 'oneoff': job}
        self.jobs = {}

    def schedule_lottery_job(self, guild_id: int):
        async def job_coro():
            await self.run_lottery_for_guild(guild_id)

        def job_func():
            loop = self.loop or asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(job_coro(), loop)

        return job_func

    async def load_scheduled_lotteries(self):
        for guild in self.bot.guilds:
            guild_id = guild.id
            date_str = await get_lottery_date(guild_id)
            if not date_str:
                continue
            try:
                dt_naive = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                dt_local = self.tz.localize(dt_naive)
                dt_utc = dt_local.astimezone(utc)
                if dt_utc > datetime.datetime.now(utc):
                    trigger = DateTrigger(run_date=dt_utc)
                    job_func = self.schedule_lottery_job(guild_id)
                    job = self.scheduler.add_job(job_func, trigger)
                    if guild_id not in self.jobs:
                        self.jobs[guild_id] = {}
                    self.jobs[guild_id]['oneoff'] = job
                else:
                    await delete_lottery_date(guild_id)
            except Exception as e:
                print(f"[Scheduler] Ошибка при загрузке планов лотереи для гильдии {guild_id}: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        await self.load_scheduled_lotteries()

    @commands.command(name="set_lottery_channel")
    @commands.has_role('Владыка Петухов')
    async def set_lottery_channel_cmd(self, ctx):
        await set_lottery_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(f"✅ Канал для розыгрыша установлен: {ctx.channel.mention}")

    @commands.command(name="start_lottery")
    @commands.has_role('Владыка Петухов')
    async def start_lottery(self, ctx, measure: str, periodicity: int, date: str = None, time: str = None):
        measures = ['sec', 'min', 'day']
        if measure not in measures:
            await ctx.send(f'❌ Неверная единица времени. Используйте: {"/".join(measures)}')
            return
        interval_seconds = periodicity
        if measure == 'min':
            interval_seconds *= 60
        elif measure == 'day':
            interval_seconds *= 86400
        if date and time:
            try:
                dt_naive = datetime.datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M:%S")
                dt_local = self.tz.localize(dt_naive)
                start_dt_utc = dt_local.astimezone(utc)
            except ValueError:
                await ctx.send("❌ Неверный формат даты. Используйте: YYYY-MM-DD HH:MM:SS")
                return
            if start_dt_utc <= datetime.datetime.now(utc):
                await ctx.send("❌ Указанная дата уже прошла.")
                return
        else:
            start_dt_utc = datetime.datetime.now(utc)
        guild_id = ctx.guild.id
        old_rec = self.jobs.get(guild_id, {}).get('recurring')
        if old_rec:
            try:
                self.scheduler.remove_job(old_rec.id)
            except Exception:
                pass
            self.jobs[guild_id].pop('recurring', None)
        trigger = IntervalTrigger(seconds=interval_seconds, start_date=start_dt_utc)
        job_func = self.schedule_lottery_job(guild_id)
        job = self.scheduler.add_job(job_func, trigger)
        if guild_id not in self.jobs:
            self.jobs[guild_id] = {}
        self.jobs[guild_id]['recurring'] = job
        # Сохраняем в БД время в Московской зоне для удобства, но в UTC для планировщика используем
        await set_lottery_date(guild_id, dt_local.strftime("%Y-%m-%d %H:%M:%S"))
        start_local_str = dt_local.strftime('%Y-%m-%d %H:%M:%S') if date and time else datetime.datetime.now(self.tz).strftime('%Y-%m-%d %H:%M:%S')
        await ctx.send(f"✅ Лотерея запланирована каждые {periodicity} {measure}, начиная с {start_local_str}")

    @commands.command(name="start_lottery_now")
    @commands.has_role('Владыка Петухов')
    async def start_lottery_now(self, ctx, interval_seconds: int = 604800):
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
        # Моментальный запуск
        await self.run_lottery_for_guild(guild_id)
        now_utc = datetime.datetime.now(utc)
        next_run_utc = now_utc + datetime.timedelta(seconds=interval_seconds)
        trigger = IntervalTrigger(seconds=interval_seconds, start_date=next_run_utc)
        job_func = self.schedule_lottery_job(guild_id)
        job = self.scheduler.add_job(job_func, trigger)
        self.jobs[guild_id] = {'recurring': job}
        next_run_local = next_run_utc.astimezone(self.tz)
        await ctx.send(f"✅ Моментальный запуск проведён. Следующий розыгрыш через {interval_seconds} сек. — {next_run_local.strftime('%Y-%m-%d %H:%M:%S')} МСК")

    @commands.command(name="stop_lottery")
    @commands.has_role('Владыка Петухов')
    async def stop_lottery(self, ctx):
        guild_id = ctx.guild.id
        job = self.jobs.get(guild_id, {}).get('recurring')
        if job:
            try:
                self.scheduler.remove_job(job.id)
            except Exception:
                pass
            self.jobs[guild_id].pop('recurring', None)
            await delete_lottery_date(guild_id)
            await ctx.send('🛑 Циклическая лотерея остановлена')
        else:
            await ctx.send('ℹ️ Активная циклическая лотерея не найдена')

    @commands.command(name="lottery_status")
    @commands.has_role('Владыка Петухов')
    async def lottery_status(self, ctx):
        guild_id = ctx.guild.id
        job = self.jobs.get(guild_id, {}).get('recurring')
        if job and job.next_run_time:
            next_run_local = job.next_run_time.astimezone(self.tz)
            await ctx.send(f"Лотерея активна, следующая итерация: {next_run_local.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            await ctx.send("Лотерея не активна")

    @commands.command(name="time_to_lottery")
    async def time_to_lottery(self, ctx):
        guild_id = ctx.guild.id
        job = self.jobs.get(guild_id, {}).get('recurring')
        if job and job.next_run_time:
            next_run_local = job.next_run_time.astimezone(self.tz)
            now_local = datetime.datetime.now(self.tz)
            delta = next_run_local - now_local
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
            await ctx.send(f"До следующего розыгрыша осталось: {' '.join(parts)} (запуск: {next_run_local.strftime('%Y-%m-%d %H:%M:%S')} МСК)")
        else:
            await ctx.send("Расписание розыгрыша не установлено или нет следующих запусков.")

    async def run_lottery_for_guild(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            print(f"[Lottery] Гильдия {guild_id} не найдена")
            return
        channel_id = await get_lottery_channel(guild_id)
        if not channel_id:
            print(f"[Lottery] Канал лотереи не задан для гильдии {guild_id}")
            return
        channel = guild.get_channel(int(channel_id))
        if not channel:
            print(f"[Lottery] Канал с ID {channel_id} не найден в гильдии {guild_id}")
            return
        members = [m for m in guild.members if not m.bot]
        if not members:
            await channel.send("ℹ️ Нет участников для розыгрыша.")
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
        role = discord.utils.get(guild.roles, name="Главный петух")
        if role:
            prev = await get_previous_winner(guild_id)
            if prev:
                prev_id = prev[0]
                if prev_id:
                    prev_member = guild.get_member(int(prev_id))
                    if prev_member and role in prev_member.roles:
                        try:
                            await prev_member.remove_roles(role)
                        except Exception as e:
                            print(f"Error removing role: {e}")
        if role:
            try:
                await winner_member.add_roles(role)
            except Exception as e:
                await channel.send(f"Ошибка при выдаче роли: {e}")
                return
        await set_winner(guild_id, winner_member)
        await channel.send(f"@everyone, начинаем розыгрыш роли **Главный петух**!")
        if bio:
            try:
                bio.seek(0)
                await channel.send(file=discord.File(fp=bio, filename="lottery.gif"))
            except Exception as e:
                await channel.send(f"Ошибка при отправке гифки: {e}")
        await channel.send(f"🎉 Победитель лотереи: {winner_member.mention} 🥳🥳🥳")

    def cog_unload(self):
        for jobs_dict in self.jobs.values():
            for job in jobs_dict.values():
                if job:
                    try:
                        self.scheduler.remove_job(job.id)
                    except Exception:
                        pass


async def setup(bot):
    await bot.add_cog(Commands(bot))
