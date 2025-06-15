import os
import logging
import asyncio
from datetime import datetime
import shutil
from telethon import TelegramClient, events, Button
from telethon.tl.types import InputMessagesFilterPhotos
from dotenv import load_dotenv
import tempfile
from pathlib import Path
from utils import logger, WITH_TEXT_DIR, WITHOUT_TEXT_DIR

# Загружаем переменные окружения
load_dotenv()

# Настройки бота
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')

# Преобразуем API_ID в int (это важно!)
try:
    API_ID = int(API_ID)
except (ValueError, TypeError):
    logger.error("API_ID должен быть числом! Проверьте значение в .env файле")
    exit(1)

try:
    ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', 0))
except (ValueError, TypeError):
    logger.error("ADMIN_USER_ID должен быть числом! Проверьте значение в .env файле")
    exit(1)

# Проверка настроек
if not all([BOT_TOKEN, API_ID, API_HASH, ADMIN_USER_ID]):
    logger.error("Не указаны обязательные параметры в .env файле!")
    exit(1)

# Состояние пользователя
user_state = {
    'current_category': None,  # 'with_text' или 'without_text'
    'current_index': 0,
    'images': []
}

async def load_images():
    """Загружает список изображений из обоих директорий"""
    with_text_images = list(WITH_TEXT_DIR.glob('*.jpg'))
    without_text_images = list(WITHOUT_TEXT_DIR.glob('*.jpg'))
    
    logger.info(f"Загружено изображений с текстом: {len(with_text_images)}")
    logger.info(f"Загружено изображений без текста: {len(without_text_images)}")
    
    return {
        'with_text': with_text_images,
        'without_text': without_text_images
    }

async def send_current_image(event):
    """Отправляет текущее изображение с кнопками навигации"""
    if not user_state['current_category'] or not user_state['images']:
        await event.respond("Нет доступных изображений для просмотра.")
        return
    
    images = user_state['images'][user_state['current_category']]
    if not images:
        await event.respond(f"Нет изображений в категории {user_state['current_category']}")
        return
    
    # Получаем текущий индекс (с защитой от выхода за пределы)
    if user_state['current_index'] >= len(images):
        user_state['current_index'] = 0
    if user_state['current_index'] < 0:
        user_state['current_index'] = len(images) - 1
    
    current_image = images[user_state['current_index']]
    
    # Создаем кнопки навигации
    buttons = [
        [
            Button.inline("⬅️ Пред.", data="prev"),
            Button.inline(f"{user_state['current_index'] + 1}/{len(images)}", data="count"),
            Button.inline("След. ➡️", data="next")
        ],
        [
            Button.inline("🗑️ Удалить", data="delete"),
            Button.inline("🔄 Перенести", data="move"),
            Button.inline("📋 Меню", data="menu")
        ]
    ]
    
    # Создаем подпись для изображения
    caption = (f"🖼 Мем #{user_state['current_index'] + 1}/{len(images)}\n"
               f"📂 Категория: {'С текстом' if user_state['current_category'] == 'with_text' else 'Без текста'}\n"
               f"📅 Добавлен: {datetime.fromtimestamp(os.path.getctime(current_image)).strftime('%Y-%m-%d')}")
    
    # ИСПРАВЛЕНИЕ: Используем client.send_file вместо event.respond с caption
    # Сначала удаляем предыдущее сообщение, если есть
    try:
        await event.delete()
    except:
        pass  # Если не можем удалить, просто продолжаем
    
    # Отправляем новое сообщение с изображением
    await event.client.send_file(
        event.chat_id,
        file=str(current_image),
        caption=caption,
        buttons=buttons
    )

async def main():
    """Запускает бота"""
    logger.info(f"Запуск Telegram-бота для просмотра мемов с API_ID={API_ID} и API_HASH={API_HASH[:5]}...")
    
    # Инициализация клиента
    bot = TelegramClient('meme_bot_session', API_ID, API_HASH)
    
    @bot.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        # Проверяем, что это администратор
        sender = await event.get_sender()
        if sender.id != ADMIN_USER_ID:
            await event.respond("🔒 У вас нет доступа к этому боту.")
            return
        
        # Приветственное сообщение
        await event.respond(
            "👋 Привет! Я помогу тебе просматривать и сортировать мемы.\n\n"
            "Выбери категорию, чтобы начать просмотр:",
            buttons=[
                [Button.inline("С текстом", data="category_with_text")],
                [Button.inline("Без текста", data="category_without_text")],
                [Button.inline("Обновить коллекцию", data="reload_images")]
            ]
        )
    
    @bot.on(events.NewMessage(pattern='/help'))
    async def help_handler(event):
        # Проверяем, что это администратор
        sender = await event.get_sender()
        if sender.id != ADMIN_USER_ID:
            return
        
        await event.respond(
            "📚 Команды бота:\n\n"
            "/start - начать работу с ботом\n"
            "/help - показать эту справку\n\n"
            "Используйте кнопки для навигации по коллекции мемов."
        )
    
    @bot.on(events.CallbackQuery())
    async def callback_handler(event):
        # Проверяем, что это администратор
        sender = await event.get_sender()
        if sender.id != ADMIN_USER_ID:
            await event.answer("🔒 У вас нет доступа к этому боту.")
            return
        
        data = event.data.decode()
        logger.info(f"Нажата кнопка: {data}")
        
        # Сначала отправляем уведомление о нажатии
        if data != "count":
            await event.answer(f"Выбрано: {data}")
        
        if data == "menu":
            await event.edit(
                "Выбери категорию для просмотра:",
                buttons=[
                    [Button.inline("С текстом", data="category_with_text")],
                    [Button.inline("Без текста", data="category_without_text")],
                    [Button.inline("Обновить коллекцию", data="reload_images")]
                ]
            )
            
        elif data == "reload_images":
            user_state['images'] = await load_images()
            await event.edit(
                "🔄 Коллекция мемов обновлена!\n\n"
                f"С текстом: {len(user_state['images']['with_text'])}\n"
                f"Без текста: {len(user_state['images']['without_text'])}\n\n"
                "Выбери категорию для просмотра:",
                buttons=[
                    [Button.inline("С текстом", data="category_with_text")],
                    [Button.inline("Без текста", data="category_without_text")]
                ]
            )
            
        elif data == "category_with_text":
            user_state['current_category'] = 'with_text'
            user_state['current_index'] = 0
            await send_current_image(event)
            
        elif data == "category_without_text":
            user_state['current_category'] = 'without_text'
            user_state['current_index'] = 0
            await send_current_image(event)
            
        elif data == "next":
            if user_state['current_category']:
                user_state['current_index'] += 1
                # Если вышли за предел, переходим к первому изображению
                if user_state['current_index'] >= len(user_state['images'][user_state['current_category']]):
                    user_state['current_index'] = 0
                await send_current_image(event)
            else:
                await event.answer("Сначала выберите категорию")
                
        elif data == "prev":
            if user_state['current_category']:
                user_state['current_index'] -= 1
                # Если вышли за предел, переходим к последнему изображению
                if user_state['current_index'] < 0:
                    user_state['current_index'] = len(user_state['images'][user_state['current_category']]) - 1
                await send_current_image(event)
            else:
                await event.answer("Сначала выберите категорию")
        
        elif data == "count":
            if user_state['current_category']:
                total = len(user_state['images'][user_state['current_category']])
                await event.answer(f"Мем {user_state['current_index'] + 1} из {total}")
            
        elif data == "delete":
            if not user_state['current_category']:
                await event.answer("Сначала выберите категорию")
                return
                
            images = user_state['images'][user_state['current_category']]
            if not images:
                await event.answer("Нет изображений для удаления")
                return
                
            # Получаем текущее изображение
            current_image = images[user_state['current_index']]
            
            try:
                # Удаляем файл
                os.remove(current_image)
                await event.answer(f"Мем удален!")
                
                # Обновляем список изображений
                user_state['images'] = await load_images()
                
                # Показываем следующий мем (или информацию, что мемов больше нет)
                if user_state['images'][user_state['current_category']]:
                    # Если индекс теперь за пределами списка, корректируем
                    if user_state['current_index'] >= len(user_state['images'][user_state['current_category']]):
                        user_state['current_index'] = 0
                    await send_current_image(event)
                else:
                    await event.edit(f"В категории больше нет мемов.", buttons=[
                        [Button.inline("Вернуться в меню", data="menu")]
                    ])
                    
            except Exception as e:
                logger.error(f"Ошибка при удалении мема: {e}")
                await event.answer(f"Ошибка при удалении: {str(e)[:50]}...")
        
        elif data == "move":
            # Если не выбрана категория, ничего не делаем
            if not user_state['current_category']:
                await event.answer("Сначала выберите категорию")
                return
                
            images = user_state['images'][user_state['current_category']]
            if not images:
                await event.answer("Нет изображений для перемещения")
                return
                
            # Получаем текущее изображение
            current_image = images[user_state['current_index']]
            
            # Определяем целевую директорию (противоположную текущей)
            current_dir = WITH_TEXT_DIR if user_state['current_category'] == 'with_text' else WITHOUT_TEXT_DIR
            target_dir = WITHOUT_TEXT_DIR if user_state['current_category'] == 'with_text' else WITH_TEXT_DIR
            target_category = 'without_text' if user_state['current_category'] == 'with_text' else 'with_text'
            
            try:
                # Создаем путь к новому файлу
                filename = os.path.basename(current_image)
                target_path = target_dir / filename
                
                # Если файл с таким именем уже существует, добавляем префикс
                if target_path.exists():
                    base, ext = os.path.splitext(filename)
                    target_path = target_dir / f"{base}_moved{ext}"
                
                # Перемещаем файл
                shutil.move(str(current_image), str(target_path))
                await event.answer(f"Мем перемещен в категорию '{target_category}'!")
                
                # Обновляем список изображений
                user_state['images'] = await load_images()
                
                # Показываем следующий мем (или информацию, что мемов больше нет)
                if user_state['images'][user_state['current_category']]:
                    # Если индекс теперь за пределами списка, корректируем
                    if user_state['current_index'] >= len(user_state['images'][user_state['current_category']]):
                        user_state['current_index'] = len(user_state['images'][user_state['current_category']]) - 1
                    await send_current_image(event)
                else:
                    await event.edit(f"В категории больше нет мемов.", buttons=[
                        [Button.inline("Вернуться в меню", data="menu")]
                    ])
                    
            except Exception as e:
                logger.error(f"Ошибка при перемещении мема: {e}")
                await event.answer(f"Ошибка при перемещении: {str(e)[:50]}...")
    
    # Загружаем изображения при старте
    user_state['images'] = await load_images()
    
    try:
        # Запуск бота
        await bot.start(bot_token=BOT_TOKEN)
        logger.info(f"Бот запущен. Авторизован как @{(await bot.get_me()).username}")
        
        # Продолжаем работу бота, пока не прервут
        await bot.run_until_disconnected()
        
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        
    finally:
        await bot.disconnect()
        logger.info("Бот остановлен")

if __name__ == "__main__":
    # Запускаем асинхронную функцию в event loop
    asyncio.run(main()) 