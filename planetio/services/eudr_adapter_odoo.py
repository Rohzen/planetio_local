# -*- coding: utf-8 -*-
import base64, json
import xml.etree.ElementTree as ET
import requests
from requests.auth import HTTPBasicAuth
from odoo import _, fields
from odoo.exceptions import UserError
from .eudr_client import EUDRClient, build_geojson_b64
from .eudr_client_retrieve import EUDRRetrievalClient
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from types import SimpleNamespace


class _SafeFormatDict(dict):
    """Helper dict that returns empty string for missing keys when formatting strings."""

    def __missing__(self, key):  # pragma: no cover - trivial fallback
        return ""


def _download_and_attach_dds_pdf(record, reference_number: str, username: str, apikey: str):
    """Download the DDS PDF via the public EUDR API and attach it to the record.

    The API documentation is available at https://www.eudr-api.eu/docs. The default
    endpoint expects a GET request returning ``application/pdf``. The request uses
    HTTP basic authentication with the TRACES username/API key and supports a
    configurable header for API key based auth.
    """

    if not reference_number:
        return

    ICP = record.env['ir.config_parameter'].sudo()
    template = ICP.get_param('planetio.eudr_pdf_url_template') or \
        'https://www.eudr-api.eu/api/dds/{reference_number}/pdf'
    header_name = (ICP.get_param('planetio.eudr_pdf_key_header') or 'X-API-Key').strip()

    context = _SafeFormatDict(
        reference_number=reference_number,
        uuid=getattr(record, 'dds_identifier', ''),
        dds_identifier=getattr(record, 'dds_identifier', ''),
        eudr_id=getattr(record, 'eudr_id', reference_number),
        record_id=record.id,
    )
    try:
        pdf_url = template.format_map(context)
    except Exception as exc:  # pragma: no cover - configuration error
        raise UserError(_('Impossibile comporre la URL per il PDF DDS: %s') % exc)

    if not pdf_url:
        raise UserError(_('La configurazione URL per il PDF DDS restituisce un valore vuoto.'))

    headers = {'Accept': 'application/pdf'}
    if header_name and apikey:
        headers[header_name] = apikey

    auth = HTTPBasicAuth(username, apikey) if username and apikey else None

    try:
        response = requests.get(pdf_url, headers=headers, auth=auth, timeout=120)
    except Exception as exc:  # pragma: no cover - network failure
        raise UserError(_('Errore durante il download del PDF DDS: %s') % exc)

    if response.status_code != 200 or not response.content:
        # Try to extract meaningful message from JSON responses
        detail = ''
        try:
            payload = response.json()
            detail = payload.get('message') or payload.get('detail') or ''
        except Exception:  # pragma: no cover - optional JSON decoding
            detail = response.text[:200]
        raise UserError(_('Download PDF DDS fallito (%s): %s') % (response.status_code, detail or '-'))

    data_b64 = base64.b64encode(response.content)
    attachment_vals = {
        'name': f'DDS_{reference_number}.pdf',
        'datas_fname': f'DDS_{reference_number}.pdf',
        'res_model': record._name,
        'res_id': record.id,
        'type': 'binary',
        'mimetype': 'application/pdf',
        'datas': data_b64,
        'eudr_document_visible': True,
    }

    Attachment = record.env['ir.attachment'].sudo()
    existing = Attachment.search([
        ('res_model', '=', record._name),
        ('res_id', '=', record.id),
        ('datas_fname', '=', attachment_vals['datas_fname']),
    ], limit=1)

    if existing:
        write_vals = {k: v for k, v in attachment_vals.items() if k not in {'res_model', 'res_id'}}
        existing.write(write_vals)
        attachment = existing
    else:
        attachment = Attachment.create(attachment_vals)

    record.message_post(
        body=_('PDF DDS scaricato e allegato come <b>%s</b>.') % attachment.name,
        attachment_ids=attachment.ids,
    )


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


def _format_weight_value(raw):
    try:
        kg = Decimal(str(raw))
    except (InvalidOperation, TypeError):
        raise UserError(_("net_weight must be a valid number (kg)"))
    if kg <= 0:
        raise UserError(_("net_weight must be > 0 kg"))
    kg_int = max(1, int(kg.to_integral_value(rounding=ROUND_HALF_UP)))
    return str(kg_int)


def _species_info_xml(record):
    coffee = getattr(record, "coffee_species", False)
    scientific = (coffee and getattr(coffee, "scientific_name", None)) or getattr(record, "scientific_name", None)
    common = getattr(record, "common_name", None) or (coffee and getattr(coffee, "name", None))
    if scientific or common:
        xml = ['<model:speciesInfo>']
        if scientific:
            xml.append(f'<model:scientificName>{scientific}</model:scientificName>')
        if common:
            xml.append(f'<model:commonName>{common}</model:commonName>')
        xml.append('</model:speciesInfo>')
        return ''.join(xml)
    return ''


def _build_producer_feature_collection(record, producer, ha_per_point):
    features = []
    ha_per_point = ha_per_point or 4.0
    for idx, plot in enumerate(producer.plot_ids, start=1):
        geom = _safe_json_loads(getattr(plot, "geometry", None))
        if not isinstance(geom, dict) or not geom.get("type"):
            continue

        producer_name = producer.name or (_("Producer %s") % idx)
        producer_country = (plot.country_of_production or producer.country or getattr(record.partner_id.country_id, 'code', '') or getattr(record.supplier_id.country_id, 'code', '') or 'XX').upper()
        line_stub = SimpleNamespace(
            farm_name=None,
            municipality=None,
            region=None,
            country=plot.country_of_production or producer.country,
            farmer_id_code=plot.plot_id,
            name=plot.plot_id,
        )
        production_place = _place_description(line_stub, record, idx)

        props = {
            "ProducerName": producer_name,
            "ProducerCountry": producer_country,
            "PlotId": plot.plot_id or f"plot-{idx}",
        }
        if production_place:
            props["ProductionPlace"] = production_place

        geom_type = geom.get("type", "")
        if geom_type == "Point":
            area_val = plot.area_ha if plot.area_ha not in (None, "") else ha_per_point
            try:
                props["Area"] = float(area_val)
            except (TypeError, ValueError):
                props["Area"] = float(ha_per_point)

        features.append({"type": "Feature", "properties": props, "geometry": geom})

    if not features:
        raise UserError(_("Producer %s has no valid plot geometries.") % (producer.name or producer.id))

    return {"type": "FeatureCollection", "features": features}


def _build_multi_commodities_xml(record, species_block, ha_per_point):
    default_desc = record.product_description or getattr(record.product_id, "display_name", None) or record.name or ""
    default_weight = record.net_mass_kg
    default_hs = record.hs_code or "090111"
    blocks = []

    for position, commodity in enumerate(record.commodity_ids, start=1):
        if not commodity.producer_ids:
            raise UserError(_("Commodity %s has no producers.") % position)

        description = commodity.description_of_goods or default_desc
        weight_raw = commodity.net_weight_kg or default_weight
        net_weight = _format_weight_value(weight_raw)
        hs_heading = commodity.hs_heading or default_hs

        block = [
            '<model:commodities>',
            f'<model:position>{position}</model:position>',
            '<model:descriptors>',
            f'<model:descriptionOfGoods>{description}</model:descriptionOfGoods>',
            '<model:goodsMeasure>',
            f'<model:netWeight>{net_weight}</model:netWeight>',
            '</model:goodsMeasure>',
            '</model:descriptors>',
            f'<model:hsHeading>{hs_heading}</model:hsHeading>',
        ]
        if species_block:
            block.append(species_block)

        for idx, producer in enumerate(commodity.producer_ids, start=1):
            if not producer.plot_ids:
                raise UserError(
                    _("Producer %(producer)s in commodity %(commodity)s has no plots.") % {
                        "producer": producer.name or idx,
                        "commodity": position,
                    }
                )
            collection = _build_producer_feature_collection(record, producer, ha_per_point)
            geojson_b64 = build_geojson_b64(collection)
            producer_country = (producer.country or getattr(record.partner_id.country_id, 'code', '') or getattr(record.supplier_id.country_id, 'code', '') or 'XX').upper()
            block.extend([
                '<model:producers>',
                f'<model:position>{idx}</model:position>',
                f'<model:country>{producer_country}</model:country>',
                f'<model:name>{producer.name or (_("Producer %s") % idx)}</model:name>',
                f'<model:geometryGeojson>{geojson_b64}</model:geometryGeojson>',
                '</model:producers>',
            ])

        block.append('</model:commodities>')
        blocks.append(''.join(block))

    return ''.join(blocks)


def _build_associated_statements_xml(statements):
    if not statements:
        return ''
    parts = ['<model:associatedStatements>']
    for idx, stmt in enumerate(statements, start=1):
        parts.append('<model:statements>')
        parts.append(f'<model:position>{idx}</model:position>')
        ref = (stmt.upstream_reference_number or "").strip()
        if ref:
            parts.append(f'<model:referenceNumber>{ref}</model:referenceNumber>')
        dds = (stmt.upstream_dds_identifier or "").strip()
        if dds:
            parts.append(f'<model:ddsIdentifier>{dds}</model:ddsIdentifier>')
        parts.append('</model:statements>')
    parts.append('</model:associatedStatements>')
    return ''.join(parts)


def _build_statement_xml_common(base_vals, comment_text, associated_xml='', commodities_xml=''):
    xml = [
        '<eudr:SubmitStatementRequest '
        'xmlns:eudr="http://ec.europa.eu/tracesnt/certificate/eudr/submission/v1" '
        'xmlns:model="http://ec.europa.eu/tracesnt/certificate/eudr/model/v1" '
        'xmlns:base="http://ec.europa.eu/sanco/tracesnt/base/v4">',
        f'<eudr:operatorType>{base_vals["operator_type"]}</eudr:operatorType>',
        '<eudr:statement>',
        f'<model:internalReferenceNumber>{base_vals["internal_ref"]}</model:internalReferenceNumber>',
        f'<model:activityType>{base_vals["activity_type"]}</model:activityType>',
        '<model:operator>',
        '<model:referenceNumber>',
        '<model:identifierType>eori</model:identifierType>',
        f'<model:identifierValue>{base_vals["eori_value"]}</model:identifierValue>',
        '</model:referenceNumber>',
        '<model:nameAndAddress>',
        f'<base:name>{base_vals["company_name"]}</base:name>',
        f'<base:country>{base_vals["company_country"]}</base:country>',
        f'<base:address>{base_vals["company_address"]}</base:address>',
        '</model:nameAndAddress>',
        '</model:operator>',
        f'<model:countryOfActivity>{base_vals["country_of_activity"]}</model:countryOfActivity>',
        f'<model:borderCrossCountry>{base_vals["border_cross_country"]}</model:borderCrossCountry>',
        f'<model:comment>{comment_text}</model:comment>',
    ]
    if associated_xml:
        xml.append(associated_xml)
    if commodities_xml:
        xml.append(commodities_xml)
    xml.append('<model:geoLocationConfidential>false</model:geoLocationConfidential>')
    xml.append('</eudr:statement>')
    xml.append('</eudr:SubmitStatementRequest>')
    return ''.join(xml)


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
    features = []
    for idx, line in enumerate(getattr(record, "line_ids", []), start=1):
        geom = _get_line_geometry(line)
        if not geom:
            continue

        # ProducerCountry ISO2
        producer_country = (line.country or record.partner_id.country_id.code or "XX").upper()
        # ProductionPlace (max ~240 char)
        production_place = _place_description(line, record, idx)

        props = {
            # Usato da TRACES per raggruppare i produttori (Type II)
            "ProducerName": getattr(line, "farmer_name", None) or getattr(record, "producer_name", None) or (line.farmer_id_code or line.name or f"line-{line.id}"),
            "ProducerCountry": producer_country,
            # Popola la colonna “Production Place Description”
            "ProductionPlace": production_place,
        }

        # Area solo per geometrie Point (in ettari)
        if geom.get("type") == "Point":
            area_val = _safe_float(getattr(line, "area_ha", None)) or 4.0  # TRACES mette 4ha di default se mancante
            props["Area"] = float(area_val)

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
        "eudr_document_visible": False,
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

    company = record.company_id or record.env.company
    if record.eudr_company_type_rel == 'third_party_trader':
        company = record.partner_id
    addr_parts = [company.street or "", company.zip or "", company.city or "", company.country_id.code or ""]
    company_address = ", ".join([p for p in addr_parts if p]).strip()
    company_country = (company.country_id.code or 'IT').upper()
    if not company_address:
        raise UserError(_("Indirizzo azienda mancante: compila via/Cap/Città/Nazione in Impostazioni Azienda."))

    eori_value = (ICP.get_param('planetio.eudr_eori') or company.vat or '').replace(' ', '')
    if not eori_value or len(eori_value) < 6:
        raise UserError(_("EORI mancante/non valido. Imposta planetio.eudr_eori nelle configurazioni."))

    client = EUDRClient(endpoint, username, apikey, wsse_mode, webservice_client_id=wsclient)
    comment_text = ((getattr(record, 'x_eudr_comment', None) or getattr(record, 'note', None) or '').strip())
    if not comment_text:
        comment_text = _('Submission for %s on %s by %s for lot %s') % (
            (record.name or f'Batch-{record.id}'),
            fields.Date.today(),
            company.name,
            record.lot_name or 'N/A',
        )

    address_source = company if hasattr(company, '_display_address') else record.partner_id
    company_address = (address_source and address_source._display_address(without_company=True)) or ''
    company_address = (company_address or '').replace('\n', ' ') or 'Unknown Address'

    dds_mode = getattr(record, 'dds_mode', 'single_one') or 'single_one'

    base_vals = {
        "internal_ref": record.name or f'Batch-{record.id}',
        "operator_type": (record.eudr_type_override or 'TRADER'),
        "activity_type": (record.activity_type or 'import').upper(),
        "company_name": company.name or 'Company',
        "company_country": company_country or 'IT',
        "company_address": company_address,
        "eori_value": eori_value,
        "country_of_activity": company_country,
        "border_cross_country": company_country,
    }

    submit_xml = None

    if dds_mode == 'single_one':
        geojson_dict = build_dds_geojson(record)
        attach_dds_geojson(record, geojson_dict)
        geojson_b64 = build_geojson_b64(geojson_dict)
        weight = _format_weight_value(record.net_mass_kg)

        line = next((l for l in record.line_ids if l.geometry), None)
        if line and line.country:
            producer_country = (line.country[:2] or 'PE').upper()
        elif record.supplier_id.country_id.code:
            producer_country = (record.supplier_id.country_id.code or 'PE').upper()
        else:
            raise UserError(_('Nazione produttore mancante: imposta la nazione sul fornitore o sulle linee.'))

        submit_xml = client.build_statement_xml(
            internal_ref=base_vals['internal_ref'],
            operator_type=base_vals['operator_type'],
            activity_type=base_vals['activity_type'],
            company_name=base_vals['company_name'],
            company_address=base_vals['company_address'],
            company_country=base_vals['company_country'],
            eori_value=eori_value,
            hs_heading=record.hs_code or '090111',
            description_of_goods=(
                record.coffee_species.name if record.coffee_species else (record.product_id.display_name or '')
            ),
            scientific_name=getattr(record.coffee_species, 'scientific_name', None),
            common_name=getattr(record.coffee_species, 'name', None) or getattr(record, 'common_name', None),
            net_weight_kg=weight,
            producer_country=producer_country,
            producer_name=record.supplier_id.name or 'Unknown Producer',
            country_of_activity=base_vals['country_of_activity'],
            border_cross_country=base_vals['border_cross_country'],
            geojson_b64=geojson_b64,
            comment=comment_text,
        )
    elif dds_mode == 'single_multi':
        if not record.commodity_ids:
            raise UserError(_('Add at least one commodity before submitting in Multiple commodities mode.'))
        ha_per_point = float(record.env['ir.config_parameter'].sudo().get_param('planetio.eudr_point_area_ha', '4'))
        species_block = _species_info_xml(record)
        commodities_xml = _build_multi_commodities_xml(record, species_block, ha_per_point)
        if not commodities_xml:
            raise UserError(_('Unable to build commodities payload for DDS submission.'))
        submit_xml = _build_statement_xml_common(base_vals, comment_text, commodities_xml=commodities_xml)
    elif dds_mode == 'trader_refs':
        if not record.associated_statement_ids:
            raise UserError(_('Add at least one associated statement before submitting.'))
        associated_xml = _build_associated_statements_xml(record.associated_statement_ids)
        submit_xml = _build_statement_xml_common(base_vals, comment_text, associated_xml=associated_xml)
    else:
        # Fallback to legacy behaviour
        geojson_dict = build_dds_geojson(record)
        attach_dds_geojson(record, geojson_dict)
        geojson_b64 = build_geojson_b64(geojson_dict)
        weight = _format_weight_value(record.net_mass_kg)
        submit_xml = client.build_statement_xml(
            internal_ref=base_vals['internal_ref'],
            operator_type=base_vals['operator_type'],
            activity_type=base_vals['activity_type'],
            company_name=base_vals['company_name'],
            company_address=base_vals['company_address'],
            company_country=base_vals['company_country'],
            eori_value=eori_value,
            hs_heading=record.hs_code or '090111',
            description_of_goods=(
                record.coffee_species.name if record.coffee_species else (record.product_id.display_name or '')
            ),
            scientific_name=getattr(record.coffee_species, 'scientific_name', None),
            common_name=getattr(record.coffee_species, 'name', None) or getattr(record, 'common_name', None),
            net_weight_kg=weight,
            producer_country=(record.supplier_id.country_id.code or 'BR').upper(),
            producer_name=record.supplier_id.name or 'Unknown Producer',
            country_of_activity=base_vals['country_of_activity'],
            border_cross_country=base_vals['border_cross_country'],
            geojson_b64=geojson_b64,
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
        'eudr_document_visible': False,
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
        'eudr_document_visible': False,
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
            # raise UserError(msg)
        else:
            wsid_only = client.parse_ws_request_id(text)
            base = _('Errore EUDR (%s): %s') % (status, (text or '')[:800])
            if wsid_only:
                base += _('\n\nWS_REQUEST_ID: %s') % wsid_only
            record.message_post(
                body=("Fault grezzo (parsing fallito):<br/><pre>%s</pre>" % (text or "")).replace("\n", "<br/>"))
            # raise UserError(base)

def _extract_fault_messages(payload: str):
    """Return a list of human readable fault messages extracted from a SOAP payload."""
    if not payload:
        return []

    messages = []
    try:
        root = ET.fromstring(payload)
    except Exception:
        text = (payload or "").strip()
        return [text[:400]] if text else []

    def lname(tag: str) -> str:
        return tag.split('}', 1)[-1] if isinstance(tag, str) else tag

    interesting = {"faultstring", "Text", "message", "reason", "description", "detail", "Value"}

    for node in root.iter():
        name = lname(node.tag)
        if name in interesting and node.text:
            text = node.text.strip()
            if text and text not in messages:
                messages.append(text)

    return messages


def action_retrieve_dds_numbers(record):
    """Given record.dds_identifier, call Retrieval SOAP and fill eudr_id (and others if present)."""
    ICP = record.env['ir.config_parameter'].sudo()

    # Separate endpoint from submit
    endpoint = ICP.get_param('planetio.eudr_retrieval_endpoint') or \
               'https://webgate.acceptance.ec.europa.eu/tracesnt-alpha/ws/EUDRRetrievalServiceV1'
    username  = ICP.get_param('planetio.eudr_user') or ''
    apikey    = ICP.get_param('planetio.eudr_apikey') or ''
    wsse_mode = (ICP.get_param('planetio.eudr_wsse_mode') or 'digest').lower()
    wsclient  = ICP.get_param('planetio.eudr_webservice_client_id') or 'eudr-test'

    if not username or not apikey:
        raise UserError(_('Credenziali EUDR mancanti: imposta planetio.eudr_user e planetio.eudr_apikey.'))

    dds_uuid = (getattr(record, 'dds_identifier', None) or '').strip()
    if not dds_uuid:
        raise UserError(_('Nessun DDS Identifier (UUID) presente sul record.'))

    root_tag = ICP.get_param('planetio.eudr_retrieval_root_tag')

    client = EUDRRetrievalClient(
        endpoint,
        username,
        apikey,
        wsse_mode,
        webservice_client_id=wsclient,
        retrieval_root_tag=root_tag,
    )

    # build + attach request for audit
    retrieval_xml = client.build_retrieval_xml(dds_uuid)
    envelope = client.build_retrieval_envelope(retrieval_xml)
    record.env['ir.attachment'].create({
        'name': f'DDS_Retrieve_Request_{record.id}.xml',
        'res_model': record._name,
        'res_id': record.id,
        'mimetype': 'text/xml',
        'type': 'binary',
        'eudr_document_visible': False,
        'datas': base64.b64encode(envelope.encode('utf-8')),
    })

    status, text = client.retrieve_dds(dds_uuid)

    # attach response
    record.env['ir.attachment'].create({
        'name': f'DDS_Retrieve_Response_{record.id}.xml',
        'res_model': record._name,
        'res_id': record.id,
        'mimetype': 'text/xml',
        'type': 'binary',
        'eudr_document_visible': False,
        'datas': base64.b64encode((text or '').encode('utf-8')),
    })

    if status != 200:
        wsid, errs = client.parse_business_errors(text)
        parts = [_('Errore Retrieval EUDR (%s)') % status]
        if wsid:
            parts.append(_('WS_REQUEST_ID: %s') % wsid)

        if errs:
            bullets = []
            for err in errs:
                code = err.get('code') or 'N/A'
                message = err.get('message') or '-'
                path = err.get('path') or '-'
                bullets.append(f"- [{code}] {message} (path: {path})")
            parts.append(_('Dettagli:') + '\n' + '\n'.join(bullets))
        else:
            faults = _extract_fault_messages(text)
            if faults:
                parts.append(_('Dettagli:') + '\n' + '\n'.join(f'- {msg}' for msg in faults))
            elif text:
                snippet = text.strip().splitlines()
                preview = '\n'.join(snippet[:5])[:400]
                if preview:
                    parts.append(_('Risposta:') + f"\n{preview}")

        raise UserError('\n\n'.join(parts))

    entries = client.parse_retrieval_result(text) or []
    hit = next((e for e in entries if (e.get('uuid') or '').strip() == dds_uuid), None)
    if not hit:
        available = ', '.join(
            e.get('uuid').strip()
            for e in entries
            if isinstance(e.get('uuid'), str) and e.get('uuid').strip()
        )
        msg = _('Retrieve OK ma nessuna voce restituita per il UUID.')
        if available:
            msg += _(' UUID disponibili: %s') % available
        record.message_post(body=msg)
        return False

    refno = hit.get('referenceNumber')
    verno = hit.get('verificationNumber')
    status_txt = hit.get('status')

    vals = {}
    if refno and hasattr(record, 'eudr_id'):
        vals['eudr_id'] = refno
    if verno and hasattr(record, 'eudr_verification_number'):
        vals['eudr_verification_number'] = verno
    if status_txt and hasattr(record, 'eudr_status'):
        vals['eudr_status'] = status_txt

    if vals:
        record.write(vals)

    record.message_post(body=_(
        'Retrieve DDS: status=<b>%s</b>%s%s' % (
            status_txt or '-',
            (', Reference=<b>%s</b>' % refno) if refno else '',
            (', Verification=<b>%s</b>' % verno) if verno else '',
        )
    ))

    if refno:
        _download_and_attach_dds_pdf(record, refno, username, apikey)

    return True
