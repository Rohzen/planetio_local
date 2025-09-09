# -*- coding: utf-8 -*-
import base64, json
from odoo import _
from odoo.exceptions import UserError
from .eudr_client import EUDRClient, build_geojson_b64

def submit_dds_for_batch(record):
    ICP = record.env['ir.config_parameter'].sudo()
    endpoint = ICP.get_param('planetio.eudr_endpoint') or 'https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/EUDRSubmissionServiceV1'
    username = ICP.get_param('planetio.eudr_user') or ''
    apikey  = ICP.get_param('planetio.eudr_apikey') or ''
    wsse_mode = (ICP.get_param('planetio.eudr_wsse_mode') or 'digest').lower()
    wsclient = ICP.get_param('planetio.eudr_webservice_client_id') or 'eudr-test'

    if not username or not apikey:
        raise UserError(_('Credenziali EUDR mancanti: imposta planetio.eudr_user e planetio.eudr_apikey.'))

    company = record.env.company
    addr_parts = [company.street or "", company.zip or "", company.city or "", company.country_id.code or ""]
    company_address = ", ".join([p for p in addr_parts if p]).strip()
    company_country = (company.country_id.code or 'IT').upper()
    if not company_address:
        raise UserError(_("Indirizzo azienda mancante: compila via/Cap/Città/Nazione in Impostazioni Azienda."))

    eori_value = (ICP.get_param('planetio.eudr_eori') or company.vat or '').replace(' ', '')
    if not eori_value or len(eori_value) < 6:
        raise UserError(_("EORI mancante/non valido. Imposta planetio.eudr_eori nelle configurazioni."))

    # GeoJSON example
    GEOJSON = {
        'type': 'FeatureCollection',
        'features': [{
            'type': 'Feature',
            'properties': {
                'plotId': 'BR-TEST-COFFEE-001',
                'commodity': 'coffee',
                'harvestDate': '2024-03-15',
                'countryOfProduction': 'BR'
            },
            'geometry': {'type': 'Point', 'coordinates': [-46.6, -20.2]}
        }]}
    geojson_b64 = base64.b64encode(json.dumps(GEOJSON, separators=(',', ':')).encode('utf-8')).decode('ascii')

    # GeoJSON
    # try:
    #     gj_str = record.geo_analysis_id.geojson_data if (
    #                 record.geo_analysis_id and record.geo_analysis_id.geojson_data) else None
    #     gj = json.loads(gj_str) if gj_str else None
    # except Exception:
    #     gj = None
    #
    # def has_valid_geometry(fc):
    #     try:
    #         if fc and fc.get("type") == "FeatureCollection":
    #             feats = fc.get("features") or []
    #             for f in feats:
    #                 geom = (f or {}).get("geometry")
    #                 if geom and geom.get("type") in ("Point", "Polygon", "MultiPolygon", "MultiPoint", "LineString"):
    #                     coords = geom.get("coordinates")
    #                     if coords:
    #                         return True
    #     except Exception:
    #         pass
    #     return False

    # if not has_valid_geometry(gj):
    #     raise UserError(
    #         _("GeoJSON mancante o senza geometrie valide: aggiungi almeno un punto/poligono con coordinate."))
    #
    # geojson_b64 = build_geojson_b64(gj)



    # Net weight (kg) — usa un campo reale e fai fallback sicuro
    peso = 1 #None
    for name in ("net_weight_kg", "weight_net_kg", "weight_kg"):
        if hasattr(record, name) and getattr(record, name):
            try:
                peso = float(getattr(record, name))
                break
            except Exception:
                pass
    if peso is None and record.farm_area:
        # fallback molto prudente (evita 0); ma meglio NON usare farm_area in produzione
        try:
            peso = float(record.farm_area)
        except Exception:
            peso = None

    if not peso or peso <= 0:
        raise UserError(_("Peso netto (kg) mancante o non valido. Imposta un campo peso reale > 0."))

    net_weight_kg = str(max(1, int(round(peso))))

    client = EUDRClient(endpoint, username, apikey, wsse_mode, webservice_client_id=wsclient)

    submit_xml = client.build_statement_xml(
        internal_ref = record.protocol_number or f'Batch-{record.id}',
        activity_type = 'IMPORT',
        company_name = company.name or 'Company',
        company_country = company_country,
        company_address = company_address,
        eori_value = eori_value,
        hs_heading = '090111',
        description_of_goods = 'Green coffee beans',
        net_weight_kg = net_weight_kg,
        producer_country = (record.country_code or 'BR').upper(),
        producer_name = record.name or 'Unknown Producer',
        geojson_b64 = geojson_b64,
        operator_type = 'OPERATOR',
        country_of_activity = company_country,
        border_cross_country = company_country,
        comment = _('Questionnaire completed on %s') % (record.questionnaire_date and record.questionnaire_date.strftime('%Y-%m-%d') or 'N/A'),
    )

    envelope = client.build_envelope(submit_xml)

    # Attach request
    record.env['ir.attachment'].create({
        'name': f'DDS_Submit_Request_{record.id}.xml',
        'res_model': record._name,
        'res_id': record.id,
        'mimetype': 'text/xml',
        'type': 'binary',
        'datas': base64.b64encode(envelope.encode('utf-8')),
    })

    status, text = client.submit(envelope)

    # Attach response
    record.env['ir.attachment'].create({
        'name': f'DDS_Submit_Response_{record.id}.xml',
        'res_model': record._name,
        'res_id': record.id,
        'mimetype': 'text/xml',
        'type': 'binary',
        'datas': base64.b64encode((text or '').encode('utf-8')),
    })

    if status == 200:
        dds_id = client.parse_dds_identifier(text)
        if dds_id:
            if hasattr(record, 'dds_identifier'):
                record.dds_identifier = dds_id
            record.status_planetio = 'transmitted'
            record.message_post(body=_('DDS trasmessa con successo. ID: <b>%s</b>') % dds_id)
            return dds_id
        else:
            raise UserError(_('DDS inviata ma senza ddsIdentifier. Controlla la risposta XML.'))
    else:
        wsid, errs = client.parse_business_errors(text)
        if errs:
            bullets = []
            for e in errs:
                code = e.get("code") or "N/A"
                msg = e.get("message") or "N/A"
                path = e.get("path") or "-"
                bullets.append(f"- [{code}] {msg} (path: {path})")
            msg = _('Violazioni regole EUDR rilevate:\n%s') % "\n".join(bullets)
            if wsid:
                msg += _('\n\nWS_REQUEST_ID: %s') % wsid
            # Log anche sul chatter per storico completo
            record.message_post(body=msg.replace("\n", "<br/>"))
            raise UserError(msg)
        else:
            wsid_only = client.parse_ws_request_id(text)
            base = _('Errore EUDR (%s): %s') % (status, (text or '')[:800])
            if wsid_only:
                base += _('\n\nWS_REQUEST_ID: %s') % wsid_only
            # Log raw sul chatter per analisi manuale
            record.message_post(
                body=("Fault grezzo (parsing fallito):<br/><pre>%s</pre>" % (text or "")).replace("\n", "<br/>"))
            raise UserError(base)

