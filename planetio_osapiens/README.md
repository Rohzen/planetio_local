Planetio oSapiens Integration (Odoo 14)
=======================================

Modulo di integrazione verso oSapiens (ambito EUDR) con esempi di:
- RFI (elenco e invio risposte)
- Plot (crea/aggiorna)
- Lot (crea)
- DDS (associazione e verifica stato)
- Upload documenti

Nota importante
---------------
Gli endpoint nel client sono segnaposto (`/api/v1/eudr/...`). Sostituiscili con quelli ufficiali della tua documentazione oSapiens.
Adatta anche gli header di autenticazione se richiesto (Bearer vs X-Api-Token).

Installazione
-------------
- Copia la cartella `planetio_osapiens` in `addons/`
- Aggiorna la lista moduli e installa da Apps
- Vai su Impostazioni -> Generali e configura i parametri oSapiens

Utilizzo rapido
---------------
- Apri un ordine di acquisto
- Tab "oSapiens" -> imposta DDS Reference se lo hai
- Premi "Crea/aggiorna Lot su oSapiens" per inviare dati e creare un lot
- Premi "Invia/aggiorna DDS" per collegare/verificare un DDS

Logging
-------
Il client scrive su ir.logging con path = osapiens_client.

Licenza
-------
LGPL-3