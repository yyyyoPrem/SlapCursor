@echo off
rem Double-click to start SlapCursor (no console window). Quit from the tray icon menu.
set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
start "" "%PYW%" "%~dp0slap_cursor.py"
