@echo off
REM Runs gmail_ingest.py and logs output. Task Scheduler calls this file.
REM Edit the path below if you move the project folder.

cd /d "%~dp0"
python gmail_ingest.py >> ingest.log 2>&1