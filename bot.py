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
import io
from PIL import Image, ImageDraw, ImageFont
import textwrap
import hashlib

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

# Добавим новые состояния для FSM (машины конечных состояний)
AWAITING_TOP_TEXT = "awaiting_top_text"  # Состояние ожидания ввода текста сверху
AWAITING_BOTTOM_TEXT = "awaiting_bottom_text"  # Состояние ожидания ввода текста снизу

# Словарь для хранения текущего состояния пользователя
user_states = {}

# Словарь для хранения данных пользователя (текущее изображение, тексты и т.д.)
user_data = {}

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
    
    # Создаем кнопки навигации с добавлением новой кнопки "Создать мем"
    buttons = [
        [
            Button.inline("⬅️ Пред.", data="prev"),
            Button.inline(f"{user_state['current_index'] + 1}/{len(images)}", data="count"),
            Button.inline("След. ➡️", data="next")
        ],
        [
            Button.inline("🗑️ Удалить", data="delete"),
            Button.inline("🔄 Перенести", data="move"),
            Button.inline("✏️ Создать мем", data="create_meme")  # Новая кнопка для создания мема
        ],
        [
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

async def create_meme_button_handler(event):
    """
    Обработчик нажатия кнопки "Создать мем"
    """
    user_id = event.sender_id
    
    # Проверяем, есть ли активное изображение для этого пользователя
    if user_id not in user_state['images'] or user_state['images'][user_id] is None:
        await event.respond("⚠️ Сначала выберите изображение, для которого хотите создать мем.")
        return

    # Сохраняем текущее изображение в данных пользователя
    if user_id not in user_data:
        user_data[user_id] = {}
    
    user_data[user_id]['current_image'] = user_state['images'][user_id][user_state['current_index']]
    
    # Устанавливаем состояние - ожидание верхнего текста
    user_states[user_id] = AWAITING_TOP_TEXT
    
    # Отправляем сообщение с просьбой ввести текст
    await event.respond("✏️ Введите текст, который будет размещен СВЕРХУ изображения (или отправьте /cancel для отмены):")

async def message_handler(event):
    """
    Обработчик текстовых сообщений
    """
    user_id = event.sender_id
    message_text = event.raw_text
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_USER_ID:
        await event.respond("⛔ У вас нет доступа к этому боту.")
        return
        
    # Обрабатываем команду /cancel для отмены создания мема
    if message_text == "/cancel":
        if user_id in user_states:
            del user_states[user_id]
            if user_id in user_data:
                user_data[user_id] = {}
            await event.respond("❌ Создание мема отменено.")
            return
    
    # Обработка состояний FSM для создания мема
    if user_id in user_states:
        state = user_states[user_id]
        
        if state == AWAITING_TOP_TEXT:
            # Пользователь ввел верхний текст, сохраняем его
            user_data[user_id]['top_text'] = message_text
            
            # Меняем состояние на ожидание нижнего текста
            user_states[user_id] = AWAITING_BOTTOM_TEXT
            
            # Просим ввести нижний текст
            await event.respond("✏️ Теперь введите текст, который будет размещен СНИЗУ изображения (или отправьте /cancel для отмены):")
            return
            
        elif state == AWAITING_BOTTOM_TEXT:
            # Пользователь ввел нижний текст, сохраняем его
            user_data[user_id]['bottom_text'] = message_text
            
            # Сбрасываем состояние
            del user_states[user_id]
            
            # Создаем мем на основе введенных данных
            image_path = user_data[user_id]['current_image']
            top_text = user_data[user_id]['top_text']
            bottom_text = user_data[user_id]['bottom_text']
            
            await event.respond("🔄 Создаю мем, пожалуйста, подождите...")
            
            # Создаем мем
            meme_path = await create_meme(image_path, top_text, bottom_text)
            
            if meme_path:
                # Отправляем мем пользователю
                await event.respond(f"✅ Вот ваш мем: {meme_path}")
                
                # Сбрасываем данные пользователя
                user_data[user_id] = {}
                logger.info(f"Создан новый мем: {meme_path}")
            else:
                await event.respond("❌ Произошла ошибка при создании мема.")
            
            return
    
    # Обработка обычных сообщений (не связанных с созданием мема)
    # ... existing message handling code ...

async def create_meme(image_path, top_text, bottom_text):
    """
    Создает мем, добавляя текст сверху и снизу изображения
    
    Args:
        image_path: путь к исходному изображению
        top_text: текст для размещения сверху
        bottom_text: текст для размещения снизу
        
    Returns:
        str: путь к созданному изображению или None в случае ошибки
    """
    try:
        # Открываем изображение
        with Image.open(image_path) as img:
            # Создаем копию, чтобы не изменять оригинал
            img = img.copy()
            
            # Получаем размеры
            width, height = img.size
            
            # Создаем объект для рисования
            draw = ImageDraw.Draw(img)
            
            # Настраиваем шрифт и его размер (примерно 1/10 от высоты изображения для более крупного текста)
            font_size = int(height / 10)  # Увеличенный размер шрифта (было 1/15)
            # Пытаемся использовать шрифт Impact (классический шрифт мемов)
            try:
                # Список возможных путей к шрифту Impact
                possible_paths = [
                    # Windows пути
                    "C:\\Windows\\Fonts\\impact.ttf",
                    "C:\\Windows\\Fonts\\Impact.ttf",
                    # Linux пути
                    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
                    "/usr/share/fonts/TTF/impact.ttf",
                    "/usr/share/fonts/truetype/impact.ttf",
                    # Если специально скачали в директорию проекта
                    "impact.ttf",
                    # Резервные варианты
                    "C:\\Windows\\Fonts\\arial.ttf",
                    "C:\\Windows\\Fonts\\Arial.ttf",
                    "C:\\Windows\\Fonts\\arialbd.ttf",  # Arial Bold
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                ]
                
                # Ищем существующий шрифт
                font_path = None
                for path in possible_paths:
                    if os.path.exists(path):
                        font_path = path
                        break
                
                if font_path:
                    font = ImageFont.truetype(font_path, font_size)
                    logger.info(f"Используется шрифт: {os.path.basename(font_path)}")
                else:
                    # Если не нашли Impact, используем шрифт по умолчанию
                    font = ImageFont.load_default()
                    logger.warning("Шрифт Impact не найден, используется стандартный шрифт")
            except Exception as e:
                # Если не удалось загрузить шрифт, используем стандартный
                font = ImageFont.load_default()
                logger.warning(f"Ошибка при загрузке шрифта: {e}")
            
            # Функция для добавления обводки тексту для лучшей читаемости
            def draw_text_with_outline(text, position, font, fill_color=(255, 255, 255), outline_color=(0, 0, 0), outline_width=3):
                x, y = position
                # Рисуем обводку (увеличена толщина до 3)
                for offset_x in range(-outline_width, outline_width + 1):
                    for offset_y in range(-outline_width, outline_width + 1):
                        draw.text((x + offset_x, y + offset_y), text, font=font, fill=outline_color)
                # Рисуем основной текст
                draw.text((x, y), text, font=font, fill=fill_color)
            
            # Функция для разбивки текста на несколько строк, если он слишком длинный
            def wrap_text(text, font, max_width):
                lines = []
                # Если текст пустой, возвращаем пустой список
                if not text:
                    return lines
                    
                # Оцениваем среднюю ширину символа для грубой оценки
                try:
                    avg_char_width = font.getbbox("A")[2]
                except:
                    # Для старых версий PIL
                    avg_char_width = font.getsize("A")[0]
                
                chars_per_line = max(1, int(max_width / avg_char_width))
                
                # Разбиваем текст на слова
                words = text.split()
                
                # Собираем слова в строки
                current_line = []
                current_width = 0
                
                for word in words:
                    try:
                        word_width = font.getbbox(word)[2]
                    except:
                        # Для старых версий PIL
                        word_width = font.getsize(word)[0]
                    
                    if current_width + word_width <= max_width:
                        current_line.append(word)
                        current_width += word_width + avg_char_width  # Добавляем ширину пробела
                    else:
                        lines.append(" ".join(current_line))
                        current_line = [word]
                        current_width = word_width
                
                if current_line:
                    lines.append(" ".join(current_line))
                
                return lines
            
            # Устанавливаем максимальную ширину текста
            max_text_width = width * 0.9  # 90% от ширины изображения
            
            # Подготавливаем верхний текст
            top_lines = wrap_text(top_text.upper(), font, max_text_width)
            try:
                top_height = len(top_lines) * (font_size + 5)
            except:
                top_height = 0
            
            # Подготавливаем нижний текст
            bottom_lines = wrap_text(bottom_text.upper(), font, max_text_width)
            try:
                bottom_height = len(bottom_lines) * (font_size + 5)
            except:
                bottom_height = 0
            
            # Рисуем верхний текст
            y_position = 10  # Отступ сверху
            for line in top_lines:
                # Центрируем текст
                try:
                    text_width = font.getbbox(line)[2]
                except:
                    # Для старых версий PIL
                    text_width = font.getsize(line)[0]
                
                x_position = (width - text_width) // 2
                draw_text_with_outline(line, (x_position, y_position), font)
                y_position += font_size + 5  # Отступ между строками
            
            # Рисуем нижний текст
            y_position = height - bottom_height - 10  # Отступ снизу
            for line in bottom_lines:
                # Центрируем текст
                try:
                    text_width = font.getbbox(line)[2]
                except:
                    # Для старых версий PIL
                    text_width = font.getsize(line)[0]
                
                x_position = (width - text_width) // 2
                draw_text_with_outline(line, (x_position, y_position), font)
                y_position += font_size + 5  # Отступ между строками
            
            # Генерируем уникальное имя файла
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            hash_input = f"{str(image_path)}_{top_text}_{bottom_text}_{timestamp}"
            hash_value = hashlib.md5(hash_input.encode()).hexdigest()
            filename = f"meme_{hash_value}.jpg"
            
            # Создаем директорию для мемов с текстом, если она не существует
            meme_dir = WITH_TEXT_DIR  # Используем существующую директорию для мемов с текстом
            os.makedirs(meme_dir, exist_ok=True)
            
            # Путь для сохранения
            output_path = os.path.join(meme_dir, filename)
            
            # Сохраняем изображение
            img.save(output_path, "JPEG")
            
            return output_path
            
    except Exception as e:
        logger.error(f"Ошибка при создании мема: {e}")
        return None

# Обновляем функцию, которая создает клавиатуру для изображения, добавляя кнопку "Создать мем"
def get_image_keyboard(image_index, total_images, category):
    """
    Создает клавиатуру для навигации по изображениям с кнопкой создания мема
    """
    keyboard = [
        [
            Button.inline("⬅️ Пред.", f"prev_{category}"),
            Button.inline("След. ➡️", f"next_{category}")
        ],
        [
            Button.inline("🗑️ Удалить", f"delete"),
            Button.inline("🔀 Перенести", f"move"),
            Button.inline("✏️ Создать мем", f"create_meme")  # Новая кнопка
        ],
        [
            Button.inline("🔄 Обновить", f"reload_images"),
            Button.inline("🏠 Меню", f"main_menu")
        ]
    ]
    
    return keyboard

# В функции регистрации обработчиков добавляем наш новый обработчик
def register_handlers():
    """
    Регистрирует все обработчики бота
    """
    # ... existing handlers ...
    
    # Обработчик кнопки создания мема
    bot.add_event_handler(
        create_meme_button_handler,
        events.CallbackQuery(pattern=r"create_meme")
    )
    
    # Обработчик текстовых сообщений для ввода текста мема
    bot.add_event_handler(
        message_handler,
        events.NewMessage(func=lambda e: e.is_private)
    )
    
    # ... existing handlers ...

async def main():
    """Запускает бота"""
    logger.info(f"Запуск Telegram-бота для просмотра мемов с API_ID={API_ID} и API_HASH={API_HASH[:5]}...")
    
    # Инициализация клиента
    bot = TelegramClient('meme_bot_session', API_ID, API_HASH)
    
    # Загружаем изображения при старте
    user_state['images'] = await load_images()
    
    # Регистрируем все обработчики
    
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
        
        elif data == "create_meme":
            # Если не выбрана категория, ничего не делаем
            if not user_state['current_category']:
                await event.answer("Сначала выберите категорию")
                return
            
            images = user_state['images'][user_state['current_category']]
            if not images:
                await event.answer("Нет изображений для создания мема")
                return
            
            # Получаем текущее изображение
            current_image = images[user_state['current_index']]
            
            # Сохраняем данные для дальнейшего использования
            user_id = event.sender_id
            if user_id not in user_data:
                user_data[user_id] = {}
            
            user_data[user_id]['current_image'] = current_image
            
            # Устанавливаем состояние - ожидание верхнего текста
            user_states[user_id] = AWAITING_TOP_TEXT
            
            # Отправляем сообщение с просьбой ввести текст
            await event.respond("✏️ Введите текст, который будет размещен СВЕРХУ изображения (или отправьте /cancel для отмены):")
    
    # Добавляем обработчик текстовых сообщений для создания мема
    @bot.on(events.NewMessage(func=lambda e: e.is_private))
    async def text_message_handler(event):
        """Обработчик текстовых сообщений для создания мема"""
        user_id = event.sender_id
        
        # Проверяем, является ли пользователь администратором
        if user_id != ADMIN_USER_ID:
            await event.respond("⛔ У вас нет доступа к этому боту.")
            return
        
        message_text = event.raw_text
        
        # Обрабатываем команды
        if message_text.startswith('/'):
            if message_text == '/cancel' and user_id in user_states:
                del user_states[user_id]
                if user_id in user_data:
                    user_data[user_id] = {}
                await event.respond("❌ Создание мема отменено.")
            # Для остальных команд используем существующие обработчики
            return
        
        # Обработка состояний FSM для создания мема
        if user_id in user_states:
            state = user_states[user_id]
            
            if state == AWAITING_TOP_TEXT:
                # Пользователь ввел верхний текст, сохраняем его
                user_data[user_id]['top_text'] = message_text
                
                # Меняем состояние на ожидание нижнего текста
                user_states[user_id] = AWAITING_BOTTOM_TEXT
                
                # Просим ввести нижний текст
                await event.respond("✏️ Теперь введите текст, который будет размещен СНИЗУ изображения (или отправьте /cancel для отмены):")
                return
                
            elif state == AWAITING_BOTTOM_TEXT:
                # Пользователь ввел нижний текст, сохраняем его
                user_data[user_id]['bottom_text'] = message_text
                
                # Сбрасываем состояние
                del user_states[user_id]
                
                # Создаем мем на основе введенных данных
                image_path = user_data[user_id]['current_image']
                top_text = user_data[user_id]['top_text']
                bottom_text = user_data[user_id]['bottom_text']
                
                await event.respond("🔄 Создаю мем, пожалуйста, подождите...")
                
                # Создаем мем
                meme_path = await create_meme(image_path, top_text, bottom_text)
                
                if meme_path:
                    # Отправляем мем пользователю
                    await bot.send_file(user_id, meme_path, caption="✅ Вот ваш мем!")
                    
                    # Обновляем список изображений
                    user_state['images'] = await load_images()
                    
                    logger.info(f"Создан новый мем: {meme_path}")
                else:
                    await event.respond("❌ Произошла ошибка при создании мема.")
                
                # Сбрасываем данные пользователя
                user_data[user_id] = {}
                return
    
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