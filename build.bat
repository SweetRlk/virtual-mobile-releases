@echo off
cd /d "%~dp0"
echo Compilando ETS2 Overlay...
npm run build
echo.
echo Pronto! Instalador em: dist\ETS2 Overlay Setup 1.0.0.exe
pause
