# NL→Domain Provider (FastAPI + Gemini)

Requisiti
- Python 3.10+
- Google AI Studio API key in variabile d'ambiente `GEMINI_API_KEY`

GEMINI_API_KEY="AIzaSyArcu3q9FMaII5ryggEqXfdJ5TbO-sTwbQ"
setx GEMINI_API_KEY "AIzaSyArcu3q9FMaII5ryggEqXfdJ5TbO-sTwbQ"

Setup (Linux/macOS)
```
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=PASTE_YOUR_KEY
uvicorn app:app --reload --port 8081
```
Setup (Windows PowerShell)
```
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
setx GEMINI_API_KEY PASTE_YOUR_KEY
uvicorn app:app --reload --port 8081
```
Endpoint: `http://localhost:8081/nl2domain`
