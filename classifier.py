import os
import logging
import easyocr
from PIL import Image
import tempfile
from utils import logger

class MemeClassifier:
    def __init__(self):
        """Инициализирует классификатор с моделью для распознавания текста"""
        logger.info("Инициализация классификатора мемов...")
        # Инициализируем ридер для русского и английского языков
        # Это может занять некоторое время при первом запуске
        try:
            self.reader = easyocr.Reader(['en', 'ru'], gpu=False)
            logger.info("Модель OCR успешно инициализирована")
        except Exception as e:
            logger.error(f"Ошибка инициализации OCR: {e}")
            self.reader = None

    def has_text(self, image_path, min_confidence=0.4, min_text_length=3):
        """
        Определяет, содержит ли изображение текст
        
        Args:
            image_path: путь к изображению
            min_confidence: минимальная уверенность для детекции текста (0-1)
            min_text_length: минимальная длина текста для учета
            
        Returns:
            bool: True если найден текст, иначе False
        """
        if not self.reader:
            logger.error("OCR модель не инициализирована")
            return False
        
        try:
            # Обрабатываем изображение: масштабируем для ускорения обработки
            with Image.open(image_path) as img:
                # Если изображение слишком большое, уменьшаем для ускорения
                if max(img.size) > 1200:
                    ratio = 1200 / max(img.size)
                    new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                    img = img.resize(new_size, Image.LANCZOS)
                    
                    # Сохраняем во временный файл
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                        temp_path = tmp.name
                    
                    img.save(temp_path, 'JPEG')
                    image_path = temp_path

            # Находим текст на изображении
            results = self.reader.readtext(image_path)
            
            # Удаляем временный файл, если он существует
            if 'temp_path' in locals():
                os.unlink(temp_path)
            
            # Фильтруем результаты по уверенности и длине текста
            valid_texts = [text for _, text, conf in results 
                          if conf >= min_confidence and len(text) >= min_text_length]
            
            has_text = len(valid_texts) > 0
            logger.info(f"Изображение {image_path}: {'содержит текст' if has_text else 'без текста'}")
            
            if has_text:
                logger.debug(f"Найденный текст: {', '.join(valid_texts[:3])}")
            
            return has_text
            
        except Exception as e:
            logger.error(f"Ошибка при анализе изображения {image_path}: {e}")
            return False

# Создаем синглтон-экземпляр классификатора
classifier = MemeClassifier() 