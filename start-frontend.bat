@echo off
chcp 65001 >nul
cd /d "%~dp0frontend"
where npm >nul 2>nul
if errorlevel 1 (
  echo [!] Node.js не найден. Установите LTS-версию с https://nodejs.org и запустите файл снова.
  pause
  exit /b 1
)
if not exist node_modules (
  echo Устанавливаю зависимости (первый раз 1-2 минуты)...
  call npm install
)
echo.
echo Фронтенд: http://localhost:3000   (не закрывайте это окно)
call npm run dev
pause
