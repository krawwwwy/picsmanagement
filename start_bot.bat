@echo off
title Мем-бот Telegram
color 0A

echo ====================================
echo Запуск Telegram-бота для просмотра мемов
echo ====================================
echo.

:start
echo [%time%] Запуск бота...
python bot.py
echo.

echo [%time%] Бот остановлен с кодом %errorlevel%

if "%errorlevel%"=="0" (
    echo [%time%] Бот был остановлен корректно через команду /stop или кнопку в интерфейсе.
    echo [%time%] Для нового запуска нажмите любую клавишу или закройте окно для выхода.
    pause > nul
    goto start
) else (
    echo [%time%] Произошла ошибка или сбой бота. Код ошибки: %errorlevel%
    echo [%time%] Автоматический перезапуск через 5 секунд...
    echo [%time%] Нажмите Ctrl+C, чтобы отменить перезапуск.
    timeout /t 5 > nul
    goto start
) 