@echo off
REM Attiva l'ambiente virtuale
call .venv\Scripts\activate

REM Imposta la variabile GEMINI_API_KEY per questa sessione
set GEMINI_API_KEY=AIzaSyArcu3q9FMaII5ryggEqXfdJ5TbO-sTwbQ

REM Avvia Uvicorn
uvicorn app:app --reload --port 8081
