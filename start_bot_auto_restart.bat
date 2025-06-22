@echo off
title Мем-бот с автоперезапуском
color 0B

:: Создаем папку для логов, если ее нет
if not exist logs mkdir logs

:: Имя файла лога с текущей датой и временем
set logfile=logs\bot_log_%date:~6,4%-%date:~3,2%-%date:~0,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%.txt
set logfile=%logfile: =0%

echo ====================================
echo Запуск Telegram-бота с автоперезапуском
echo Логи сохраняются в %logfile%
echo ====================================
echo.

echo Запуск Telegram-бота с автоперезапуском > %logfile%
echo Время запуска: %date% %time% >> %logfile%
echo. >> %logfile%

:start
echo [%time%] Запуск бота...
echo [%date% %time%] Запуск бота... >> %logfile%

python bot.py
set exitcode=%errorlevel%

echo. >> %logfile%
echo [%date% %time%] Бот остановлен с кодом %exitcode% >> %logfile%

if "%exitcode%"=="0" (
    echo [%time%] Бот был остановлен корректно через команду /stop или кнопку в интерфейсе.
    echo [%date% %time%] Бот был корректно остановлен. >> %logfile%
    echo.
    echo [%time%] Для перезапуска нажмите любую клавишу или закройте окно для выхода.
    pause > nul
) else (
    echo [%time%] Произошла ошибка или сбой бота. Код ошибки: %exitcode%
    echo [%date% %time%] Произошла ошибка. Код ошибки: %exitcode% >> %logfile%
    echo [%time%] Автоматический перезапуск через 10 секунд...
    echo [%date% %time%] Автоматический перезапуск через 10 секунд... >> %logfile%
    echo [%time%] Нажмите Ctrl+C для отмены перезапуска.
    timeout /t 10 > nul
)

echo. >> %logfile%
goto start 