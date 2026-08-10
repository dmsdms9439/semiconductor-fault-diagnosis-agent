@echo off
REM Kafka streamer launcher (Scheduled Task 'EtchStreamer'); auto-stops at 09:00 KST.
REM See run_server.bat for the ETCH_PY environment variable.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not defined ETCH_PY set ETCH_PY=python
"%ETCH_PY%" scheduled_streamer.py
