@echo off
cd /d "%~dp0"
echo Compilando Virtual Mobile...
npm run build
echo.
echo Pronto! Instalador gerado na pasta dist\
pause
