@echo off
REM Etch anomaly server launcher (registered as a Windows Scheduled Task).
REM Auto-starts at logon; Task Scheduler restarts it if it crashes.
REM
REM Set ETCH_PY to the project venv python, e.g.
REM   setx ETCH_PY "D:\envs\etch\.venv\Scripts\python.exe"
REM Falls back to the python on PATH when ETCH_PY is not defined.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not defined ETCH_PY set ETCH_PY=python
"%ETCH_PY%" server.py
