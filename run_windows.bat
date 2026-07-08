@echo off
python -m pip install -r requirements.txt
python src\health_agent.py "data\Project Plan B(2).xlsx" "data\S2P Project(2).xlsx" --as-of 2026-07-08 --out outputs\json
pause
