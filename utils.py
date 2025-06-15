import os
import logging
import hashlib
from pathlib import Path
from dotenv import load_dotenv
from PIL import Image

# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("meme_collector.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MemeCollector")

# Загружаем переменные окружения
load_dotenv()

# Константы
MEMES_DIR = Path("memes")
WITH_TEXT_DIR = MEMES_DIR / "with_text"
WITHOUT_TEXT_DIR = MEMES_DIR / "without_text"

# Создаем директории, если их нет
WITH_TEXT_DIR.mkdir(parents=True, exist_ok=True)
WITHOUT_TEXT_DIR.mkdir(parents=True, exist_ok=True)

def get_image_hash(image_path):
    """Генерирует хеш изображения для предотвращения дубликатов"""
    try:
        with Image.open(image_path) as img:
            # Приводим к общему размеру для сравнения
            img = img.resize((64, 64), Image.LANCZOS).convert('L')
            pixel_data = list(img.getdata())
            avg_pixel = sum(pixel_data) / len(pixel_data)
            bits = "".join(['1' if pixel > avg_pixel else '0' for pixel in pixel_data])
            # Хешируем результат
            return hashlib.md5(bits.encode()).hexdigest()
    except Exception as e:
        logger.error(f"Ошибка при генерации хеша изображения {image_path}: {e}")
        return None

def is_duplicate(image_path):
    """Проверяет, есть ли уже такое изображение в базе"""
    img_hash = get_image_hash(image_path)
    if not img_hash:
        return False
    
    # Проверка в обеих директориях
    for dir_path in [WITH_TEXT_DIR, WITHOUT_TEXT_DIR]:
        for existing_img in dir_path.glob("*.jpg"):
            if get_image_hash(existing_img) == img_hash:
                logger.info(f"Дубликат найден: {image_path} == {existing_img}")
                return True
    
    return False

def save_image(image_path, has_text):
    """Сохраняет изображение в соответствующую директорию"""
    # Если это дубликат, не сохраняем
    if is_duplicate(image_path):
        os.remove(image_path)  # Удаляем временный файл
        return False
    
    # Определяем директорию для сохранения
    target_dir = WITH_TEXT_DIR if has_text else WITHOUT_TEXT_DIR
    
    # Определяем имя файла на основе хеша
    img_hash = get_image_hash(image_path) or hashlib.md5(str(image_path).encode()).hexdigest()
    target_path = target_dir / f"{img_hash}.jpg"
    
    try:
        # Оптимизируем изображение перед сохранением
        with Image.open(image_path) as img:
            img.save(target_path, "JPEG", quality=85, optimize=True)
        
        # Удаляем временный файл
        os.remove(image_path)
        logger.info(f"Изображение сохранено: {target_path}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении изображения: {e}")
        return False 