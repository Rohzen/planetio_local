# Odoo AI Copilot NL→Domain

Questo repository contiene un prototipo di **AI Copilot per Odoo** capace di trasformare prompt in linguaggio naturale in domini Odoo (`[(field, operator, value), ...]`), con supporto sia a regole deterministiche sia a provider LLM esterni (es. Gemini).

## Contenuto

- **odoo_addons/ai_copilot_nl_domain**  
  Wizard/Chat NL→Domain con:
  - tab *Candidati*
  - intent base deterministici (fatture, MRP, magazzino)
  - logging su `ir.logging`

- **odoo_addons/ai_copilot_llm_provider**  
  Integrazione con un provider LLM esterno:
  - whitelist dinamica dei modelli
  - catalogo campi per filtrare i suggerimenti
  - supporto a risposte multiple (*candidates*)

- **provider_nl2domain**  
  Servizio FastAPI che usa **Gemini 1.5 Flash** (free-friendly):  
  - riceve prompt + whitelist modelli  
  - restituisce solo JSON valido (`model/domain` o `candidates[]`)

## Come provarlo al volo

1. **Installa i moduli Odoo**
   - Copia entrambe le cartelle in `addons/`
   - Aggiorna l’elenco App
   - Installa i moduli

2. **Avvia il provider**
   ```bash
   export GEMINI_API_KEY=YOUR_KEY
   cd provider_nl2domain
   pip install -r requirements.txt
   uvicorn app:app --reload --port 8081
   ```

3. **Configura Odoo**
   - Vai su *Impostazioni → AI Copilot*
   - Inserisci `http://localhost:8081/nl2domain` come URL provider
   - Inserisci la tua API key

4. **Testa nel menu**
   - Apri *AI → Copilot NL→Domain*
   - Esempi prompt:
     - `documenti ACME di luglio`
     - `ordini di produzione in ritardo`
     - `articoli sotto punto di riordino`

## Few-shots inclusi

Il provider include esempi precostruiti che guidano il modello nei casi più comuni:

- **mrp.production**: MO in ritardo  
- **stock.picking**: picking in attesa per mancanza componenti  
- **stock.move**: movimenti non riservati per un prodotto  
- **purchase.order**: acquisti urgenti con consegna entro 7 giorni  
- **account.move**: fatture fornitore ACME pagate in un intervallo  

Il provider passa questi *few-shots* al modello come guida: se il prompt è simile, Gemini li utilizza come pattern per generare domini più precisi.  
