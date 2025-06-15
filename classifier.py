import os
import logging
import easyocr
from PIL import Image
import tempfile
import cv2
import numpy as np
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

    def has_text(self, image_path, min_confidence=0.5, min_text_length=2):
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
            # Предобработка изображения
            temp_path = self._preprocess_image(image_path)
            image_to_analyze = temp_path or image_path
            
            # Находим текст на изображении
            results = self.reader.readtext(image_to_analyze)
            
            # Удаляем временный файл, если он существует
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            
            # Фильтруем результаты по уверенности и длине текста
            valid_texts = [text for _, text, conf in results 
                         if conf >= min_confidence and len(text.strip()) >= min_text_length]
            
            # Дополнительная проверка на осмысленность текста
            filtered_texts = []
            for text in valid_texts:
                # Убираем слишком короткие слова и часто ложно определяемые символы
                cleaned_text = text.strip()
                # Если после очистки осталась значимая строка, считаем текстом
                if len(cleaned_text) >= min_text_length:
                    filtered_texts.append(cleaned_text)
                    
            has_text = len(filtered_texts) > 0
            logger.info(f"Изображение {image_path}: {'содержит текст' if has_text else 'без текста'}")
            
            if has_text:
                logger.debug(f"Найденный текст: {', '.join(filtered_texts[:3])}")
                logger.debug(f"Всего найдено текстовых блоков: {len(filtered_texts)}")
            
            return has_text
            
        except Exception as e:
            logger.error(f"Ошибка при анализе изображения {image_path}: {e}")
            return False
            
    def _preprocess_image(self, image_path):
        """
        Предобрабатывает изображение для улучшения распознавания текста
        
        Args:
            image_path: путь к изображению
            
        Returns:
            str: путь к обработанному изображению или None в случае ошибки
        """
        try:
            # Открываем изображение
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
                
                # Дополнительная обработка для улучшения распознавания текста
                image = cv2.imread(temp_path)
                
                # Преобразуем в оттенки серого
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                
                # Применяем адаптивное пороговое значение
                # Это может помочь выделить текст на сложных фонах
                thresh = cv2.adaptiveThreshold(
                    gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                    cv2.THRESH_BINARY, 11, 2
                )
                
                # Применяем морфологические операции для улучшения результата
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
                opening = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
                
                # Сохраняем обработанное изображение во временный файл
                processed_path = temp_path + "_processed.jpg"
                cv2.imwrite(processed_path, opening)
                
                # Удаляем исходный временный файл
                os.unlink(temp_path)
                
                return processed_path
                
        except Exception as e:
            logger.error(f"Ошибка при предобработке изображения: {e}")
            # В случае ошибки возвращаем None, чтобы использовался оригинальный файл
            return None

# Создаем синглтон-экземпляр классификатора
classifier = MemeClassifier() 