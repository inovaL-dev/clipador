@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set "PATH=%CD%\ffmpeg\bin;%CD%\.venv\Scripts;%PATH%"

set "PY="
python --version >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto tem_python
py -3 --version >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY goto sem_python

:tem_python

ffmpeg -version >nul 2>nul
if errorlevel 1 goto baixar_ffmpeg
ffprobe -version >nul 2>nul
if errorlevel 1 goto baixar_ffmpeg
goto ffmpeg_ok

:baixar_ffmpeg
echo Baixando o FFmpeg. Isso pode levar alguns minutos...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $urls=@('https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip','https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'); $ok=$false; foreach($u in $urls){ try { Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile 'ffmpeg_download.zip'; $ok=$true; break } catch { Write-Host $_.Exception.Message } }; if(-not $ok){ exit 1 }; if(Test-Path 'ffmpeg_tmp'){ Remove-Item -Recurse -Force 'ffmpeg_tmp' }; Expand-Archive -Force 'ffmpeg_download.zip' 'ffmpeg_tmp'; $exe=Get-ChildItem 'ffmpeg_tmp' -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1; if(-not $exe){ exit 1 }; New-Item -ItemType Directory -Force 'ffmpeg\bin' | Out-Null; Copy-Item (Join-Path $exe.DirectoryName '*') 'ffmpeg\bin' -Force; Remove-Item -Recurse -Force 'ffmpeg_tmp'; Remove-Item -Force 'ffmpeg_download.zip'"
if errorlevel 1 goto erro_ffmpeg
ffmpeg -version >nul 2>nul
if errorlevel 1 goto erro_ffmpeg
ffprobe -version >nul 2>nul
if errorlevel 1 goto erro_ffmpeg
echo FFmpeg instalado.

:ffmpeg_ok
if exist ".venv\instalado-v3.ok" goto iniciar
echo Instalando os componentes do clipador. Isso pode levar alguns minutos...
%PY% -m venv .venv
if errorlevel 1 goto erro_instalar
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto erro_instalar
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto erro_instalar
echo ok> ".venv\instalado-v3.ok"

:iniciar
".venv\Scripts\python.exe" clipador.py
pause
exit /b 0

:sem_python
echo Instale o Python 3.10 ou mais novo em https://www.python.org/downloads/
echo Na instalacao, marque a opcao "Add Python to PATH".
echo Depois, abra o iniciar.bat de novo.
pause
exit /b 1

:erro_ffmpeg
echo Nao consegui baixar o FFmpeg. Confira sua internet e abra o iniciar.bat de novo.
pause
exit /b 1

:erro_instalar
echo Nao consegui instalar o clipador. Confira sua internet e abra o iniciar.bat de novo.
rmdir /s /q .venv 2>nul
pause
exit /b 1
