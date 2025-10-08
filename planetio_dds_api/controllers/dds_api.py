import json
import logging

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.planetio.services.eudr_client_retrieve import EUDRRetrievalClient
from odoo.addons.planetio.services.eudr_adapter_odoo import _extract_fault_messages

_logger = logging.getLogger(__name__)


class DDSApiController(http.Controller):
    """Expose a small JSON API to create and transmit DDS declarations."""

    # ------------------------------------------------------------------
    # API endpoints
    # ------------------------------------------------------------------

    @http.route(
        '/api/dds/minimal_submit',
        type='json',
        auth='user',
        methods=['POST'],
        csrf=False,
    )
    def api_create_and_transmit_dds(self, **payload):
        """Create an :model:`eudr.declaration` and trigger transmission.

        Expected payload structure::

            {
                "partner_id": 42,                 # optional if ``partner`` block is provided
                "partner": {                     # optional block to create a partner on the fly
                    "name": "Importer SpA",
                    "vat": "IT12345678901",
                    "country_code": "IT",
                    "street": "Via Roma 1",
                    "zip": "00100",
                    "city": "Roma"
                },
                "activity_type": "import",      # optional, defaults to "import"
                "net_mass_kg": 12.5,             # required
                "hs_code": "090111",            # optional, defaults to 090111
                "producer_name": "Farm Coop",   # optional
                "lines": [                       # at least one geometry line is required
                    {
                        "name": "Plot 1",
                        "farmer_name": "John Doe",
                        "country": "BR",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [-51.5, -9.2]
                        }
                    }
                ]
            }

        The response contains the created record id together with the DDS
        identifier and the reference number returned by TRACES, if available.
        """

        payload = payload or {}
        try:
            record = self._create_declaration_from_payload(payload)
            record.action_transmit_dds()
            record.invalidate_cache()
            response = {
                'ok': True,
                'id': record.id,
                'name': record.name,
                'dds_identifier': record.dds_identifier,
                'reference_number': record.eudr_id,
                'stage': record.stage_id.display_name if record.stage_id else None,
            }
            # Add verification number if field is available on the model
            if hasattr(record, 'eudr_verification_number'):
                response['verification_number'] = record.eudr_verification_number
            return response
        except UserError as exc:
            request.env.cr.rollback()
            return {
                'ok': False,
                'error': str(exc),
                'error_type': 'user_error',
            }
        except Exception as exc:  # pragma: no cover - defensive logging
            request.env.cr.rollback()
            _logger.exception('Unexpected error while creating DDS via API')
            return {
                'ok': False,
                'error': _('Unexpected server error while creating DDS.'),
                'error_type': 'server_error',
            }

    @http.route(
        '/api/dds/retrieve_by_identifier',
        type='json',
        auth='user',
        methods=['POST'],
        csrf=False,
    )
    def api_retrieve_by_identifier(self, **payload):
        """Retrieve DDS information from TRACES using a DDS identifier (UUID).

        Returns a structure like::

            {
                "status": "success",
                "httpStatus": 200,
                "data": [
                    {
                        "identifier": "...",
                        "internalReferenceNumber": "...",
                        "referenceNumber": "...",
                        "verificationNumber": "...",
                        "status": "AVAILABLE",
                        "date": "2025-09-18T23:05:02.000Z",
                        "updatedBy": "Operator Name"
                    }
                ]
            }
        """

        payload = payload or {}
        identifier = (payload.get('identifier') or payload.get('dds_identifier') or '').strip()
        if not identifier:
            return {
                'status': 'error',
                'httpStatus': 400,
                'message': _('The field "identifier" is required.'),
                'data': [],
            }

        try:
            client = self._build_retrieval_client()
        except UserError as exc:
            return {
                'status': 'error',
                'httpStatus': 500,
                'message': str(exc),
                'data': [],
            }

        try:
            result = client.get_numbers(identifier)
        except Exception:  # pragma: no cover - defensive
            _logger.exception('Unexpected error while retrieving DDS identifier %s', identifier)
            return {
                'status': 'error',
                'httpStatus': 500,
                'message': _('Unexpected error while retrieving DDS data.'),
                'data': [],
            }

        http_status = result.get('httpStatus') or 500
        if http_status != 200:
            message = self._format_retrieval_error(client, result)
            return {
                'status': 'error',
                'httpStatus': http_status,
                'message': message,
                'data': [],
            }

        entry = {
            'identifier': identifier,
            'internalReferenceNumber': result.get('internalReferenceNumber'),
            'referenceNumber': result.get('referenceNumber'),
            'verificationNumber': result.get('verificationNumber'),
            'status': (result.get('status') or '').upper() if result.get('status') else None,
            'date': result.get('date'),
            'updatedBy': result.get('updatedBy'),
        }

        return {
            'status': 'success',
            'httpStatus': http_status,
            'data': [entry],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_declaration_from_payload(self, payload):
        Declaration = request.env['eudr.declaration'].sudo()

        partner = self._resolve_partner(payload)

        activity_type = (payload.get('activity_type') or 'import').lower()
        if activity_type not in {'import', 'export', 'domestic'}:
            raise UserError(
                _('Invalid activity_type %s. Allowed values are: import, export, domestic.')
                % activity_type
            )

        net_mass_raw = payload.get('net_mass_kg')
        if net_mass_raw is None:
            raise UserError(_('The field net_mass_kg is required.'))
        try:
            net_mass = float(net_mass_raw)
        except (TypeError, ValueError):
            raise UserError(_('The field net_mass_kg must be a number.'))
        if net_mass <= 0:
            raise UserError(_('The field net_mass_kg must be greater than zero.'))

        lines_payload = payload.get('lines') or []
        if not isinstance(lines_payload, list):
            raise UserError(_('The field lines must be a list of objects.'))
        if not lines_payload:
            raise UserError(_('At least one line with a GeoJSON geometry is required.'))

        line_commands = [(0, 0, self._prepare_line_vals(line)) for line in lines_payload]

        values = {
            'partner_id': partner.id,
            'activity_type': activity_type,
            'net_mass_kg': net_mass,
            'hs_code': payload.get('hs_code') or '090111',
            'producer_name': payload.get('producer_name'),
            'operator_name': payload.get('operator_name'),
            'extra_info': payload.get('extra_info'),
            'product_description': payload.get('product_description'),
            'common_name': payload.get('common_name'),
            'line_ids': line_commands,
        }

        if payload.get('name'):
            values['name'] = payload['name']

        operator_type = payload.get('operator_type')
        if operator_type:
            operator_type = operator_type.upper()
            if operator_type not in {'TRADER', 'OPERATOR'}:
                raise UserError(_('operator_type must be either TRADER or OPERATOR.'))
            values['eudr_type_override'] = operator_type

        if payload.get('coffee_species_id'):
            values['coffee_species'] = payload['coffee_species_id']
        if payload.get('product_id'):
            values['product_id'] = payload['product_id']
        if payload.get('third_party_client_id'):
            values['eudr_third_party_client_id'] = payload['third_party_client_id']

        record = Declaration.create(values)
        return record

    def _build_retrieval_client(self):
        ICP = request.env['ir.config_parameter'].sudo()

        endpoint = (
            ICP.get_param('planetio.eudr_retrieval_endpoint')
            or 'https://webgate.acceptance.ec.europa.eu/tracesnt-alpha/ws/EUDRRetrievalServiceV1'
        )
        username = ICP.get_param('planetio.eudr_user') or ''
        apikey = ICP.get_param('planetio.eudr_apikey') or ''
        wsse_mode = (ICP.get_param('planetio.eudr_wsse_mode') or 'digest').lower()
        wsclient = ICP.get_param('planetio.eudr_webservice_client_id') or 'eudr-test'
        root_tag = ICP.get_param('planetio.eudr_retrieval_root_tag')

        if not username or not apikey:
            raise UserError(_('EUDR credentials are missing. Configure planetio.eudr_user and planetio.eudr_apikey.'))

        return EUDRRetrievalClient(
            endpoint,
            username,
            apikey,
            wsse_mode,
            webservice_client_id=wsclient,
            retrieval_root_tag=root_tag,
        )

    def _format_retrieval_error(self, client, result):
        http_status = result.get('httpStatus') or 500
        raw = result.get('raw') or ''
        wsid, errs = client.parse_business_errors(raw)

        parts = [_('Errore Retrieval EUDR (%s)') % http_status]
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
            faults = _extract_fault_messages(raw)
            if faults:
                parts.append(_('Dettagli:') + '\n' + '\n'.join(f'- {msg}' for msg in faults))
            elif raw:
                snippet = raw.strip().splitlines()
                preview = '\n'.join(snippet[:5])[:400]
                if preview:
                    parts.append(_('Risposta:') + f"\n{preview}")

        return '\n\n'.join(parts)

    def _resolve_partner(self, payload):
        Partner = request.env['res.partner'].sudo()
        partner_id = payload.get('partner_id')
        if partner_id:
            partner = Partner.browse(partner_id)
            if not partner.exists():
                raise UserError(_('Partner with id %s was not found.') % partner_id)
            return partner

        partner_vals = payload.get('partner') or {}
        name = partner_vals.get('name')
        if not name:
            raise UserError(_('Provide either an existing partner_id or partner.name.'))

        vals = {'name': name}
        for field in ('vat', 'street', 'street2', 'zip', 'city', 'email', 'phone'):
            if partner_vals.get(field):
                vals[field] = partner_vals[field]

        country_code = partner_vals.get('country_code')
        if country_code:
            Country = request.env['res.country'].sudo()
            country = Country.search([('code', '=', country_code.upper())], limit=1)
            if not country:
                raise UserError(_('Unknown country_code %s.') % country_code)
            vals['country_id'] = country.id

        state_code = partner_vals.get('state_code')
        if state_code and vals.get('country_id'):
            State = request.env['res.country.state'].sudo()
            state = State.search(
                [
                    ('code', '=', state_code.upper()),
                    ('country_id', '=', vals['country_id']),
                ],
                limit=1,
            )
            if state:
                vals['state_id'] = state.id

        return Partner.create(vals)

    def _prepare_line_vals(self, line):
        if not isinstance(line, dict):
            raise UserError(_('Each line must be a JSON object.'))

        geometry = line.get('geometry')
        if isinstance(geometry, str):
            try:
                geometry = json.loads(geometry)
            except Exception:
                raise UserError(_('Geometry must be a valid JSON object.'))
        if not isinstance(geometry, dict):
            raise UserError(_('Each line requires a geometry object.'))

        geo_type = geometry.get('type')
        if geo_type not in {'Point', 'Polygon', 'MultiPolygon'}:
            raise UserError(_('Unsupported geometry type %s.') % geo_type)

        coordinates = geometry.get('coordinates')
        if coordinates in (None, []):
            raise UserError(_('Geometry coordinates are missing.'))

        line_vals = {
            'name': line.get('name'),
            'farmer_name': line.get('farmer_name'),
            'farmer_id_code': line.get('farmer_id_code'),
            'tax_code': line.get('tax_code'),
            'country': line.get('country'),
            'region': line.get('region'),
            'municipality': line.get('municipality'),
            'farm_name': line.get('farm_name'),
            'geo_type_raw': geo_type,
            'geo_type': 'point' if geo_type == 'Point' else 'polygon',
            'geometry': json.dumps(geometry, ensure_ascii=False),
        }

        area = line.get('area_ha')
        if area is not None:
            line_vals['area_ha'] = str(area)

        return line_vals
