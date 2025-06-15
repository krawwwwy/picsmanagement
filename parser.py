import os
import asyncio
import tempfile
from telethon import TelegramClient, events
from telethon.tl.types import InputMessagesFilterPhotos
import time
from tqdm import tqdm
import re
from dotenv import load_dotenv
from utils import logger, save_image
from classifier import classifier

# Загружаем переменные окружения
load_dotenv()

# Конфигурация Telegram API
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
SOURCE_CHANNELS = os.getenv('SOURCE_CHANNELS', '').split(',')

# Преобразуем API_ID в int (это важно!)
try:
    API_ID = int(API_ID)
except (ValueError, TypeError):
    logger.error("API_ID должен быть числом! Проверьте значение в .env файле")
    exit(1)

# Проверка настроек
if not API_ID or not API_HASH:
    logger.error("Не указаны API_ID или API_HASH в .env файле!")
    exit(1)

if not SOURCE_CHANNELS or SOURCE_CHANNELS == ['']:
    logger.error("Не указаны каналы для парсинга в .env файле!")
    exit(1)

# Экстракция юзернеймов каналов из URL
def extract_username(channel_url):
    # Извлекаем юзернейм из URL вида https://t.me/username или @username или просто username
    if match := re.search(r'(?:https?://)?t\.me/([^/]+)', channel_url):
        return match.group(1)
    elif channel_url.startswith('@'):
        return channel_url[1:]
    else:
        return channel_url.strip()

SOURCE_CHANNELS = [extract_username(channel) for channel in SOURCE_CHANNELS]
logger.info(f"Парсинг каналов: {', '.join(SOURCE_CHANNELS)}")

async def download_memes(client, channels, limit=30, offset_days=1):
    """
    Скачивает мемы из указанных каналов
    
    Args:
        client: Telegram клиент
        channels: список каналов
        limit: максимальное кол-во сообщений для проверки в каждом канале
        offset_days: за сколько дней назад проверять сообщения
    """
    total_processed = 0
    total_saved = 0
    
    for channel_username in channels:
        logger.info(f"Начинаю парсинг канала: @{channel_username}")
        
        try:
            # Получаем доступ к каналу
            channel = await client.get_entity(channel_username)
            
            # Получаем только фотографии
            messages = await client.get_messages(
                channel, 
                limit=limit, 
                filter=InputMessagesFilterPhotos,
                offset_date=int(time.time()) - offset_days * 24 * 60 * 60
            )
            
            logger.info(f"Найдено {len(messages)} изображений в @{channel_username}")
            
            # Обрабатываем каждое сообщение
            for message in tqdm(messages, desc=f"Обработка @{channel_username}"):
                # Пропускаем сообщения без медиа
                if not message.media:
                    continue
                
                total_processed += 1
                
                # Создаем временный файл для скачивания
                with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
                    temp_path = tmp_file.name
                
                try:
                    # Скачиваем изображение
                    await client.download_media(message, file=temp_path)
                    
                    # Определяем, содержит ли мем текст
                    has_text = classifier.has_text(temp_path)
                    
                    # Сохраняем изображение в соответствующую директорию
                    if save_image(temp_path, has_text):
                        total_saved += 1
                        
                except Exception as e:
                    logger.error(f"Ошибка при обработке медиа: {e}")
                    # Удаляем временный файл при ошибке
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                        
        except Exception as e:
            logger.error(f"Ошибка при обработке канала @{channel_username}: {e}")
    
    logger.info(f"Всего обработано изображений: {total_processed}")
    logger.info(f"Сохранено новых мемов: {total_saved}")
    
    return total_saved

async def main():
    logger.info(f"Запуск парсера мемов из Telegram с API_ID={API_ID} и API_HASH={API_HASH[:5]}...")
    
    # Инициализация клиента Telegram
    client = TelegramClient('meme_parser_session', API_ID, API_HASH)
    
    try:
        await client.start()
        logger.info("Успешное подключение к Telegram API")
        
        # Загружаем мемы из каналов
        saved_count = await download_memes(
            client, 
            SOURCE_CHANNELS, 
            limit=30,  # Количество сообщений для проверки
            offset_days=2  # Проверяем за последнюю неделю
        )
        
        logger.info(f"Парсинг завершен. Сохранено {saved_count} новых мемов.")
        
    except Exception as e:
        logger.error(f"Произошла ошибка: {e}")
    
    finally:
        await client.disconnect()
        logger.info("Отключение от Telegram API")

if __name__ == "__main__":
    # Запускаем асинхронную функцию в event loop
    asyncio.run(main()) 