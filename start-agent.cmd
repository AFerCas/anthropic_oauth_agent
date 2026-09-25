@echo off
rem Start the agent in the background (no console window). Log: logs\agent.log
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" uv sync --quiet
start "" ".venv\Scripts\pythonw.exe" -m anthropic_oauth_agent %*
