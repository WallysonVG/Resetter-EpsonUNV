@echo off
chcp 65001 >nul
echo Gerando o ResetEpson.exe...
echo.
python -m pip install --upgrade pyinstaller || goto erro
python -m PyInstaller --onefile --console --clean --name ResetEpson reset.py || goto erro
echo.
echo Pronto! O executavel esta em: dist\ResetEpson.exe
echo Pode copiar esse arquivo para qualquer computador com Windows.
pause
exit /b 0

:erro
echo.
echo Algo deu errado. Confira se o Python esta instalado e marcado no PATH.
pause
exit /b 1
