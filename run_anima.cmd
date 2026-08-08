@echo off
set "PROJECT_ROOT=%~dp0"
set "PYTHONPATH=%PROJECT_ROOT%src"
python -m anima_prompt_studio
