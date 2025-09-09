import os
import json
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import google.generativeai as genai

# Config iniziale (potrà essere ri-eseguita a runtime)
API_KEY = os.getenv('GEMINI_API_KEY')
if not API_KEY:
    print('WARNING: GEMINI_API_KEY not set')
else:
    genai.configure(api_key=API_KEY)

MODEL_NAME = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')

app = FastAPI(title='NL→Domain Provider')

class RequestBody(BaseModel):
    prompt: str
    hint_model: Optional[str] = None
    temperature: float = 0.0
    allowed_models: List[str] = Field(default_factory=list)
    catalog: Dict[str, Dict[str, List[str]]] = Field(default_factory=dict)
    expected: Optional[Dict[str, Any]] = None

SYSTEM_PROMPT = (
    "Sei un traduttore NL→Domain per Odoo. "
    "Dato un prompt utente, una whitelist di modelli Odoo (allowed_models) e un catalogo di campi, "
    "devi restituire JSON con: ('model','domain','description') oppure ('candidates':[...], 'description'). "
    "Il 'domain' è una lista di tuple Odoo: (campo, operatore, valore). "
    "Usa solo modelli presenti in allowed_models e solo campi presenti nel catalog del relativo modello. "
    "Non inventare valori. Non aggiungere testo fuori dal JSON."
)

# Few-shot guidati per scenari tipici ERP (MRP/Inventory/Acquisti/Accounting)
FEW_SHOTS = [
    {
        "prompt": "ordini di produzione in ritardo",
        "model": "mrp.production",
        "domain": [["state","in",["confirmed","progress"]], ["date_deadline","<","{{today}}"]],
        "description": "MO oltre deadline"
    },
    {
        "prompt": "picking in attesa per mancanza componenti",
        "model": "stock.picking",
        "domain": [["state","in",["confirmed","waiting","assigned"]], ["move_lines.state","=","confirmed"]],
        "description": "Picking non completati per attesa componenti"
    },
    {
        "prompt": "movimenti non riservati del prodotto ABC",
        "model": "stock.move",
        "domain": [["product_id.name","ilike","ABC"], ["state","in",["confirmed","waiting"]], ["reserved_availability","=",0.0]],
        "description": "Stock moves non riservati per prodotto ABC"
    },
    {
        "prompt": "acquisti urgenti consegna entro 7 giorni",
        "model": "purchase.order",
        "domain": [["state","in",["to approve","purchase"]], ["date_approve","!=",False], ["date_planned","<=","{{today_plus_7}}"]],
        "description": "PO urgenti con consegna entro 7 giorni"
    },
    {
        "prompt": "fatture fornitore ACME pagate luglio 2025",
        "model": "account.move",
        "domain": [["move_type","in",["in_invoice","in_refund"]],["partner_id.name","ilike","ACME"],["invoice_date",">=","2025-07-01"],["invoice_date","<=","2025-07-31"],["payment_state","=","paid"]],
        "description": "Fornitori ACME luglio 2025 pagate"
    }
]

def _few_shots_block():
    # Inserisce few-shot come testo strutturato per aiutare il modello
    return json.dumps(FEW_SHOTS, ensure_ascii=False)

@app.post('/nl2domain')
async def nl2domain(body: RequestBody, authorization: Optional[str] = Header(None)):
    # Auth semplice
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Missing bearer token')

    # Controllo/refresh API key a runtime (utile se avvii con .bat)
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail='GEMINI_API_KEY not configured')
    genai.configure(api_key=api_key)

    # Prepara contesto input
    allowed = ', '.join(sorted(body.allowed_models)[:100])
    catalog_json = json.dumps(
        {k: v for k, v in body.catalog.items() if k in body.allowed_models},
        ensure_ascii=False
    )[:12000]

    user_prompt = (
        f"PROMPT: {body.prompt}\n\n"
        f"ALLOWED_MODELS: {allowed}\n\n"
        f"CATALOG: {catalog_json}\n\n"
        f"FEW_SHOTS: {_few_shots_block()}\n\n"
        "Ispirati ai FEW_SHOTS quando simili al prompt; adatta nomi e date, mantieni sintassi domain valida. "
        "Se ambiguo, proponi 'candidates' (max 5) con 'model','domain','confidence'. "
        "Produci SOLO JSON valido senza testo extra."
    )

    # Costruzione modello: system_instruction + prompt come stringa
    model = genai.GenerativeModel(
        MODEL_NAME,
        system_instruction=SYSTEM_PROMPT
    )

    try:
        resp = model.generate_content(
            user_prompt,
            generation_config={"temperature": body.temperature}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'LLM call failed: {e}')

    txt = (resp.text or "").strip()
    if not txt:
        raise HTTPException(status_code=500, detail='Empty response from LLM')

    # Parsing JSON (con fallback estrazione blocco)
    try:
        obj = json.loads(txt)
    except Exception:
        start = txt.find('{'); end = txt.rfind('}')
        if start >= 0 and end > start:
            try:
                obj = json.loads(txt[start:end+1])
            except Exception:
                raise HTTPException(status_code=500, detail='LLM JSON non valido (fallback failed)')
        else:
            raise HTTPException(status_code=500, detail='LLM JSON non valido')

    # sicurezza: limita ai modelli allowed
    def valid_model(m):
        return isinstance(m, str) and m in body.allowed_models

    if isinstance(obj.get('model'), str) and isinstance(obj.get('domain'), list) and valid_model(obj['model']):
        return obj

    if isinstance(obj.get('candidates'), list):
        obj['candidates'] = [c for c in obj['candidates'] if valid_model(c.get('model'))][:5]
        if obj['candidates']:
            return obj

    raise HTTPException(status_code=422, detail='Nessun mapping valido')
