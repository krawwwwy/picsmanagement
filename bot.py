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
import random
import json
import aiohttp
from enum import Enum, auto

# Загружаем переменные окружения
load_dotenv()

# Настройки бота
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
# URL для Ollama API (по умолчанию локальный)
OLLAMA_API_URL = os.getenv('OLLAMA_API_URL', 'http://localhost:11434/api/generate')
# Модель Ollama (по умолчанию phi3)
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'phi3')
# Пароль для доступа к боту
BOT_PASSWORD = os.getenv('BOT_PASSWORD', 'admin123')
# Канал для публикации мемов
TARGET_CHANNEL = os.getenv('TARGET_CHANNEL', '')

# Инициализация клиента - перемещаем в глобальную область видимости
bot = TelegramClient('meme_bot_session', API_ID, API_HASH)

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
AWAITING_AI_THEME = "awaiting_ai_theme"  # Состояние ожидания ввода темы для ИИ-генерации
CREATING_AI_MEME = "creating_ai_meme"  # Состояние создания мема полностью через ИИ
AWAITING_TEMPLATE_THEME = "awaiting_template_theme"  # Новое состояние - ожидаем выбор темы
AWAITING_PASSWORD = "awaiting_password"  # Новое состояние - ожидание ввода пароля
AWAITING_CUSTOM_IMAGE = "awaiting_custom_image"  # Новое состояние - ожидание загрузки пользовательской картинки
FONT_SIZE_SELECTION = "font_size_selection"  # Новое состояние - выбор размера шрифта

# Темы для шаблонов мемов
TEMPLATE_THEMES = [
    "Программирование", "Работа", "Интернет", "Отношения", 
    "Еда", "Технологии", "Животные", "Спорт",
    "Учеба", "Путешествия"
]

# Базовый размер шрифта для мемов (в процентах от высоты изображения)
DEFAULT_FONT_SIZE_PERCENT = 10  # 1/10 от высоты изображения

# Эмодзи для тем
THEME_EMOJI = {
    "программирование": "💻",
    "работа": "💼",
    "интернет": "🌐",
    "отношения": "❤️",
    "еда": "🍔",
    "технологии": "📱",
    "животные": "🐱",
    "спорт": "🏃",
    "учеба": "📚",
    "путешествия": "✈️"
}

# Функция для получения эмодзи для темы
def get_emoji_for_theme(theme):
    """Возвращает эмодзи для темы шаблона"""
    return THEME_EMOJI.get(theme.lower(), "📝")

# Словарь для хранения текущего состояния пользователя
user_states = {}

# Словарь для хранения данных пользователя (текущее изображение, тексты и т.д.)
user_data = {}

# Словарь для хранения авторизованных пользователей
authenticated_users = set()  # Множество ID пользователей, прошедших аутентификацию

# Состояние пользователя
user_state = {
    'current_category': None,  # 'with_text' или 'without_text'
    'current_index': 0,
    'images': []
}

# Список тем для случайной генерации мемов
DEFAULT_MEME_THEMES = [
    "программирование", "офисная жизнь", "технологии", "социальные сети", 
    "понедельник", "пятница", "интернет", "компьютеры", "работа из дома", 
    "совещания", "дедлайны", "кофе", "выходные", "отпуск", "отношения", 
    "университет", "школа", "друзья", "семейная жизнь", "спорт", "еда",
    "фитнес", "сон", "погода", "уборка", "шоппинг", "фильмы", "игры",
    "книги", "музыка", "путешествия", "общественный транспорт", "животные",
    "политика", "экономика", "наука", "здоровье", "космос"
]

class UserState(Enum):
    IDLE = auto()
    AWAITING_TOP_TEXT = auto()
    AWAITING_BOTTOM_TEXT = auto()
    AWAITING_AI_THEME = auto()
    AWAITING_TEMPLATE_THEME = auto()  # Новое состояние - ожидаем выбор темы

async def generate_meme_text(theme=None):
    """
    Генерирует текст для мема с помощью локальной ИИ модели через Ollama API
    
    Args:
        theme: тема для генерации (необязательно)
        
    Returns:
        tuple: (верхний_текст, нижний_текст)
    """
    # Если тема не указана, выбираем случайную
    if not theme:
        theme = random.choice(DEFAULT_MEME_THEMES)
        
    try:
        # Составляем запрос к модели
        prompt = f"""Создай короткий и смешной текст для мема на тему "{theme}".
        Формат ответа должен быть строго:
        Верхний текст: [текст]
        Нижний текст: [текст]
        
        Важно:
        - Верхний и нижний текст должны быть короткими (1-5 слов)
        - Используй формат классического мема: верхний текст описывает ситуацию, нижний - неожиданный поворот или реакцию
        - Будь остроумным и смешным
        - Не используй хештеги, эмодзи или форматирование
        - Пиши на русском языке
        """
        
        # Создаем запрос к Ollama API
        async with aiohttp.ClientSession() as session:
            try:
                # Отправляем запрос к Ollama API
                async with session.post(
                    OLLAMA_API_URL,
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": prompt,
                        "stream": False
                    },
                    timeout=aiohttp.ClientTimeout(total=30)  # Увеличиваем таймаут до 30 секунд
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        ai_response = result.get("response", "").strip()
                        logger.info(f"Ответ ИИ: {ai_response}")
                    else:
                        err_text = await response.text()
                        logger.error(f"Ошибка API Ollama: {response.status}, {err_text}")
                        return (f"Когда пытаешься использовать", f"ИИ для мема про {theme}")
            except aiohttp.ClientError as e:
                logger.error(f"Ошибка соединения с Ollama: {e}")
                # В случае ошибки соединения используем резервные шаблоны
                return get_fallback_meme_text(theme)
        
        # Парсим ответ для извлечения верхнего и нижнего текста
        top_text = ""
        bottom_text = ""
        
        for line in ai_response.split('\n'):
            line = line.strip()
            if line.lower().startswith("верхний текст:"):
                top_text = line[line.find(':')+1:].strip()
            elif line.lower().startswith("нижний текст:"):
                bottom_text = line[line.find(':')+1:].strip()
        
        # Если не удалось извлечь текст, используем резервные шаблоны
        if not top_text or not bottom_text:
            return get_fallback_meme_text(theme)
        
        return (top_text, bottom_text)
        
    except Exception as e:
        logger.error(f"Ошибка при генерации текста для мема: {e}")
        return get_fallback_meme_text(theme)

def get_fallback_meme_text(theme):
    """
    Возвращает резервные шаблоны для мемов, когда ИИ недоступен
    
    Args:
        theme: тема для генерации
        
    Returns:
        tuple: (верхний_текст, нижний_текст)
    """
    # Словарь шаблонов для разных тем
    templates = {
        "программирование": [
            ("Когда код работает", "А ты не знаешь почему"),
            ("Написал 300 строк кода", "Забыл точку с запятой"),
            ("Когда тестировал локально", "И запустил на проде"),
            ("Думал это будет простой баг", "А потратил три дня"),
            ("Когда коллега спрашивает", "Как работает твой код"),
            ("Когда нашел ответ на Stack Overflow", "И он на 10 лет старше"),
            ("Когда рассказываешь о своем коде", "Что я вообще написал"),
            ("Когда сломал продакшен", "Это не я, это Дженкинс"),
            ("Время делать коммит", "git commit -m 'it works'"),
            ("Когда код работает в первый раз", "Это подозрительно"),
        ],
        "работа": [
            ("Пятница, 17:55", "Новая важная задача"),
            ("Когда босс говорит", "Задержись ненадолго"),
            ("Когда наконец закончил проект", "А заказчик меняет требования"),
            ("Первый рабочий день", "VS Последний день перед отпуском"),
            ("Когда опаздываешь на работу", "И видишь, что босс тоже опаздывает"),
            ("Когда говоришь что болен", "И случайно лайкаешь пост начальника"),
            ("Понедельник vs Пятница", "Один человек, разные вселенные"),
            ("Когда утром нажимаешь 'отложить'", "И просыпаешься через два часа"),
            ("Когда бухгалтерия задерживает зарплату", "Я в этой компании волонтер?"),
            ("Когда на совещании говорят твое имя", "И ты притворяешься, что слушал"),
        ],
        "интернет": [
            ("Когда вводишь свой пароль", "В пятый раз"),
            ("Скорость интернета в рекламе", "Скорость интернета дома"),
            ("Нажимаешь 'не сейчас'", "Приложение всё равно спрашивает завтра"),
            ("Когда Wi-Fi пропадает", "На самом интересном месте"),
            ("Обещали оптоволокно", "А подключили как всегда"),
            ("Когда пытаешься смотреть видео в HD", "При плохом интернете"),
            ("'Ваш аккаунт взломан!'", "Введите пароль, чтобы решить проблему"),
            ("Когда сайт не загружается", "F5 F5 F5 F5 F5"),
            ("'Это займет всего 5 минут'", "Загрузка 27%..."),
            ("Когда интернет включен", "Но ничего не работает"),
        ],
        "отношения": [
            ("Когда она говорит 'все нормально'", "Я чувствую опасность"),
            ("Я: расскажи о себе", "Она: *рассказывает всю жизнь за 2 часа*"),
            ("Когда вы выбираете фильм", "Уже 2 часа"),
            ("Когда услышал имя бывшей", "Вьетнамские флешбеки"),
            ("Первое свидание vs десятое", "Как менялась моя одежда"),
            ("Когда пишешь 'ахах'", "Но даже не улыбаешься"),
            ("SMS: 'Нам нужно серьезно поговорить'", "Перебираю все грехи за жизнь"),
            ("Когда кто-то говорит твое имя в толпе", "Режим шпиона активирован"),
        ],
        "еда": [
            ("Когда готовишь по рецепту", "VS Когда это у тебя получается"),
            ("Что я заказываю онлайн", "Что приезжает"),
            ("Первый кусок пиццы", "Десятый кусок пиццы"),
            ("Я на диете", "*Заглядывает в холодильник каждые 5 минут*"),
            ("Когда закончил готовить", "И весь на кухне бардак"),
            ("Что я ем на людях", "Что я ем один дома в 3 часа ночи"),
            ("Вегетарианцам 'сделаем салат'", "*Кидает помидор на тарелку*"),
            ("Мои планы на здоровое питание", "Я в 2 часа ночи"),
        ],
        "технологии": [
            ("Новый айфон", "Моя месячная зарплата"),
            ("Что я хотел купить", "Что я могу себе позволить"),
            ("Я: мой компьютер тормозит", "IT-специалист: пробовали перезагрузить?"),
            ("Когда телефон падает экраном вниз", "Мозг: готовься к худшему"),
            ("64 ГБ памяти", "2000 фотографий моей собаки"),
            ("Заряд 1%", "Держится еще 2 часа"),
            ("Заряд 20%", "Выключается внезапно"),
            ("Использую 10 паролей", "И все равно забываю"),
        ],
        "животные": [
            ("Когда говоришь псу 'кто хороший мальчик'", "А он на самом деле хороший мальчик"),
            ("Кот в 3 часа ночи", "*Звуки хаоса*"),
            ("Что я вижу", "Что видит кот"),
            ("Собака после прогулки", "VS Собака через 5 минут дома"),
            ("Когда пытаешься сфотографировать питомца", "А он все время двигается"),
            ("Коты в интернете", "Мой кот"),
            ("Я: не буду заводить питомца", "Я через неделю: это мой сыночек"),
            ("Когда кот смотрит на пустую стену", "Что он там видит?"),
        ],
        "спорт": [
            ("Я в спортзале", "Я после спортзала"),
            ("Первый день в тренажерке", "Следующее утро"),
            ("Мои планы на пробежку", "Погода: *идет дождь*"),
            ("Что я представляю", "Как выгляжу на самом деле"),
            ("Мое лицо на беговой дорожке", "Мое сердце на беговой дорожке"),
            ("До отпуска осталась неделя", "*Бешеная тренировка*"),
            ("Купил абонемент на год", "Был в зале 3 раза"),
            ("Я после 5 минут тренировки", "Кажется я уже в форме"),
        ],
        "учеба": [
            ("Я во время лекции", "Я на экзамене"),
            ("Начало семестра", "Конец семестра"),
            ("Задание: 2000 слов", "Я на 1999 слове"),
            ("Дедлайн через месяц", "Дедлайн завтра"),
            ("Преподаватель: не списывайте", "Студенты: *смотрят друг на друга*"),
            ("Я на уроке", "Мои мысли на уроке"),
            ("Целый семестр для подготовки", "Учу всё за ночь до экзамена"),
            ("Когда учитель говорит что-то важное", "Мой мозг: запомни это... не запомнил"),
        ],
        "путешествия": [
            ("Мои планы на отпуск", "Мой бюджет"),
            ("Фото отеля на сайте", "Отель в реальности"),
            ("Я собираюсь", "VS Моя мама собирает меня"),
            ("Когда все проверил перед выездом", "А потом думаешь, что забыл паспорт"),
            ("Выезжаем на отдых", "Пробка на трассе"),
            ("Я после 12-часового перелета", "Пограничник: улыбнитесь для фото"),
            ("Планы на отпуск", "Погода: *тропический шторм*"),
            ("Чемодан при отъезде", "Чемодан при возвращении"),
        ]
    }
    
    # Для указанной темы или близкой к ней
    for key in templates:
        if key.lower() in theme.lower() or theme.lower() in key.lower():
            return random.choice(templates[key])
    
    # Если тема не найдена точно, ищем частичное совпадение
    for key in templates:
        for word in theme.lower().split():
            if word in key.lower() or key.lower() in word:
                return random.choice(templates[key])
    
    # Для случайной категории
    random_category = random.choice(list(templates.keys()))
    
    # Если тема указана, но не найдена в шаблонах, создаем общий шаблон с указанной темой
    if theme:
        generic_templates = [
            (f"Когда говорят про {theme}", "А ты понятия не имеешь что это"),
            (f"Я и мой {theme}", "Идеальная пара"),
            (f"Никто: ...", f"Я: *рассказываю всем про {theme}*"),
            (f"Когда наконец купил {theme}", "И он сразу подешевел"),
            (f"{theme} в рекламе", f"{theme} в реальности"),
            (f"Когда впервые услышал про {theme}", "VS Сейчас"),
            (f"Мои знания о {theme}", "Вопросы на экзамене"),
            (f"Мой друг: {theme} - это легко", "Я после 5 минут"),
        ]
        return random.choice(generic_templates)
    
    return random.choice(templates[random_category])

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

async def send_current_image(event, new_message=False):
    """
    Отправляет текущее изображение из выбранной категории.
    
    Args:
        event: Telegram event
        new_message: Если True, то отправляет новое сообщение вместо редактирования текущего
    """
    # Получаем текущую категорию и индекс
    category = user_state['current_category']
    index = user_state['current_index']
    
    # Проверяем наличие изображений в выбранной категории
    if not user_state['images'][category]:
        if new_message:
            await event.respond("В этой категории нет изображений.")
        else:
            await event.edit("В этой категории нет изображений.")
        return
    
    # Получаем текущее изображение
    current_image = user_state['images'][category][index]
    
    # Общее количество изображений в категории
    total_images = len(user_state['images'][category])
    
    # Создаем хэш для публикации текущего изображения
    file_hash = get_path_hash(current_image)
    
    # Создаем клавиатуру для навигации
    keyboard = [
        [
            Button.inline("⬅️", data="prev"),
            Button.inline(f"{index + 1} / {total_images}", data="count"),
            Button.inline("➡️", data="next")
        ],
        [
            Button.inline("🗑️ Удалить", data="delete"),
            Button.inline("🔄 Перенести", data="move"),
        ],
        [
            Button.inline("✏️ Создать мем", data="create_meme"),
            Button.inline("📢 Опубликовать в канал", data=f"publish_{file_hash}"),
        ],
        [
            Button.inline("🎭 Шаблоны", data="template_meme"),
            Button.inline("🤖 ИИ + Тема", data="create_meme_ai_theme"),
        ],
        [
            Button.inline("🧠 ИИ Автомат", data="create_meme_ai_auto"),
            Button.inline("📋 Меню", data="menu")
        ]
    ]
    
    # Получаем хэш файла (часть пути) для отображения в подписи
    file_name = current_image.name  # Получаем только имя файла из Path
    file_hash = file_name.split('.')[0][:8]  # Берем первые 8 символов имени файла без расширения
    
    # Создаем подпись
    caption = f"📁 Категория: {category}\n🔢 {index + 1} из {total_images}\n🆔 {file_hash}"
    
    try:
        # Используем непосредственно клиент для отправки файла
        user_id = event.sender_id
        chat_id = event.chat_id
        
        # При редактировании нужно сначала удалить старое сообщение
        if not new_message:
            try:
                await event.delete()
            except Exception as delete_error:
                logger.error(f"Не удалось удалить сообщение: {delete_error}")
                
        # Отправляем файл напрямую через бота
        sent_message = await bot.send_file(
            chat_id,
            file=str(current_image),  # Преобразуем Path в строку
            caption=caption,
            buttons=keyboard
        )
        
        # Сохраняем текущее изображение для создания мема в данных пользователя
        if user_id not in user_data:
            user_data[user_id] = {}
        user_data[user_id]['current_image'] = current_image
        
    except Exception as e:
        logger.error(f"Ошибка при отправке изображения: {e}")
        error_message = f"❌ Ошибка при отправке изображения: {str(e)[:50]}..."
        try:
            await bot.send_message(event.chat_id, error_message)
        except Exception as msg_error:
            logger.error(f"Не удалось отправить сообщение об ошибке: {msg_error}")

@bot.on(events.CallbackQuery(pattern=r"create_meme$"))
async def create_meme_button_handler(event):
    """
    Обработчик нажатия кнопки "Создать мем"
    """
    user_id = event.sender_id
    
    # Проверяем, что пользователь авторизован
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        return
    
    # Правильная проверка наличия изображения
    if not user_state['current_category'] or not user_state['images'].get(user_state['current_category']):
        await event.respond("⚠️ Сначала выберите категорию и изображение")
        return

    # Получаем текущее изображение
    current_image = user_state['images'][user_state['current_category']][user_state['current_index']]
    
    # Сохраняем текущее изображение в данных пользователя
    if user_id not in user_data:
        user_data[user_id] = {}
    
    user_data[user_id]['current_image'] = current_image
    
    # Устанавливаем состояние - ожидание верхнего текста
    user_states[user_id] = AWAITING_TOP_TEXT
    
    # Отправляем сообщение с просьбой ввести текст
    await event.respond("✏️ Введите текст, который будет размещен СВЕРХУ изображения (или отправьте /skip или skip, чтобы пропустить, или /cancel для отмены):")

@bot.on(events.NewMessage(func=lambda e: e.is_private))
async def text_message_handler(event):
    """Обработчик текстовых сообщений для создания мема"""
    user_id = event.sender_id
    message_text = event.raw_text
    
    # Добавляем отладочный лог для отслеживания входящих сообщений и состояния
    logger.info(f"Получено сообщение от пользователя {user_id}: '{message_text}', текущее состояние: {user_states.get(user_id, 'нет')}")
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_USER_ID:
        await event.respond("⛔ У вас нет доступа к этому боту.")
        return
    
    # Обрабатываем ввод пароля
    if user_id in user_states and user_states[user_id] == AWAITING_PASSWORD:
        if message_text == BOT_PASSWORD:
            # Пароль верный
            authenticated_users.add(user_id)
            user_states.pop(user_id)  # Удаляем состояние ожидания пароля
            
            await event.respond(
                "✅ Пароль принят!\n\n"
                "Выбери категорию, чтобы начать просмотр:",
                buttons=[
                    [Button.inline("С текстом", data="category_with_text")],
                    [Button.inline("Без текста", data="category_without_text")],
                    [Button.inline("Своя картинка", data="custom_image")],
                    [Button.inline("Обновить коллекцию", data="reload_images")],
                    [Button.inline("🚀 Запустить парсер", data="parse_memes")],
                    [Button.inline("🗑️ Очистить коллекцию", data="clear_menu")]
                ]
            )
            logger.info(f"Пользователь {user_id} успешно авторизовался")
        else:
            # Пароль неверный
            await event.respond("❌ Неверный пароль. Попробуйте еще раз или отправьте /cancel для отмены.")
            logger.warning(f"Попытка ввода неверного пароля от пользователя {user_id}")
        return
    
    # Проверяем авторизацию для других операций
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        return
    
    # Обрабатываем команды
    if message_text.startswith('/'):
        if message_text == '/cancel' and user_id in user_states:
            if user_states[user_id] == AWAITING_PASSWORD:
                await event.respond("❌ Авторизация отменена.")
            else:
                await event.respond("❌ Создание мема отменено.")
            del user_states[user_id]
            if user_id in user_data:
                user_data[user_id] = {}
        elif message_text == '/skip' and user_id in user_states:
            # Специальная обработка команды /skip - не выходим из обработки, а продолжаем ниже
            pass
        else:
            # Для остальных команд используем существующие обработчики
            return
    
    # Обработка состояний FSM для создания мема
    if user_id in user_states:
        state = user_states[user_id]
        logger.info(f"Обрабатываем состояние {state} для пользователя {user_id}")
        
        if state == AWAITING_TOP_TEXT:
            # Пользователь ввел верхний текст, сохраняем его
            # Проверяем, не хочет ли пользователь пропустить ввод текста
            if message_text == '/skip' or message_text == 'skip':
                user_data[user_id]['top_text'] = ""  # Пустой текст
                logger.info(f"Пользователь {user_id} пропустил ввод верхнего текста")
            else:
                user_data[user_id]['top_text'] = message_text
                logger.info(f"Сохранен верхний текст для пользователя {user_id}: '{message_text}'")
            
            # Меняем состояние на ожидание нижнего текста
            user_states[user_id] = AWAITING_BOTTOM_TEXT
            
            # Просим ввести нижний текст
            await event.respond("✏️ Теперь введите текст, который будет размещен СНИЗУ изображения (или отправьте /skip или skip, чтобы пропустить, или /cancel для отмены):")
            return
            
        elif state == AWAITING_BOTTOM_TEXT:
            # Пользователь ввел нижний текст, сохраняем его
            # Проверяем, не хочет ли пользователь пропустить ввод текста
            if message_text == '/skip' or message_text == 'skip':
                user_data[user_id]['bottom_text'] = ""  # Пустой текст
                logger.info(f"Пользователь {user_id} пропустил ввод нижнего текста")
            else:
                user_data[user_id]['bottom_text'] = message_text
                logger.info(f"Сохранен нижний текст для пользователя {user_id}: '{message_text}'")
            
            # Сбрасываем состояние
            del user_states[user_id]
            
            # Проверяем наличие всех необходимых данных
            if 'current_image' not in user_data[user_id] or 'top_text' not in user_data[user_id]:
                logger.error(f"Отсутствуют необходимые данные для создания мема у пользователя {user_id}")
                await event.respond("❌ Ошибка: отсутствуют необходимые данные для создания мема. Попробуйте снова.")
                user_data[user_id] = {}  # Очищаем данные
                return
            
            # Получаем данные для создания мема
            image_path = user_data[user_id]['current_image']
            top_text = user_data[user_id]['top_text']
            bottom_text = user_data[user_id]['bottom_text']
            
            await event.respond("🔄 Подготавливаю мем, выберите размер шрифта...")
            
            # Вместо создания мема, показываем интерфейс выбора размера шрифта
            await show_font_size_selection(event, image_path, top_text, bottom_text)
            
            return
            
        elif state == AWAITING_AI_THEME:
            # Пользователь ввел тему для генерации мема с помощью ИИ
            theme = message_text
            logger.info(f"Получена тема для ИИ-мема от пользователя {user_id}: '{theme}'")
            
            # Сбрасываем состояние
            del user_states[user_id]
            
            # Отправляем сообщение о генерации мема
            processing_message = await event.respond(f"🧠 ИИ придумывает смешной текст на тему '{theme}'... Подождите немного.")
            
            try:
                # Генерируем текст с помощью ИИ на основе темы
                top_text, bottom_text = await generate_meme_text(theme)
                
                # Обновляем сообщение о статусе
                await processing_message.edit(f"⚙️ Генерация текста завершена!\n↑ {top_text}\n↓ {bottom_text}\n\n🔄 Выберите размер шрифта...")
                
                # Создаем мем с полученным текстом
                image_path = user_data[user_id]['current_image']
                
                # Показываем интерфейс выбора размера шрифта
                await show_font_size_selection(processing_message, image_path, top_text, bottom_text)
                
            except Exception as e:
                # В случае ошибки удаляем сообщение о генерации и отправляем сообщение об ошибке
                await processing_message.delete()
                logger.error(f"Ошибка при генерации мема по теме '{theme}': {e}")
                await event.respond(f"❌ Произошла ошибка при создании мема: {str(e)[:100]}...")
            
            return
    else:
        # Если пользователь не находится в каком-либо состоянии FSM, 
        # но отправил текстовое сообщение - игнорируем его
        logger.info(f"Получено сообщение вне FSM от пользователя {user_id}: '{message_text}'")
        # Не отвечаем, чтобы не спамить пользователя

async def create_meme(image_path, top_text, bottom_text, font_size_percent=None):
    """
    Создает мем, добавляя текст сверху и снизу изображения
    
    Args:
        image_path: путь к исходному изображению
        top_text: текст для размещения сверху
        bottom_text: текст для размещения снизу
        font_size_percent: размер шрифта в процентах от высоты изображения (по умолчанию DEFAULT_FONT_SIZE_PERCENT)
        
    Returns:
        str: путь к созданному изображению или None в случае ошибки
    """
    try:
        # Если размер шрифта не указан, используем стандартный
        if font_size_percent is None:
            font_size_percent = DEFAULT_FONT_SIZE_PERCENT
            
        # Открываем изображение
        with Image.open(image_path) as img:
            # Создаем копию, чтобы не изменять оригинал
            img = img.copy()
            
            # Получаем размеры
            width, height = img.size
            
            # Создаем объект для рисования
            draw = ImageDraw.Draw(img)
            
            # Настраиваем шрифт и его размер (в процентах от высоты изображения)
            font_size = int(height * font_size_percent / 100)
            
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

async def publish_to_channel(image_path, caption=""):
    """
    Публикует изображение в канал
    
    Args:
        image_path: путь к изображению
        caption: подпись к изображению (опционально)
        
    Returns:
        bool: True - если успешно опубликовано, False - если произошла ошибка
    """
    try:
        # Проверяем, что файл существует
        if not os.path.exists(image_path):
            logger.error(f"Файл не существует: {image_path}")
            return False
            
        # Отправляем в канал без подписи
        await bot.send_file(
            TARGET_CHANNEL,
            file=str(image_path),
            caption=""  # Пустая подпись
        )
        
        logger.info(f"Изображение успешно опубликовано в канале @{TARGET_CHANNEL}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при публикации в канал: {e}")
        return False

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
            Button.inline("🔄 Перенести", f"move"),
        ],
        [
            Button.inline("✏️ Создать мем", f"create_meme")  # Новая кнопка
        ],
        [
            Button.inline("📋 Меню", data="menu")
        ]
    ]
    
    return keyboard

def register_handlers():
    """
    Регистрирует все обработчики бота
    """
    # Обработчики команд
    bot.add_event_handler(
        start_handler,
        events.NewMessage(pattern='/start')
    )
    
    bot.add_event_handler(
        logout_handler,
        events.NewMessage(pattern='/logout')
    )
    
    bot.add_event_handler(
        help_handler,
        events.NewMessage(pattern='/help')
    )
    
    # Обработчики для остановки бота
    bot.add_event_handler(
        stop_command_handler,
        events.NewMessage(pattern='/stop')
    )
    
    bot.add_event_handler(
        stop_bot_handler,
        events.CallbackQuery(pattern=r"stop_bot")
    )
    
    # Общий обработчик callback
    bot.add_event_handler(
        callback_handler,
        events.CallbackQuery()
    )
    
    # Обработчик кнопки создания мема
    bot.add_event_handler(
        create_meme_button_handler,
        events.CallbackQuery(pattern=r"create_meme$")
    )
    
    # Обработчики ИИ-генерации мемов
    bot.add_event_handler(
        create_meme_ai_theme_handler,
        events.CallbackQuery(pattern=r"create_meme_ai_theme")
    )
    
    bot.add_event_handler(
        create_meme_ai_auto_handler,
        events.CallbackQuery(pattern=r"create_meme_ai_auto")
    )
    
    # Обработчики для работы с шаблонами мемов
    bot.add_event_handler(
        template_meme_handler,
        events.CallbackQuery(pattern=r"template_meme$")
    )
    
    bot.add_event_handler(
        back_to_meme_menu_handler,
        events.CallbackQuery(pattern=r"back_to_meme_menu$")
    )
    
    bot.add_event_handler(
        handle_template_selection,
        events.CallbackQuery(pattern=r"template_")
    )
    
    # Обработчики для выбора размера шрифта
    bot.add_event_handler(
        font_smaller_handler,
        events.CallbackQuery(pattern=r"font_smaller_")
    )
    
    bot.add_event_handler(
        font_larger_handler,
        events.CallbackQuery(pattern=r"font_larger_")
    )
    
    bot.add_event_handler(
        font_confirm_handler,
        events.CallbackQuery(pattern=r"font_confirm")
    )
    
    # Обработчик текстовых сообщений для создания мема
    bot.add_event_handler(
        text_message_handler,
        events.NewMessage(func=lambda e: e.is_private)
    )

@bot.on(events.CallbackQuery(pattern=r"template_meme"))
async def template_meme_handler(event):
    """Обработчик для начала создания мема из шаблона"""
    user_id = event.sender_id
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_USER_ID:
        await event.answer("⛔ У вас нет доступа к этому боту.", alert=True)
        return
    
    # Проверяем авторизацию
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        await event.answer()
        return
    
    # Если не выбрана категория, ничего не делаем
    if not user_state['current_category']:
        await event.answer("Сначала выберите категорию")
        return
        
    # Проверяем наличие изображений
    category = user_state['current_category']
    index = user_state['current_index']
    
    if not user_state['images'][category] or len(user_state['images'][category]) == 0:
        await event.answer("⚠️ В этой категории нет изображений!")
        return
        
    current_image = user_state['images'][category][index]
    
    # Сохраняем изображение для мема
    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id]['current_image_for_meme'] = current_image
        
    # Отправляем сообщение о нажатии
    await event.answer()
    
    # Формируем кнопки для выбора темы шаблона
    buttons = [
        [Button.inline(f"{get_emoji_for_theme(theme)} {theme}", data=f"template_{theme.lower()}") 
         for theme in TEMPLATE_THEMES[i:i+2]] 
        for i in range(0, len(TEMPLATE_THEMES), 2)
    ]
    
    # Добавляем кнопку "Случайная тема"
    buttons.append([Button.inline("🎲 Случайная тема", data="template_random")])
    
    # Добавляем кнопку назад
    buttons.append([Button.inline("◀️ Назад", data="back_to_meme_menu")])
    
    # Отправляем сообщение с кнопками выбора темы
    await event.edit("🎭 Выберите тему для шаблона мема:", buttons=buttons)
    
    # Устанавливаем состояние пользователя
    user_states[user_id] = AWAITING_TEMPLATE_THEME

@bot.on(events.CallbackQuery(pattern=r"back_to_meme_menu"))
async def back_to_meme_menu_handler(event):
    """
    Обработчик для возврата в меню создания мема
    """
    user_id = event.sender_id
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_USER_ID:
        await event.answer("⛔ У вас нет доступа к этому боту.", alert=True)
        return
    
    # Проверяем авторизацию
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        await event.answer()
        return
    
    # Сбрасываем состояние
    if user_id in user_states:
        user_states[user_id] = None
    
    try:
        # Удаляем текущее сообщение, так как event.edit не может изменять медиа
        await event.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
    
    # Возвращаемся к показу изображения с кнопками для создания мема
    await send_current_image(event, new_message=True)

@bot.on(events.CallbackQuery(pattern=r"template_"))
async def handle_template_selection(event):
    """
    Обработчик выбора шаблона для мема
    """
    user_id = event.sender_id
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_USER_ID:
        await event.answer("⛔ У вас нет доступа к этому боту.", alert=True)
        return
    
    # Проверяем авторизацию
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        await event.answer()
        return
    
    # Проверяем состояние пользователя
    if user_id not in user_states or user_states[user_id] != AWAITING_TEMPLATE_THEME:
        await event.answer("Сначала выберите опцию создания мема по шаблону")
        return
    
    # Получаем выбранную категорию
    data = event.data.decode('utf-8')
    category = data.split("_")[1]
    
    # Отправляем уведомление
    await event.answer(f"Выбрана тема: {category}")
    
    # Отображаем статус
    await event.edit(f"⏳ Создаем мем с темой '{category}'...")
    
    try:
        # Если выбрана случайная тема
        if category == "random":
            # Получаем случайную категорию из списка
            category = random.choice([theme.lower() for theme in TEMPLATE_THEMES])
        
        # Получаем текст для мема
        top_text, bottom_text = get_fallback_meme_text(category)
        
        # Проверяем наличие изображения
        image_path = user_data[user_id].get('current_image_for_meme')
        if not image_path:
            await event.edit(text="⚠️ Изображение не найдено. Пожалуйста, выберите изображение и попробуйте снова.")
            return
        
        # Обновляем сообщение о статусе
        await event.edit(f"✅ Получен текст для мема:\n↑ {top_text}\n↓ {bottom_text}\n\n🔄 Выберите размер шрифта...")
        
        # Показываем интерфейс выбора размера шрифта
        await show_font_size_selection(event, image_path, top_text, bottom_text)
        
        # Очищаем состояние
        user_states[user_id] = None
        if 'current_image_for_meme' in user_data[user_id]:
            del user_data[user_id]['current_image_for_meme']
            
    except Exception as e:
        logger.error(f"Ошибка при создании мема по шаблону: {e}")
        await event.edit(f"❌ Ошибка при создании мема: {str(e)}", 
        buttons=[
            [Button.inline("◀️ Назад", data="back_to_meme_menu")]
        ])
        user_states[user_id] = None

@bot.on(events.CallbackQuery(pattern=r"create_meme_ai_theme"))
async def create_meme_ai_theme_handler(event):
    """
    Обработчик для создания мема с помощью ИИ по заданной теме
    """
    # Проверяем, что это администратор
    user_id = event.sender_id
    if user_id != ADMIN_USER_ID:
        await event.answer("⛔ У вас нет доступа к этому боту.", alert=True)
        return
    
    # Проверяем авторизацию
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        await event.answer()
        return
    
    # Проверяем наличие текущей категории и изображения
    if not user_state['current_category']:
        await event.answer("⚠️ Сначала выберите категорию!")
        return
        
    # Получаем текущее изображение
    category = user_state['current_category']
    index = user_state['current_index']
    
    if not user_state['images'][category] or len(user_state['images'][category]) == 0:
        await event.answer("⚠️ В этой категории нет изображений!")
        return
        
    current_image = user_state['images'][category][index]
    
    # Проверяем доступность Ollama API
    try:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    OLLAMA_API_URL,
                    json={"model": OLLAMA_MODEL, "prompt": "Привет", "stream": False},
                    timeout=aiohttp.ClientTimeout(total=2)  # Таймаут 2 секунды для проверки
                ) as response:
                    if response.status != 200:
                        # Если API недоступен, предлагаем использовать шаблоны
                        await event.edit(
                            "⚠️ Сервер Ollama не отвечает. Используйте шаблоны или запустите Ollama:",
                            buttons=[
                                [Button.inline("🎭 Использовать шаблоны", data="template_meme")],
                                [Button.inline("◀️ Назад", data="back_to_meme_menu")]
                            ]
                        )
                        return
            except Exception as e:
                logger.error(f"Ошибка при проверке Ollama API: {e}")
                # В случае ошибки соединения также предлагаем шаблоны
                await event.edit(
                    "⚠️ Не удалось подключиться к серверу Ollama. Используйте шаблоны или запустите Ollama:",
                    buttons=[
                        [Button.inline("🎭 Использовать шаблоны", data="template_meme")],
                        [Button.inline("◀️ Назад", data="back_to_meme_menu")]
                    ]
                )
                return
    except Exception as e:
        logger.error(f"Общая ошибка при проверке Ollama API: {e}")
        await event.edit(
            "⚠️ Ошибка при проверке Ollama. Используйте шаблоны:",
            buttons=[
                [Button.inline("🎭 Использовать шаблоны", data="template_meme")],
                [Button.inline("◀️ Назад", data="back_to_meme_menu")]
            ]
        )
        return
    
    # Сохраняем текущее изображение для мема
    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id]['current_image'] = current_image
    
    # Изменяем сообщение и ждем ввода темы
    await event.edit(
        "🤖 Введите тему для создания мема с помощью ИИ:",
        buttons=[
            [Button.inline("❌ Отмена", data="back_to_meme_menu")]
        ]
    )
    
    # Устанавливаем состояние пользователя
    user_states[user_id] = AWAITING_AI_THEME

@bot.on(events.CallbackQuery(pattern=r"create_meme_ai_auto"))
async def create_meme_ai_auto_handler(event):
    """
    Обработчик для автоматического создания мема с помощью ИИ (без ввода темы)
    """
    # Проверяем, что это администратор
    user_id = event.sender_id
    if user_id != ADMIN_USER_ID:
        await event.answer("⛔ У вас нет доступа к этому боту.", alert=True)
        return
    
    # Проверяем авторизацию
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        await event.answer()
        return
    
    # Проверяем наличие текущей категории и изображения
    if not user_state['current_category']:
        await event.answer("⚠️ Сначала выберите категорию!")
        return
        
    # Получаем текущее изображение
    category = user_state['current_category']
    index = user_state['current_index']
    
    if not user_state['images'][category] or len(user_state['images'][category]) == 0:
        await event.answer("⚠️ В этой категории нет изображений!")
        return
        
    current_image = user_state['images'][category][index]
    
    # Проверяем доступность Ollama API
    try:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    OLLAMA_API_URL,
                    json={"model": OLLAMA_MODEL, "prompt": "Привет", "stream": False},
                    timeout=aiohttp.ClientTimeout(total=2)  # Таймаут 2 секунды для проверки
                ) as response:
                    if response.status != 200:
                        # Если API недоступен, предлагаем использовать шаблоны
                        await event.edit(
                            "⚠️ Сервер Ollama не отвечает. Используйте шаблоны или запустите Ollama:",
                            buttons=[
                                [Button.inline("🎭 Использовать шаблоны", data="template_meme")],
                                [Button.inline("◀️ Назад", data="back_to_meme_menu")]
                            ]
                        )
                        return
            except Exception as e:
                logger.error(f"Ошибка при проверке Ollama API: {e}")
                # В случае ошибки соединения также предлагаем шаблоны
                await event.edit(
                    "⚠️ Не удалось подключиться к серверу Ollama. Используйте шаблоны или запустите Ollama:",
                    buttons=[
                        [Button.inline("🎭 Использовать шаблоны", data="template_meme")],
                        [Button.inline("◀️ Назад", data="back_to_meme_menu")]
                    ]
                )
                return
    except Exception as e:
        logger.error(f"Общая ошибка при проверке Ollama API: {e}")
        await event.edit(
            "⚠️ Ошибка при проверке Ollama. Используйте шаблоны:",
            buttons=[
                [Button.inline("🎭 Использовать шаблоны", data="template_meme")],
                [Button.inline("◀️ Назад", data="back_to_meme_menu")]
            ]
        )
        return
    
    # Изменяем сообщение, чтобы показать, что мем создается
    await event.edit("⏳ Генерирую текст для мема с помощью ИИ...")
    
    try:
        # Генерируем текст мема
        top_text, bottom_text = await generate_meme_text()
        
        # Уведомляем о прогрессе
        await event.edit(f"✅ Текст сгенерирован:\n↑ {top_text}\n↓ {bottom_text}\n\n🔄 Выберите размер шрифта...")
        
        # Сохраняем текущее изображение для мема
        if user_id not in user_data:
            user_data[user_id] = {}
        
        # Показываем интерфейс выбора размера шрифта
        await show_font_size_selection(event, current_image, top_text, bottom_text)
        
    except Exception as e:
        logger.error(f"Ошибка при создании мема с ИИ: {e}")
        await event.edit(
            f"❌ Ошибка при генерации текста для мема: {str(e)}",
            buttons=[
                [Button.inline("🔙 Вернуться", data="back_to_meme_menu")]
            ]
        )
        # Очищаем состояние пользователя
        user_states[user_id] = None

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """Обработчик команды /start"""
    # Проверяем, что запрос от известного пользователя
    user_id = event.sender_id
    
    if user_id == ADMIN_USER_ID and user_id in authenticated_users:
        # Если это администратор и он уже авторизован
        await event.respond(
            "👋 Привет! Я помогу тебе просматривать и сортировать мемы.\n\n"
            "Выбери категорию, чтобы начать просмотр:",
            buttons=[
                [Button.inline("С текстом", data="category_with_text")],
                [Button.inline("Без текста", data="category_without_text")],
                [Button.inline("Своя картинка", data="custom_image")],
                [Button.inline("Обновить коллекцию", data="reload_images")],
                [Button.inline("🚀 Запустить парсер", data="parse_memes")],
                [Button.inline("🗑️ Очистить коллекцию", data="clear_menu")],
                [Button.inline("🛑 Остановить бота", data="stop_bot")]
            ]
        )
    elif user_id == ADMIN_USER_ID:
        # Если это администратор, но он еще не авторизован
        await event.respond("🔒 Для доступа к боту введите пароль:")
        user_states[user_id] = AWAITING_PASSWORD
    else:
        # Если это не администратор
        await event.respond("🔒 У вас нет доступа к этому боту.")
        
    logger.info(f"Пользователь {user_id} запустил бота")

@bot.on(events.NewMessage(pattern='/logout'))
async def logout_handler(event):
    """Обработчик для выхода из системы"""
    user_id = event.sender_id
    
    if user_id in authenticated_users:
        authenticated_users.remove(user_id)
        await event.respond("🔒 Вы вышли из системы. Чтобы войти снова, отправьте /start")
    else:
        await event.respond("Вы не были авторизованы")
        
@bot.on(events.NewMessage(pattern='/help'))
async def help_handler(event):
    """Обработчик команды /help"""
    # Проверяем, что это администратор и он авторизован
    user_id = event.sender_id
    
    if user_id != ADMIN_USER_ID or user_id not in authenticated_users:
        await event.respond("🔒 У вас нет доступа к этому боту. Отправьте /start для ввода пароля.")
        return
    
    await event.respond(
        "📚 **Команды бота:**\n\n"
        "/start - начать работу с ботом\n"
        "/help - показать эту справку\n"
        "/logout - выйти из системы\n"
        "/stop - остановить бота\n"
        "/skip - пропустить ввод текста при создании мема (можно также просто ввести 'skip')\n"
        "/parse - запустить парсер для сбора новых мемов из каналов\n"
        "/clear - управление коллекцией мемов (очистка)\n\n"
        "**Навигация:**\n"
        "⬅️/➡️ кнопки - переключение между мемами\n"
        "🗑️ - удаление мема\n"
        "🔄 - перенос мема в другую категорию\n\n"
        "**Создание мемов:**\n"
        "✏️ Создать мем - ручной ввод текста\n"
        "🎭 Шаблоны - выбор готовых шаблонов по темам\n"
        "🤖 ИИ + Тема - генерация текста по указанной теме с помощью ИИ\n"
        "🧠 ИИ Автомат - автоматическая генерация текста с помощью ИИ\n"
        "📏 Размер шрифта - после создания мема можно настроить размер шрифта\n\n"
        "**Доступные темы для шаблонов:**\n"
        "💻 Программирование, 💼 Работа, 🌐 Интернет, ❤️ Отношения, "
        "🍔 Еда, 📱 Технологии, 🐱 Животные, 🏃 Спорт, 📚 Учеба, ✈️ Путешествия\n\n"
        "Используйте кнопки для навигации по коллекции мемов."
    )

@bot.on(events.CallbackQuery())
async def callback_handler(event):
    """Обработчик callback-запросов от кнопок"""
    user_id = event.sender_id
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_USER_ID:
        await event.answer("⛔ У вас нет доступа к этому боту.", alert=True)
        return
    
    # Проверяем авторизацию
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        await event.answer()
        return
    
    data = event.data.decode('utf-8')
    logger.info(f"Получен callback: {data}")
    
    # Сначала отправляем уведомление о нажатии
    if data != "count":
        await event.answer(f"Выбрано: {data}")
    
    if data == "menu":
        await event.edit(
            "Выбери категорию для просмотра:",
            buttons=[
                [Button.inline("С текстом", data="category_with_text")],
                [Button.inline("Без текста", data="category_without_text")],
                [Button.inline("Своя картинка", data="custom_image")],
                [Button.inline("Обновить коллекцию", data="reload_images")],
                [Button.inline("🚀 Запустить парсер", data="parse_memes")],
                [Button.inline("🗑️ Очистить коллекцию", data="clear_menu")],
                [Button.inline("🛑 Остановить бота", data="stop_bot")]
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
                [Button.inline("Без текста", data="category_without_text")],
                [Button.inline("Своя картинка", data="custom_image")],
                [Button.inline("🚀 Запустить парсер", data="parse_memes")],
                [Button.inline("🗑️ Очистить коллекцию", data="clear_menu")],
                [Button.inline("🛑 Остановить бота", data="stop_bot")]
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
                    user_state['current_index'] = 0
                await send_current_image(event)
            else:
                await event.edit(f"В категории больше нет мемов.", buttons=[
                    [Button.inline("Вернуться в меню", data="menu")]
                ])
                
        except Exception as e:
            logger.error(f"Ошибка при перемещении мема: {e}")
            await event.answer(f"Ошибка при перемещении: {str(e)[:50]}...")

    elif data == "custom_image":
        # Устанавливаем состояние ожидания загрузки картинки
        user_states[user_id] = AWAITING_CUSTOM_IMAGE
        
        # Инициализируем данные пользователя, если их еще нет
        if user_id not in user_data:
            user_data[user_id] = {}
        
        await event.edit(
            "📷 Отправьте мне изображение, которое хотите использовать в качестве основы для мема.\n"
            "Вы можете отправить фото из галереи или отправить его как файл.\n\n"
            "Для отмены отправьте /cancel."
        )
        
    elif data == "category_with_text":
        user_state['current_category'] = 'with_text'
        user_state['current_index'] = 0
        await send_current_image(event)

# Обработчик файлов (для получения пользовательских изображений)
@bot.on(events.NewMessage(func=lambda e: e.is_private and (e.photo or e.document)))
async def handle_media(event):
    """Обработчик для получения изображений от пользователя"""
    user_id = event.sender_id
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_USER_ID:
        await event.respond("⛔ У вас нет доступа к этому боту.")
        return
    
    # Проверяем авторизацию
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        return
    
    # Проверяем, ожидаем ли мы изображение от пользователя
    if user_id not in user_states or user_states[user_id] != AWAITING_CUSTOM_IMAGE:
        await event.respond("Я не ожидаю изображения от вас. Для создания мема со своей картинкой, выберите соответствующую опцию в меню.")
        return
    
    # Сообщаем о загрузке
    processing_msg = await event.respond("⏳ Загружаю изображение, подождите...")
    
    try:
        # Проверяем, что это изображение
        is_photo = False
        
        if event.photo:
            # Если это фото из Telegram
            is_photo = True
            media = event.photo
        elif event.document and event.document.mime_type and event.document.mime_type.startswith("image/"):
            # Если это документ с MIME-типом изображения
            is_photo = True
            media = event.document
        
        if not is_photo:
            await processing_msg.edit("❌ Отправленный файл не является изображением. Пожалуйста, отправьте фотографию.")
            return
        
        # Создаем временную директорию, если не существует
        temp_dir = os.path.join(os.getcwd(), "temp")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Создаем уникальное имя файла
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        file_hash = hashlib.md5(f"{user_id}_{timestamp}".encode()).hexdigest()
        file_path = os.path.join(temp_dir, f"custom_img_{file_hash}.jpg")
        
        # Загружаем изображение
        await bot.download_media(message=event.message, file=file_path)
        
        # Сохраняем путь к изображению в данных пользователя
        user_data[user_id]['current_image'] = file_path
        
        # Меняем состояние на ожидание верхнего текста
        user_states[user_id] = AWAITING_TOP_TEXT
        
        # Удаляем сообщение о загрузке и отправляем превью изображения
        await processing_msg.delete()
        
        # Отправляем превью и просим ввести верхний текст
        await bot.send_file(
            user_id,
            file=file_path,
            caption="✅ Изображение загружено! Теперь введите текст, который будет размещен СВЕРХУ изображения (или отправьте /skip или skip, чтобы пропустить, или /cancel для отмены):"
        )
        
        logger.info(f"Пользователь {user_id} загрузил изображение: {file_path}")
        
    except Exception as e:
        await processing_msg.edit(f"❌ Произошла ошибка при обработке изображения: {str(e)[:100]}...")
        logger.error(f"Ошибка при обработке пользовательского изображения: {e}")
        # Сбрасываем состояние
        del user_states[user_id]

async def main():
    """Запускает бота"""
    logger.info(f"Запуск Telegram-бота для просмотра мемов с API_ID={API_ID} и API_HASH={API_HASH[:5]}...")
    
    # Загружаем изображения при старте
    user_state['images'] = await load_images()
    
    # Обработчики уже зарегистрированы через декораторы @bot.on()
    logger.info("Обработчики бота зарегистрированы через декораторы")
    
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

# Обработчик для публикации мема или изображения в канал
@bot.on(events.CallbackQuery(pattern=r"publish_"))
async def publish_handler(event):
    """
    Обработчик для публикации мема или изображения в канал
    """
    user_id = event.sender_id
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_USER_ID:
        await event.answer("⛔ У вас нет доступа к этому боту.", alert=True)
        return
    
    # Проверяем авторизацию
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        await event.answer()
        return
    
    # Отправляем уведомление о том, что началась публикация
    await event.answer("📢 Отправка в канал...")
    
    # Получаем путь к изображению
    data = event.data.decode('utf-8')
    
    # Извлекаем хэш или используем last_meme
    image_path = None
    
    # Проверяем есть ли сохраненный мем у пользователя
    if user_id in user_data and 'last_meme' in user_data[user_id]:
        image_path = user_data[user_id]['last_meme']
    else:
        # Если нет сохранённого пути, извлекаем хэш из данных кнопки
        try:
            # Формат данных: publish_hash
            hash_value = data.split('_', 1)[1]
            if hash_value in meme_path_hash_map:
                image_path = meme_path_hash_map[hash_value]
            else:
                await event.edit("❌ Не удалось найти изображение для публикации.")
                return
        except Exception as e:
            logger.error(f"Ошибка при извлечении хэша изображения: {e}")
            await event.edit("❌ Не удалось найти изображение для публикации.")
            return
    
    # Проверяем существование файла
    if not os.path.exists(image_path):
        await event.edit("❌ Файл не найден. Возможно, он был удален.")
        return
    
    # Определяем, это мем или исходное изображение
    is_meme = "meme_" in os.path.basename(image_path)
    
    # Отправляем статус
    processing_msg = await event.edit("📤 Публикация изображения в канал @" + TARGET_CHANNEL + "...")
    
    # Публикуем в канал
    success = await publish_to_channel(image_path, "")
    
    if success:
        # Если публикация успешна
        await processing_msg.edit(
            f"✅ Изображение успешно опубликовано в канале @{TARGET_CHANNEL}!",
            buttons=[
                [Button.inline("📷 Создать еще мем", data="create_meme")],
                [Button.inline("🔄 Вернуться к просмотру", data="back_to_meme_menu" if is_meme else "menu")],
                [Button.inline("📋 Главное меню", data="menu")]
            ]
        )
    else:
        # Если произошла ошибка
        file_hash = get_path_hash(image_path)
        await processing_msg.edit(
            f"❌ Не удалось опубликовать изображение в канале @{TARGET_CHANNEL}.",
            buttons=[
                [Button.inline("🔄 Попробовать снова", data=f"publish_{file_hash}")],
                [Button.inline("📋 Главное меню", data="menu")]
            ]
        )

# Словарь для хранения соответствия хэшей и путей к файлам мемов
meme_path_hash_map = {}

def get_path_hash(file_path):
    """
    Создает короткий хэш для пути к файлу и сохраняет соответствие в словаре
    
    Args:
        file_path: полный путь к файлу
        
    Returns:
        str: короткий хэш для использования в callback data
    """
    # Создаем короткий MD5 хэш пути
    hash_obj = hashlib.md5(str(file_path).encode())
    short_hash = hash_obj.hexdigest()[:8]
    
    # Сохраняем соответствие хэша и пути
    meme_path_hash_map[short_hash] = str(file_path)
    
    return short_hash

@bot.on(events.CallbackQuery(pattern=r"stop_bot"))
async def stop_bot_handler(event):
    """Обработчик для полной остановки бота"""
    user_id = event.sender_id
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_USER_ID:
        await event.answer("⛔ У вас нет доступа к этой функции.", alert=True)
        return
    
    # Проверяем авторизацию
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        await event.answer()
        return
    
    await event.edit("🛑 Останавливаю бота...")
    await asyncio.sleep(1)  # Дадим время для отображения сообщения
    logger.info("Бот остановлен по команде пользователя")
    
    # Прерываем работу бота
    await bot.disconnect()
    await event.client.disconnect()
    
    # Завершаем программу полностью
    import sys
    sys.exit(0)

@bot.on(events.NewMessage(pattern='/stop'))
async def stop_command_handler(event):
    """Обработчик команды /stop для остановки бота"""
    user_id = event.sender_id
    
    # Проверяем, что это администратор и он авторизован
    if user_id != ADMIN_USER_ID:
        await event.respond("🔒 У вас нет доступа к этому боту.")
        return
    
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        return
    
    await event.respond("🛑 Останавливаю бота...")
    logger.info("Бот остановлен по команде пользователя")
    
    # Небольшая задержка для того, чтобы сообщение успело отправиться
    await asyncio.sleep(1)
    
    # Прерываем работу бота
    await bot.disconnect()
    
    # Завершаем программу полностью
    import sys
    sys.exit(0)

async def show_font_size_selection(event, meme_path, top_text, bottom_text, font_size_percent=None):
    """
    Отображает интерфейс выбора размера шрифта для мема
    
    Args:
        event: Telegram event
        meme_path: путь к исходному изображению (не к мему!)
        top_text: верхний текст мема
        bottom_text: нижний текст мема
        font_size_percent: текущий размер шрифта в процентах
    """
    user_id = event.sender_id
    
    # Если размер шрифта не указан, используем стандартный
    if font_size_percent is None:
        font_size_percent = DEFAULT_FONT_SIZE_PERCENT
    
    # Сохраняем данные в user_data
    if user_id not in user_data:
        user_data[user_id] = {}
    
    user_data[user_id]['meme_source'] = meme_path
    user_data[user_id]['top_text'] = top_text
    user_data[user_id]['bottom_text'] = bottom_text
    user_data[user_id]['font_size_percent'] = font_size_percent
    
    # Создаем мем с текущим размером шрифта
    new_meme_path = await create_meme(meme_path, top_text, bottom_text, font_size_percent)
    
    if not new_meme_path:
        await event.respond("❌ Произошла ошибка при создании мема.")
        return
    
    # Сохраняем путь к созданному мему
    user_data[user_id]['last_meme'] = new_meme_path
    
    # Создаем хэш для пути к файлу для публикации
    file_hash = get_path_hash(new_meme_path)
    
    # Устанавливаем состояние пользователя
    user_states[user_id] = FONT_SIZE_SELECTION
    
    # Отправляем мем с кнопками регулировки размера шрифта
    buttons = [
        [Button.inline("🔍 Уменьшить шрифт", data=f"font_smaller_{font_size_percent}")],
        [Button.inline("🔎 Увеличить шрифт", data=f"font_larger_{font_size_percent}")],
        [Button.inline("✅ Подтвердить", data=f"font_confirm")],
        [Button.inline("❌ Отмена", data="back_to_meme_menu")]
    ]
    
    try:
        # Пробуем удалить предыдущее сообщение (если вызываем через callback)
        if hasattr(event, 'delete'):
            await event.delete()
    except Exception as e:
        logger.error(f"Не удалось удалить сообщение: {e}")
    
    # Отправляем мем с кнопками выбора размера шрифта
    await bot.send_file(
        user_id,
        file=str(new_meme_path),
        caption=f"📏 Текущий размер шрифта: {font_size_percent}% от высоты изображения.\nВыберите действие:",
        buttons=buttons
    )

@bot.on(events.CallbackQuery(pattern=r"font_smaller_"))
async def font_smaller_handler(event):
    """Обработчик для уменьшения размера шрифта"""
    user_id = event.sender_id
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_USER_ID:
        await event.answer("⛔ У вас нет доступа к этому боту.", alert=True)
        return
    
    # Проверяем авторизацию
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        await event.answer()
        return
    
    # Проверяем, находится ли пользователь в состоянии выбора размера шрифта
    if user_id not in user_states or user_states[user_id] != FONT_SIZE_SELECTION:
        await event.answer("Сначала выберите опцию создания мема")
        return
    
    # Проверяем, есть ли необходимые данные
    if user_id not in user_data or 'font_size_percent' not in user_data[user_id]:
        await event.answer("Ошибка: данные о размере шрифта не найдены")
        return
    
    # Получаем текущий размер шрифта из callback data
    data = event.data.decode('utf-8')
    current_size = float(data.split('_')[2])
    
    # Уменьшаем размер шрифта на 1%, но не меньше 5%
    new_size = max(5, current_size - 1)
    
    # Если размер не изменился, уведомляем пользователя
    if new_size == current_size:
        await event.answer("Достигнут минимальный размер шрифта")
        return
    
    # Получаем данные для создания нового мема
    meme_source = user_data[user_id]['meme_source']
    top_text = user_data[user_id]['top_text']
    bottom_text = user_data[user_id]['bottom_text']
    
    # Показываем уведомление пользователю
    await event.answer(f"Размер шрифта уменьшен до {new_size}%")
    
    # Отображаем новый интерфейс выбора размера шрифта
    await show_font_size_selection(event, meme_source, top_text, bottom_text, new_size)

@bot.on(events.CallbackQuery(pattern=r"font_larger_"))
async def font_larger_handler(event):
    """Обработчик для увеличения размера шрифта"""
    user_id = event.sender_id
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_USER_ID:
        await event.answer("⛔ У вас нет доступа к этому боту.", alert=True)
        return
    
    # Проверяем авторизацию
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        await event.answer()
        return
    
    # Проверяем, находится ли пользователь в состоянии выбора размера шрифта
    if user_id not in user_states or user_states[user_id] != FONT_SIZE_SELECTION:
        await event.answer("Сначала выберите опцию создания мема")
        return
    
    # Проверяем, есть ли необходимые данные
    if user_id not in user_data or 'font_size_percent' not in user_data[user_id]:
        await event.answer("Ошибка: данные о размере шрифта не найдены")
        return
    
    # Получаем текущий размер шрифта из callback data
    data = event.data.decode('utf-8')
    current_size = float(data.split('_')[2])
    
    # Увеличиваем размер шрифта на 1%, но не больше 25%
    new_size = min(25, current_size + 1)
    
    # Если размер не изменился, уведомляем пользователя
    if new_size == current_size:
        await event.answer("Достигнут максимальный размер шрифта")
        return
    
    # Получаем данные для создания нового мема
    meme_source = user_data[user_id]['meme_source']
    top_text = user_data[user_id]['top_text']
    bottom_text = user_data[user_id]['bottom_text']
    
    # Показываем уведомление пользователю
    await event.answer(f"Размер шрифта увеличен до {new_size}%")
    
    # Отображаем новый интерфейс выбора размера шрифта
    await show_font_size_selection(event, meme_source, top_text, bottom_text, new_size)

@bot.on(events.CallbackQuery(pattern=r"font_confirm"))
async def font_confirm_handler(event):
    """Обработчик подтверждения размера шрифта и завершения создания мема"""
    user_id = event.sender_id
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_USER_ID:
        await event.answer("⛔ У вас нет доступа к этому боту.", alert=True)
        return
    
    # Проверяем авторизацию
    if user_id not in authenticated_users:
        await event.respond("🔒 Вы не авторизованы. Отправьте /start для ввода пароля.")
        await event.answer()
        return
    
    # Проверяем, находится ли пользователь в состоянии выбора размера шрифта
    if user_id not in user_states or user_states[user_id] != FONT_SIZE_SELECTION:
        await event.answer("Сначала выберите опцию создания мема")
        return
    
    # Проверяем, есть ли необходимые данные
    if user_id not in user_data or 'last_meme' not in user_data[user_id]:
        await event.answer("Ошибка: данные о меме не найдены")
        return
    
    # Получаем путь к созданному мему
    meme_path = user_data[user_id]['last_meme']
    
    # Получаем информацию о шрифте для подписи
    font_size_percent = user_data[user_id].get('font_size_percent', DEFAULT_FONT_SIZE_PERCENT)
    
    # Создаем хэш для пути к файлу для публикации
    file_hash = get_path_hash(meme_path)
    
    # Удаляем состояние выбора шрифта
    del user_states[user_id]
    
    # Пытаемся удалить текущее сообщение
    try:
        await event.delete()
    except Exception as e:
        logger.error(f"Не удалось удалить сообщение: {e}")
    
    # Отправляем готовый мем с кнопками для дальнейших действий
    await bot.send_file(
        user_id,
        file=str(meme_path),
        caption=f"✅ Мем создан! Размер шрифта: {font_size_percent}%",
        buttons=[
            [Button.inline("📷 Создать еще мем", data="create_meme")],
            [Button.inline("📢 Опубликовать в канал", data=f"publish_{file_hash}")],
            [Button.inline("🔄 Вернуться к просмотру", data="back_to_meme_menu")],
            [Button.inline("📋 Главное меню", data="menu")]
        ]
    )
    
    # Обновляем список изображений
    user_state['images'] = await load_images()

if __name__ == "__main__":
    # Запускаем асинхронную функцию в event loop
    asyncio.run(main()) 