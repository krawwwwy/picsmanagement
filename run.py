"""
Простой скрипт для запуска компонентов системы:
1. Парсер мемов из Telegram-каналов
2. Telegram-бот для просмотра коллекции
"""

import os
import sys
import subprocess
import time
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

def check_env_file():
    """Проверка наличия .env файла"""
    if not os.path.exists('.env'):
        print("⚠️ Файл .env не найден. Создаю из образца...")
        if os.path.exists('.env.example'):
            with open('.env.example', 'r', encoding='utf-8') as example:
                with open('.env', 'w', encoding='utf-8') as env_file:
                    env_file.write(example.read())
            print("✅ Файл .env создан из образца. Пожалуйста, отредактируйте его с вашими данными.")
        else:
            print("❌ Файл .env.example не найден. Создайте файл .env вручную.")
        return False
    return True

def check_directories():
    """Проверка наличия директорий для хранения мемов"""
    meme_dir = Path("memes")
    with_text_dir = meme_dir / "with_text"
    without_text_dir = meme_dir / "without_text"
    
    for directory in [meme_dir, with_text_dir, without_text_dir]:
        directory.mkdir(parents=True, exist_ok=True)
    
    print("✅ Директории для хранения мемов готовы.")
    return True

def run_parser():
    """Запуск парсера для загрузки мемов"""
    print("🚀 Запускаю парсер мемов из Telegram-каналов...")
    try:
        subprocess.run([sys.executable, "parser.py"], check=True)
        print("✅ Парсер успешно завершил работу.")
        return True
    except subprocess.CalledProcessError:
        print("❌ Ошибка при запуске парсера.")
        return False

def run_bot():
    """Запуск Telegram-бота для просмотра мемов"""
    print("🤖 Запускаю Telegram-бота для просмотра мемов...")
    try:
        subprocess.run([sys.executable, "bot.py"], check=True)
        return True
    except subprocess.CalledProcessError:
        print("❌ Ошибка при запуске бота.")
        return False
    except KeyboardInterrupt:
        print("🛑 Бот остановлен пользователем.")
        return True

def main():
    """Основная функция"""
    print("=" * 50)
    print("🎭 Система сбора и просмотра мемов")
    print("=" * 50)
    
    # Проверяем окружение
    if not check_env_file():
        choice = input("Продолжить без настройки .env? (y/n): ")
        if choice.lower() != 'y':
            return
    
    check_directories()
    
    while True:
        print("\nВыберите действие:")
        print("1. Запустить парсер мемов (собрать новые мемы)")
        print("2. Запустить Telegram-бота (просмотр коллекции)")
        print("3. Запустить всё сразу (сначала парсер, потом бот)")
        print("4. Выйти")
        
        choice = input("Ваш выбор (1-4): ")
        
        if choice == '1':
            run_parser()
        elif choice == '2':
            run_bot()
        elif choice == '3':
            run_parser()
            time.sleep(1)  # Небольшая пауза между запусками
            run_bot()
        elif choice == '4':
            print("Спасибо за использование! Выход...")
            break
        else:
            print("⚠️ Некорректный ввод, попробуйте снова.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Программа остановлена пользователем.")
    except Exception as e:
        print(f"\n❌ Произошла ошибка: {e}")
    finally:
        print("\nЗавершение работы программы.") 