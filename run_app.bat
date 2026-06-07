@echo off
REM Double-click this file to launch the WC2026 Fantasy Analytics app.
REM It opens a console window and your browser at http://localhost:8501
cd /d "%~dp0"
python -m streamlit run app.py
pause
