@echo off
REM Sanal ortami aktiflestirmeden HusCC calistirir:  huscc publish "video adi"
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%.venv\Scripts\huscc.exe" (
  "%ROOT%.venv\Scripts\huscc.exe" %*
) else (
  echo Sanal ortam yok. Once: python bootstrap.py
  exit /b 1
)
