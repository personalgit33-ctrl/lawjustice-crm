@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
where py >nul 2>nul
if errorlevel 1 (
  echo [!] Python не найден. Установите Python 3.12 с https://www.python.org/downloads/
  echo     и при установке отметьте галочку "Add python.exe to PATH". Затем запустите этот файл снова.
  pause
  exit /b 1
)
if not exist .venv (
  echo Создаю виртуальное окружение...
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
echo Устанавливаю зависимости (первый раз 1-3 минуты)...
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
python manage.py migrate
python manage.py seed
echo.
echo Бэкенд: http://localhost:8000   (не закрывайте это окно)
python -m daphne -b 127.0.0.1 -p 8000 config.asgi:application
pause
