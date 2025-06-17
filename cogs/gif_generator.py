# cogs/gif_generator.py
import random
import asyncio
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

def generate_lottery_gif_sync(usernames, width=400, height=100, frames=30):
    """
    Синхронная функция: генерирует GIF с плавной анимацией выбора победителя.
    usernames: список строк — имена участников.
    Возвращает BytesIO с GIF.
    """
    # Шрифт: на macOS пример пути. Убедитесь, что файл существует.
    # Можно указать другой шрифт, например Arial или системный.
    font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
    try:
        font = ImageFont.truetype(font_path, 24)
    except Exception:
        font = ImageFont.load_default()

    n = len(usernames)
    if n == 0:
        raise ValueError("Список участников пуст")

    # Случайным образом выбираем победителя заранее,
    # чтобы анимация заканчивалась на нём
    winner = random.choice(usernames)
    winner_index = usernames.index(winner)

    # Формируем прогрессию индексов: сначала быстро, потом замедляемся
    progression = []
    speed = 1.0
    idx = 0
    # frames определяет, сколько кадров до начала "финальных" остановок
    for i in range(frames):
        idx = (idx + int(speed)) % n
        progression.append(idx)
        speed *= 0.9  # замедление
        if speed < 1:
            speed = 1  # чтобы не остановиться полностью
    # Добавляем финальные кадры с победителем
    for _ in range(10):
        progression.append(winner_index)

    # Генерируем кадры
    images = []
    for pos in progression:
        img = Image.new("RGB", (width, height), color="white")
        draw = ImageDraw.Draw(img)
        text = usernames[pos]
        # Вычисляем размер текста через textbbox
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (width - text_w) // 2
        y = (height - text_h) // 2
        draw.text((x, y), text, font=font, fill="black")
        images.append(img)

    # Сохраняем в BytesIO
    bio = BytesIO()
    images[0].save(
        bio,
        format='GIF',
        save_all=True,
        append_images=images[1:],
        duration=80,  # можно настроить
        loop=0
    )
    bio.seek(0)
    return bio, winner  # возвращаем BytesIO и имя победителя

async def generate_lottery_gif(usernames):
    """
    Асинхронная обёртка, чтобы не блокировать event loop:
    вызывает синхронную функцию в отдельном потоке.
    """
    return await asyncio.to_thread(generate_lottery_gif_sync, usernames)
