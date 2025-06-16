import os
import logging
import easyocr
from PIL import Image
import tempfile
import cv2
import numpy as np
import re
import string
from utils import logger
import torch
import platform
import sys

class MemeClassifier:
    def __init__(self):
        """Инициализирует классификатор с моделью для распознавания текста"""
        logger.info("Инициализация классификатора мемов...")
        
        # Проверяем доступность CUDA
        self.use_gpu = torch.cuda.is_available()
        
        if self.use_gpu:
            logger.info(f"[GPU] Используется GPU: {torch.cuda.get_device_name(0)}")
            
            # Проверка версии CUDA
            cuda_version = torch.version.cuda if hasattr(torch.version, 'cuda') else "Неизвестно"
            logger.info(f"CUDA версия: {cuda_version}")
        else:
            logger.warning("[CPU] GPU не обнаружен, будет использован CPU (медленнее)")
            self._print_gpu_setup_instructions()
        
        # Проверяем OpenCV CUDA
        try:
            cv_cuda_available = cv2.cuda.getCudaEnabledDeviceCount() > 0
            if cv_cuda_available:
                logger.info("[OK] OpenCV с поддержкой CUDA доступен")
            else:
                logger.info("[!] OpenCV без поддержки CUDA")
        except (AttributeError, cv2.error):
            logger.info("[!] OpenCV собран без поддержки CUDA")
        
        # Инициализируем ридер для русского и английского языков
        try:
            # Отключаем квантизацию для более точных результатов (но требует больше памяти)
            self.reader = easyocr.Reader(['en', 'ru'], gpu=self.use_gpu, quantize=False)
            logger.info("Модель OCR успешно инициализирована")
            
            # Дополнительная проверка для pytorch
            if self.use_gpu:
                # Проверяем, действительно ли тензоры на GPU
                device = next(self.reader.detector.parameters()).device
                logger.info(f"Модель OCR использует устройство: {device}")
        except Exception as e:
            logger.error(f"Ошибка инициализации OCR: {e}")
            self.reader = None
            
            # Если ошибка связана с CUDA, попробуем с CPU
            if "CUDA" in str(e) and self.use_gpu:
                logger.warning("Ошибка при использовании GPU, пробуем с CPU...")
                try:
                    self.use_gpu = False
                    self.reader = easyocr.Reader(['en', 'ru'], gpu=False)
                    logger.info("Модель OCR успешно инициализирована на CPU")
                except Exception as e2:
                    logger.error(f"Не удалось инициализировать OCR даже на CPU: {e2}")
                    self.reader = None

    def _print_gpu_setup_instructions(self):
        """Выводит подробные инструкции по настройке CUDA"""
        os_name = platform.system()
        
        logger.info("[ИНСТРУКЦИЯ] Для ускорения работы с помощью GPU (в 10-50 раз быстрее):")
        
        # Проверка на наличие NVIDIA GPU
        if os_name == "Windows":
            logger.info("   1. Проверьте, есть ли у вас NVIDIA GPU:")
            logger.info("      - Откройте диспетчер устройств (Win+X > Диспетчер устройств)")
            logger.info("      - Посмотрите раздел 'Видеоадаптеры'")
        else:
            logger.info("   1. Проверьте, есть ли у вас NVIDIA GPU: команда lspci | grep -i nvidia")
        
        # Инструкции по установке драйверов
        if os_name == "Windows":
            logger.info("   2. Установите последние драйверы NVIDIA:")
            logger.info("      - Посетите https://www.nvidia.ru/Download/index.aspx")
            logger.info("      - Или используйте GeForce Experience для автоматического обновления")
        else:
            logger.info("   2. Установите драйверы NVIDIA для вашей системы")
        
        # Установка CUDA
        logger.info("   3. Установите CUDA Toolkit:")
        logger.info("      - Скачайте с https://developer.nvidia.com/cuda-downloads")
        logger.info("      - Рекомендуемая версия: CUDA 11.7 или 11.8")
        
        # Установка PyTorch с CUDA
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        logger.info("   4. Переустановите PyTorch с поддержкой CUDA:")
        if os_name == "Windows":
            logger.info(f"      - pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118")
        else:
            logger.info(f"      - pip install torch torchvision torchaudio")
        
        # Проверка успешной установки
        logger.info("   5. Проверьте установку:")
        logger.info("      - python -c \"import torch; print(torch.cuda.is_available())\"")
        logger.info("      - Должно вывести: True")
        
        logger.info("   Дополнительная информация: https://pytorch.org/get-started/locally/")
        
    def has_text(self, image_path, min_confidence=0.45, min_text_length=3, min_significant_texts=1):
        """
        Определяет, содержит ли изображение текст
        
        Args:
            image_path: путь к изображению
            min_confidence: минимальная уверенность для детекции текста (0-1)
            min_text_length: минимальная длина текста для учета
            min_significant_texts: минимальное количество значимых текстов, необходимых для положительной классификации
            
        Returns:
            bool: True если найден текст, иначе False
        """
        if not self.reader:
            logger.error("OCR модель не инициализирована")
            return False
        
        try:
            # Создаем несколько вариантов обработанного изображения
            processed_images = self._preprocess_image_multiple(image_path)
            
            # Результаты по всем вариантам обработки
            all_results = []
            valid_texts_total = []
            
            # Пути к обработанным изображениям
            image_paths = [img_path for img_path, _ in processed_images]
            method_names = [method_name for _, method_name in processed_images]
            
            # Пакетная обработка изображений, если доступно GPU
            batch_size = 3 if self.use_gpu else 1
            
            for i in range(0, len(image_paths), batch_size):
                batch_paths = image_paths[i:i+batch_size]
                batch_methods = method_names[i:i+batch_size]
                
                if len(batch_paths) == 1:
                    # Одно изображение - обычная обработка
                    img_path = batch_paths[0]
                    method_name = batch_methods[0]
                    
                    if not img_path:
                        continue
                        
                    # Находим текст на изображении
                    results = self.reader.readtext(img_path)
                    
                    # Фильтруем результаты по уверенности и длине текста
                    valid_texts = [text for _, text, conf in results 
                                  if conf >= min_confidence and len(text.strip()) >= min_text_length]
                    
                    # Дополнительная фильтрация результатов
                    significant_texts = self._filter_meaningful_text(valid_texts, min_length=min_text_length)
                    
                    if significant_texts:
                        logger.debug(f"Метод {method_name}: найден текст: {', '.join(significant_texts[:3])}")
                        valid_texts_total.extend(significant_texts)
                    
                    all_results.extend(results)
                else:
                    # Пакетная обработка нескольких изображений
                    # Выполняем предсказания для всех изображений в пакете
                    batch_results = []
                    
                    # EasyOCR не поддерживает нативно пакетную обработку, 
                    # но мы можем использовать torch.no_grad() для оптимизации памяти
                    with torch.no_grad():
                        for j, img_path in enumerate(batch_paths):
                            if not img_path:
                                continue
                            
                            method_name = batch_methods[j]
                            results = self.reader.readtext(img_path)
                            
                            # Фильтруем результаты
                            valid_texts = [text for _, text, conf in results 
                                          if conf >= min_confidence and len(text.strip()) >= min_text_length]
                            
                            significant_texts = self._filter_meaningful_text(valid_texts, min_length=min_text_length)
                            
                            if significant_texts:
                                logger.debug(f"Метод {method_name}: найден текст: {', '.join(significant_texts[:3])}")
                                valid_texts_total.extend(significant_texts)
                            
                            all_results.extend(results)
            
            # Очистка: удаляем временные файлы
            for img_path, _ in processed_images:
                if os.path.exists(img_path):
                    os.unlink(img_path)
            
            # Убираем дубликаты текстов
            unique_texts = list(set(valid_texts_total))
            
            # Определяем наличие текста:
            # 1. Должно быть как минимум min_significant_texts значимых текстов
            # 2. Средняя длина текста должна быть не менее 3 символов
            has_text = len(unique_texts) >= min_significant_texts and self._evaluate_text_quality(unique_texts)
            
            # Если тексты найдены, записываем в лог
            if has_text:
                logger.info(f"Изображение {image_path}: содержит текст (найдено {len(unique_texts)} текстов)")
                logger.debug(f"Найденный текст: {', '.join(unique_texts[:5])}")
            else:
                # Если тексты есть, но мы их не считаем достаточными, логируем это
                if unique_texts:
                    logger.info(f"Изображение {image_path}: без текста (найдено {len(unique_texts)} недостаточно значимых текстов)")
                    logger.debug(f"Отклоненные тексты: {', '.join(unique_texts[:5])}")
                else:
                    logger.info(f"Изображение {image_path}: без текста")
            
            return has_text
            
        except Exception as e:
            logger.error(f"Ошибка при анализе изображения {image_path}: {e}")
            return False
    
    def _evaluate_text_quality(self, texts):
        """
        Оценивает качество найденных текстов
        
        Args:
            texts: список найденных текстов
            
        Returns:
            bool: True если тексты достаточно качественные
        """
        if not texts:
            return False
        
        # Проверяем среднюю длину текстов
        avg_length = sum(len(t) for t in texts) / len(texts)
        if avg_length < 3:
            return False
            
        # Проверяем, что хотя бы один текст содержит более 5 символов
        has_long_text = any(len(t) > 5 for t in texts)
        
        # Убрана проверка на наличие нескольких слов
        return has_long_text
    
    def _filter_meaningful_text(self, texts, min_length=3):
        """
        Фильтрует тексты, оставляя только значимые
        
        Args:
            texts: список текстов для фильтрации
            min_length: минимальная длина значимого текста
            
        Returns:
            list: отфильтрованный список текстов
        """
        if not texts:
            return []
            
        meaningful_texts = []
        
        for text in texts:
            # Очистка текста от символов пунктуации и приведение к нижнему регистру
            cleaned = text.strip()
            
            # Проверяем минимальную длину
            if len(cleaned) < min_length:
                continue
                
            # Проверяем наличие букв (а не только цифр и спецсимволов)
            if not any(c.isalpha() for c in cleaned):
                continue
                
            # Проверяем, что текст не состоит только из повторяющихся символов
            if len(set(cleaned)) < 2:
                continue
                
            # Убрана проверка на осмысленность текста
            meaningful_texts.append(cleaned)
        
        return meaningful_texts
    
    def _preprocess_image_multiple(self, image_path):
        """
        Создает несколько вариантов обработки изображения для улучшения распознавания текста
        
        Args:
            image_path: путь к изображению
            
        Returns:
            list: список кортежей (путь_к_файлу, название_метода)
        """
        processed_images = []
        
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
                
                # Читаем оригинальное изображение для OpenCV
                image = cv2.imread(temp_path)
                if image is None:
                    logger.error(f"OpenCV не смог прочитать изображение: {temp_path}")
                    return [(temp_path, "оригинал")]
                
                # Проверяем, можем ли использовать CUDA для OpenCV
                try:
                    use_cv_gpu = self.use_gpu and cv2.cuda.getCudaEnabledDeviceCount() > 0
                except (AttributeError, cv2.error):
                    # Если cv2.cuda недоступен или возникла ошибка при проверке
                    use_cv_gpu = False
                    logger.debug("OpenCV CUDA модули недоступны")
                
                # 1. Оригинальное изображение
                processed_images.append((temp_path, "оригинал"))
                
                # 2. Изображение в оттенках серого
                try:
                    if use_cv_gpu:
                        # GPU версия
                        gpu_img = cv2.cuda_GpuMat()
                        gpu_img.upload(image)
                        gpu_gray = cv2.cuda.cvtColor(gpu_img, cv2.COLOR_BGR2GRAY)
                        gray = gpu_gray.download()
                    else:
                        # CPU версия
                        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                except Exception as e:
                    # В случае ошибки откатываемся к CPU версии
                    logger.debug(f"Ошибка GPU обработки (cvtColor): {e}")
                    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                
                gray_path = f"{temp_path}_gray.jpg"
                cv2.imwrite(gray_path, gray)
                processed_images.append((gray_path, "оттенки серого"))
                
                # 3. Применяем адаптивное пороговое значение (бинаризация)
                # CUDA не имеет прямого эквивалента для adaptiveThreshold, используем CPU
                thresh = cv2.adaptiveThreshold(
                    gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                    cv2.THRESH_BINARY, 11, 2
                )
                thresh_path = f"{temp_path}_thresh.jpg"
                cv2.imwrite(thresh_path, thresh)
                processed_images.append((thresh_path, "бинаризация"))
                
                # 4. Улучшаем контраст с помощью CLAHE
                try:
                    if use_cv_gpu:
                        # Проверяем наличие CUDA CLAHE модуля в OpenCV
                        if hasattr(cv2.cuda, 'createCLAHE'):
                            gpu_clahe = cv2.cuda.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                            gpu_gray = cv2.cuda_GpuMat()
                            gpu_gray.upload(gray)
                            gpu_clahe_img = gpu_clahe.apply(gpu_gray)
                            clahe_img = gpu_clahe_img.download()
                        else:
                            # Если модуль недоступен, используем CPU
                            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                            clahe_img = clahe.apply(gray)
                    else:
                        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                        clahe_img = clahe.apply(gray)
                except Exception as e:
                    # В случае ошибки откатываемся к CPU версии
                    logger.debug(f"Ошибка GPU обработки (CLAHE): {e}")
                    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                    clahe_img = clahe.apply(gray)
                
                clahe_path = f"{temp_path}_clahe.jpg"
                cv2.imwrite(clahe_path, clahe_img)
                processed_images.append((clahe_path, "CLAHE"))
                
                # Обрабатываем остальные методы с проверкой доступности GPU функций
                # и безопасным откатом к CPU версии при необходимости
                
                # 5. Применяем Canny Edge Detection для выделения границ
                edges = None
                try:
                    if use_cv_gpu and hasattr(cv2.cuda, 'createCannyEdgeDetector'):
                        gpu_gray = cv2.cuda_GpuMat()
                        gpu_gray.upload(gray)
                        gpu_edges = cv2.cuda.createCannyEdgeDetector(100, 200).detect(gpu_gray)
                        edges = gpu_edges.download()
                    else:
                        edges = cv2.Canny(gray, 100, 200)
                except Exception as e:
                    logger.debug(f"Ошибка GPU обработки (Canny): {e}")
                    edges = cv2.Canny(gray, 100, 200)
                
                edges_path = f"{temp_path}_edges.jpg"
                cv2.imwrite(edges_path, edges)
                processed_images.append((edges_path, "границы"))
                
                # 6. Используем морфологические операции для улучшения текста
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
                dilated = None
                try:
                    if use_cv_gpu and hasattr(cv2.cuda, 'dilate'):
                        gpu_thresh = cv2.cuda_GpuMat()
                        gpu_thresh.upload(thresh)
                        gpu_dilated = cv2.cuda.dilate(gpu_thresh, kernel)
                        dilated = gpu_dilated.download()
                    else:
                        dilated = cv2.dilate(thresh, kernel, iterations=1)
                except Exception as e:
                    logger.debug(f"Ошибка GPU обработки (dilate): {e}")
                    dilated = cv2.dilate(thresh, kernel, iterations=1)
                
                dilated_path = f"{temp_path}_dilated.jpg"
                cv2.imwrite(dilated_path, dilated)
                processed_images.append((dilated_path, "расширение"))
                
                # 7. Увеличиваем резкость
                sharpen = None
                try:
                    if use_cv_gpu and hasattr(cv2.cuda, 'createGaussianFilter'):
                        gpu_gray = cv2.cuda_GpuMat()
                        gpu_gray.upload(gray)
                        gpu_blur = cv2.cuda.createGaussianFilter(cv2.CV_8UC1, cv2.CV_8UC1, (5, 5), 3)
                        gpu_blurred = gpu_blur.apply(gpu_gray)
                        blur = gpu_blurred.download()
                        # Sharpen на CPU, т.к. addWeighted не всегда доступен в CUDA
                        sharpen = cv2.addWeighted(gray, 1.5, blur, -0.5, 0)
                    else:
                        blur = cv2.GaussianBlur(gray, (5, 5), 3)
                        sharpen = cv2.addWeighted(gray, 1.5, blur, -0.5, 0)
                except Exception as e:
                    logger.debug(f"Ошибка GPU обработки (sharpen): {e}")
                    blur = cv2.GaussianBlur(gray, (5, 5), 3)
                    sharpen = cv2.addWeighted(gray, 1.5, blur, -0.5, 0)
                
                sharpen_path = f"{temp_path}_sharpen.jpg"
                cv2.imwrite(sharpen_path, sharpen)
                processed_images.append((sharpen_path, "резкость"))
                
                # 8. Инвертированное изображение (для светлого текста на темном фоне)
                inverted = None
                try:
                    if use_cv_gpu and hasattr(cv2.cuda, 'bitwise_not'):
                        gpu_gray = cv2.cuda_GpuMat()
                        gpu_gray.upload(gray)
                        gpu_inverted = cv2.cuda.bitwise_not(gpu_gray)
                        inverted = gpu_inverted.download()
                    else:
                        inverted = cv2.bitwise_not(gray)
                except Exception as e:
                    logger.debug(f"Ошибка GPU обработки (invert): {e}")
                    inverted = cv2.bitwise_not(gray)
                
                inverted_path = f"{temp_path}_inverted.jpg"
                cv2.imwrite(inverted_path, inverted)
                processed_images.append((inverted_path, "инверсия"))
                
                return processed_images
                
        except Exception as e:
            logger.error(f"Ошибка при предобработке изображения: {e}")
            # В случае ошибки возвращаем оригинальный файл, если есть
            if 'temp_path' in locals() and os.path.exists(temp_path):
                return [(temp_path, "оригинал")]
            return []
            
    def _preprocess_image(self, image_path):
        """
        Устарело: используйте _preprocess_image_multiple
        Предобрабатывает изображение для улучшения распознавания текста
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