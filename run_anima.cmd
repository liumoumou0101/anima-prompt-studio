@echo off
set "PROJECT_ROOT=%~dp0"
set "PYTHONPATH=%PROJECT_ROOT%src"
if exist "%PROJECT_ROOT%.venv\Scripts\python.exe" (
    "%PROJECT_ROOT%.venv\Scripts\python.exe" -m anima_prompt_studio
) else (
    python -m anima_prompt_studio
)
