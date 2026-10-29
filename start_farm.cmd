@echo off
rem Start both farm workers of this PC. Startup folder runs it hidden via start_farm.vbs.
cd /d "%~dp0"
set "PY=C:\Users\eseid\AppData\Local\Programs\Python\Python311\python.exe"
start "eseid-main" /b cmd /c "set FARM_DATA=farm-data&& set WORKER_NAME=eseid-main&& "%PY%" run_farm.py"
start "eseid-notebook" /b cmd /c "set FARM_DATA=farm-data-notebook&& set WORKER_NAME=eseid-notebook&& "%PY%" run_farm.py"
