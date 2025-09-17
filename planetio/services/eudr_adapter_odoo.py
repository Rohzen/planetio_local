# -*- coding: utf-8 -*-
import base64, json
from odoo import _, fields
from odoo.exceptions import UserError
from .eudr_client import EUDRClient, build_geojson_b64
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def _place_description(line, record, idx):
    parts = [
        (line.farm_name or "").strip(),
        (line.municipality or "").strip(),
        (line.region or "").strip(),
        ((line.country or (record.partner_id.country_id.code or "")).upper()).strip(),
        (line.farmer_id_code or line.name or f"plot-{idx}")
    ]
    desc = ", ".join([p for p in parts if p])
    return (desc[:240] or f"Plot {idx}")  # accorcia per sicurezza

def _safe_json_loads(value):
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {"raw": value}


def _safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_line_geometry(line):
    geom = None
    if hasattr(line, "_line_geometry"):
        try:
            geom = line._line_geometry()
        except Exception:
            geom = None
    if not geom and getattr(line, "geometry", None):
        try:
            geom = json.loads(line.geometry)
        except Exception:
            geom = None
    return geom if isinstance(geom, dict) and geom.get("type") else None


def build_dds_geojson(record):
    """Return the GeoJSON payload used for DDS submissions."""
    features = []
    commodity = (
        record.product_id.display_name
        if getattr(record, "product_id", False)
        else (record.product_description or "unknown")
    )
    harvest_date = fields.Date.context_today(record)

    for idx, line in enumerate(getattr(record, "line_ids", []), start=1):
        geom = _get_line_geometry(line)
        if not geom:
            continue

        country_code = (line.country or record.partner_id.country_id.code or "XX").upper()
        desc = _place_description(line, record, idx)

        props = {
            "plotId": line.farmer_id_code or line.name or f"line-{line.id}",
            "commodity": commodity,
            "harvestDate": fields.Date.to_string(harvest_date),
            "countryOfProduction": country_code,
            # >>> questi due riempiono "Production Place Description" in TRACES
            "description": desc,
            "name": desc,
            # opzionali (utili in UI/log)
            "index": idx,
            "type": geom.get("type"),
            "areaHa": float(getattr(line, "area_ha", 0) or 0),
        }

        features.append({"type": "Feature", "properties": props, "geometry": geom})

    if not features:
        raise UserError(_("GeoJSON missing or no valid geometries on lines."))

    return {"type": "FeatureCollection", "features": features}


def build_deforestation_geojson(record):
    """Return a GeoJSON FeatureCollection including deforestation metrics."""

    features = []

    for idx, line in enumerate(getattr(record, "line_ids", []), start=1):
        geom = _get_line_geometry(line)
        if not geom:
            continue

        props = {
            "lineId": line.id,
            "plotId": line.farmer_id_code or line.name or f"line-{line.id}",
            "index": idx,
            "name": line.name,
            "farmerName": getattr(line, "farmer_name", None),
            "farmerIdCode": getattr(line, "farmer_id_code", None),
            "farmName": getattr(line, "farm_name", None),
            "country": getattr(line, "country", None),
            "region": getattr(line, "region", None),
            "municipality": getattr(line, "municipality", None),
            "geoType": geom.get("type"),
        }

        area_val = _safe_float(getattr(line, "area_ha", None))
        if area_val is not None:
            props["areaHa"] = area_val
        elif getattr(line, "area_ha", None) not in (None, ""):
            props["areaHaRaw"] = getattr(line, "area_ha")

        defor_info = {
            "ok": bool(getattr(line, "external_ok", False)),
            "status": getattr(line, "external_status", None),
            "provider": getattr(line, "defor_provider", None),
            "alertCount": getattr(line, "defor_alerts", None),
            "alertAreaHa": getattr(line, "defor_area_ha", None),
            "httpCode": getattr(line, "external_http_code", None),
            "uid": getattr(line, "external_uid", None),
        }

        msg = getattr(line, "external_message", None) or getattr(
            line, "external_message_short", None
        )
        if msg:
            defor_info["message"] = msg

        details = _safe_json_loads(getattr(line, "defor_details_json", None))
        if details:
            defor_info["details"] = details
            if isinstance(details, dict) and not defor_info.get("message"):
                detail_msg = details.get("message")
                if detail_msg:
                    defor_info["message"] = detail_msg

        external_props = _safe_json_loads(getattr(line, "external_properties_json", None))
        if external_props:
            defor_info["externalProperties"] = external_props

        # Remove keys with ``None`` values but keep False/0
        defor_info = {
            key: val
            for key, val in defor_info.items()
            if val is not None and val != ""
        }
        defor_info["ok"] = bool(getattr(line, "external_ok", False))

        props["deforestation"] = defor_info

        features.append({"type": "Feature", "properties": props, "geometry": geom})

    if not features:
        raise UserError(_("No valid geometries found to build deforestation GeoJSON."))

    return {"type": "FeatureCollection", "features": features}


def _attach_geojson(record, geojson_dict, filename):
    attachment_vals = {
        "name": filename,
        "res_model": record._name,
        "res_id": record.id,
        "mimetype": "application/geo+json",
        "type": "binary",
        "datas": base64.b64encode(
            json.dumps(geojson_dict, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ),
    }

    Attachment = record.env["ir.attachment"]
    existing = Attachment.search(
        [
            ("res_model", "=", record._name),
            ("res_id", "=", record.id),
            ("name", "=", attachment_vals["name"]),
        ],
        limit=1,
    )
    if existing:
        existing.write(attachment_vals)
        return existing
    return Attachment.create(attachment_vals)


def attach_dds_geojson(record, geojson_dict):
    """Persist the DDS GeoJSON as an attachment on the record."""

    return _attach_geojson(record, geojson_dict, f"DDS_GeoJSON_{record.id}.geojson")


def attach_deforestation_geojson(record, geojson_dict):
    """Persist the deforestation GeoJSON as an attachment on the record."""

    return _attach_geojson(
        record, geojson_dict, f"Deforestation_GeoJSON_{record.id}.geojson"
    )

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

    geojson_dict = build_dds_geojson(record)
    attach_dds_geojson(record, geojson_dict)
    geojson_b64 = build_geojson_b64(geojson_dict)

    raw = record.net_mass_kg
    try:
        kg = Decimal(str(raw))
    except (InvalidOperation, TypeError):
        raise UserError(_("net_weight must be a valid number (kg)"))

    if kg <= 0:
        raise UserError(_("net_weight must be > 0 kg"))

    # arrotondamento "commerciale", minimo 1
    kg_int = max(1, int(kg.to_integral_value(rounding=ROUND_HALF_UP)))
    weight = str(kg_int)

    client = EUDRClient(endpoint, username, apikey, wsse_mode, webservice_client_id=wsclient)
    company_address = (record.partner_id._display_address(without_company=True) or '').replace('\n', ' ')

    comment_text = ((getattr(record, 'x_eudr_comment', None) or getattr(record, 'note', None) or '').strip())

    if not comment_text:
        comment_text = _('Submission for %s on %s by %s') % (
        (record.name or f'Batch-{record.id}'), fields.Date.today(),record.env.company.name,
        )

    submit_xml = client.build_statement_xml(
        internal_ref = record.name or f'Batch-{record.id}',
        activity_type = record.activity_type.upper(),
        company_name = record.partner_id.name or 'Company',
        company_country = record.partner_id.country_id.code or 'IT',
        company_address = company_address or 'Unknown Address',
        eori_value = record.partner_id.vat,
        hs_heading = record.hs_code or '090111',
        description_of_goods = record.coffee_species.name,
        # get scientific name =record.coffee_species.scientific_name,
        net_weight_kg = weight,
        producer_country = (record.partner_id.country_id.code or 'BR').upper(),
        producer_name = record.producer_name or 'Unknown Producer',
        geojson_b64 = geojson_b64,
        operator_type = record.eudr_type_override or 'TRADER',
        country_of_activity = company_country,
        border_cross_country = company_country,
        comment=comment_text,
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
        dds_id = client.parse_dds_identifier(text)  # UUID tecnico
        # referenceNumber “umano” (serve il parser nel client)
        ref_no = getattr(client, 'parse_reference_number', lambda _: None)(text)

        if dds_id:
            if hasattr(record, 'dds_identifier'):
                record.dds_identifier = dds_id
            if ref_no and hasattr(record, 'eudr_id'):
                record.eudr_id = ref_no  # <- il tuo campo per la reference number

            # record.status_planetio = 'transmitted'  # se vogliamo aggiornare lo stato

            record.message_post(
                body=_('DDS trasmessa con successo. ID: <b>%s</b>%s') % (
                    dds_id,
                    (", Reference: <b>%s</b>" % ref_no) if ref_no else ""
                )
            )
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
            record.message_post(body=msg.replace("\n", "<br/>"))
            raise UserError(msg)
        else:
            wsid_only = client.parse_ws_request_id(text)
            base = _('Errore EUDR (%s): %s') % (status, (text or '')[:800])
            if wsid_only:
                base += _('\n\nWS_REQUEST_ID: %s') % wsid_only
            record.message_post(
                body=("Fault grezzo (parsing fallito):<br/><pre>%s</pre>" % (text or "")).replace("\n", "<br/>"))
            raise UserError(base)


