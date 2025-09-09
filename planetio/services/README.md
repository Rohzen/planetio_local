Parametri richiesti (System Parameters)

planetio.eudr_user → username TRACES/EUDR

planetio.eudr_apikey → API key (usata nel digest)

planetio.eudr_endpoint → https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/EUDRSubmissionServiceV1

(opzionale) planetio.eudr_wsse_mode → digest (default) o text

Note pratiche

Paesi UE: countryOfActivity e borderCrossCountry devono essere UE+XI (uso company.country_id.code).

Peso netto (kg): ho messo un placeholder (record.farm_area → va sostituito con un campo peso reale se ce l’hai).

GeoJSON: per il producer viene serializzato e base64-encodato; assicurati che record.geo_analysis_id.geojson_data contenga un JSON valido.

Allegati: ogni submit salva XML di request e response come ir.attachment per audit.

Estendibilità: il client è stateless; puoi testarlo anche fuori da Odoo.