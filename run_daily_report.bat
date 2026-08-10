@echo off
REM Daily monitoring report launcher (called by Windows Task Scheduler).
REM Forces UTF-8 console encoding; see run_server.bat for ETCH_PY.
REM Optional argument: a YYYY-MM-DD date, or --no-slack for console output only.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not defined ETCH_PY set ETCH_PY=python
"%ETCH_PY%" scheduled_report.py %*
