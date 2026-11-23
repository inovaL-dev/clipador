@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Publicar o Clipador no GitHub
set PYTHONUTF8=1

set "PY="
for %%V in (3.12 3.11 3.13 3.10) do (
  if not defined PY (
    py -%%V --version >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Instale o Python 3.12 em https://www.python.org/downloads/release/python-3128/
  pause
  exit /b 1
)

%PY% empacotar\publicar.py
echo.
pause
