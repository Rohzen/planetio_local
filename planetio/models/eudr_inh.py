from odoo import fields, models, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, date, timedelta
from zeep import Client, Plugin
from zeep.wsse.username import UsernameToken
from zeep.transports import Transport
from zeep.wsse.utils import WSU
from lxml import etree
from requests import Session
import requests, json, base64, hashlib, random, string, secrets

class LoggingPlugin(Plugin):
    def egress(self, envelope, http_headers, operation, binding_options):
        print("==== SOAP Request ====")
        print(etree.tostring(envelope, pretty_print=True).decode())
        return envelope, http_headers

    def ingress(self, envelope, http_headers, operation):
        print("==== SOAP Response ====")
        print(etree.tostring(envelope, pretty_print=True).decode())
        return envelope, http_headers

class CoffeeBatch(models.Model):
    _inherit = 'eudr.declaration'
    _order = 'questionnaire_date desc, planetio_days_left asc'

    status_planetio = fields.Selection([
        ('not_started', 'Questionnaire not filled out'),
        ('completed', 'Completed questionnaire'),
        ('transmitted', 'DDS transmitted'),
    ], string="Status questionnaire", default='not_started', readonly=True)

    activation_planetio_tab = fields.Date(string="Planetio activation date", readonly=True)
    questionnaire_date = fields.Datetime(string="Compilation date", readonly=True)
    questionnaire_compiler = fields.Many2one("res.partner", string="Compiler", domain="[('is_company', '=', False)]")
    questionnaire_validated = fields.Boolean(string="Validated questionnaire", default=False)
    planetio_days_left = fields.Integer(string="EUDR questionnaire deadline days", compute="_compute_planetio_days_left")
    questionnaire_score = fields.Integer(string="Score obtained", readonly=True)
    questionnaire_max_score = fields.Integer(string="Maximum score", readonly=True)
    warning_planetio_days_left = fields.Boolean(default=False, compute="_compute_warning_planetio_days_left")
    warning_text_planetio_days_left = fields.Char(string="Warning text days to expiry of EUDR questionnaire", compute="_compute_warning_planetio_days_left")
    questionnaire_score_display = fields.Char(string="Score", compute="_compute_questionnaire_score_display", store=False)
    questionnaire_score_status = fields.Selection([('red', 'Low'), ('yellow', 'Medium'), ('green', 'High'),], compute='_compute_questionnaire_score_status', store=False)
    legend_planetio_score = fields.Char(string="Legend", compute="_compute_legend_planetio_score", store=False)
    geo_analysis_id = fields.Many2one('caffe.crudo.geo.analysis', string="Geo Analysis", ondelete='set null')
    geojson_upload_file = fields.Binary(string="Load GeoJSON")
    geojson_upload_filename = fields.Char(string=" GeoJSON file name")

    # Related GEO Analysis fields
    name = fields.Char(string="Name", related='geo_analysis_id.name', store=True)
    latitude = fields.Float(string="Latitude", related='geo_analysis_id.latitude', store=True)
    longitude = fields.Float(string="Longitude", related='geo_analysis_id.longitude', store=True)
    geojson_data = fields.Text(string="GeoJSON", related='geo_analysis_id.geojson_data', store=True)
    area_analyzed = fields.Float(string="Area Analyzed (ha)", related='geo_analysis_id.area_analyzed', store=True)
    analyzed_at = fields.Datetime(string="Analyzed At", related='geo_analysis_id.analyzed_at', store=True)
    pass_check = fields.Boolean(string="Pass Check", related='geo_analysis_id.pass_check', store=True)
    farm_area = fields.Float(string="Farm Area (ha)", related='geo_analysis_id.farm_area', store=True)
    country_name = fields.Char(string="Country", related='geo_analysis_id.country_name', store=True)
    country_code = fields.Char(string="Country Code", related='geo_analysis_id.country_code', store=True)
    country_risk = fields.Char(string="Country Risk Level", related='geo_analysis_id.country_risk', store=True)
    country_value = fields.Float(string="Country Risk Value", related='geo_analysis_id.country_value', store=True)
    deforestation_free = fields.Boolean(string="Deforestation Free", related='geo_analysis_id.deforestation_free', store=True)
    deforestation_area = fields.Float(string="Deforestation Area (ha)", related='geo_analysis_id.deforestation_area', store=True)
    built_area_overlap = fields.Float(string="Built Area Overlap (ha)", related='geo_analysis_id.built_area_overlap', store=True)
    water_overlap = fields.Float(string="Water Overlap (ha)", related='geo_analysis_id.water_overlap', store=True)
    protected_area_overlap = fields.Float(string="Protected Area Overlap (ha)", related='geo_analysis_id.protected_area_overlap', store=True)
    protected_free = fields.Boolean(string="Protected Free", related='geo_analysis_id.protected_free', store=True)
    reasonable_size = fields.Boolean(string="Reasonable Size", related='geo_analysis_id.reasonable_size', store=True)
    data_integrity = fields.Boolean(string="Data Integrity", related='geo_analysis_id.data_integrity', store=True)
    is_on_land = fields.Boolean(string="Is on Land", related='geo_analysis_id.is_on_land', store=True)
    is_not_within_urban_area = fields.Boolean(string="Not Within Urban Area", related='geo_analysis_id.is_not_within_urban_area', store=True)
    elevation_check = fields.Boolean(string="Elevation Check", related='geo_analysis_id.elevation_check', store=True)
    commodity_region_check = fields.Boolean(string="Commodity Region Check", related='geo_analysis_id.commodity_region_check', store=True)

    progress_html = fields.Char(string="Progress Bar", compute="_compute_progress_html", store=False)

    attachments_ids = fields.One2many('planetio.attachment', 'batch_id', string="Documenti")
    attach_geojson_upload_file = fields.Binary(string="GeoJSON")
    attach_geojson_upload_filename = fields.Char(string=" GeoJSON file name")

    # GeoJSON raw
    geojson_data = fields.Text(related='geo_analysis_id.geojson_data', store=True)

    # cumulative_dds_ids = fields.Many2many(
    #     'caffe.crudo.todo.batch',
    #     'batch_cumulative_dds_rel',
    #     'source_batch_id',
    #     'linked_dds_id',
    #     string="Linked DDS"
    # )

    eudr_type_override = fields.Selection([
        ('trader', 'Trader'),
        ('operator', 'Operator')
    ], string="EUDR Role (Mixed)", default='trader', help="Specify whether you're acting as Trader or Operator for this batch.")

    eudr_third_party_client_id = fields.Many2one(
        'res.partner', string="Client (3rd Party Trader)", help="Client on behalf of whom the DDS is being submitted."
    )

    eudr_company_type = fields.Selection([
        ('trader', 'Trader'),
        ('operator', 'Operator'),
        ('mixed', 'Mixed'),
        ('third_party_trader', 'Third-party Trader')
    ], string="Company Type", compute="_compute_eudr_company_type", store=False)

    @api.depends()
    def _compute_eudr_company_type(self):
        config_type = self.env['ir.config_parameter'].sudo().get_param('planetio.eudr_company_type')
        for record in self:
            record.eudr_company_type = config_type

    @api.constrains('eudr_company_type', 'eudr_type_override', 'eudr_third_party_client_id')
    def _check_eudr_fields(self):
        for rec in self:
            # Applichiamo i controlli solo quando la partita è confermata
            if rec.state != 'confirmed':
                continue

            if rec.eudr_company_type == 'mixed' and not rec.eudr_type_override:
                raise ValidationError("You must select whether you're acting as Trader or Operator.")
            if rec.eudr_company_type == 'third_party_trader' and not rec.eudr_third_party_client_id:
                raise ValidationError("You must select the client you're operating for.")

    questionnaire_answer_ids_section_1 = fields.One2many(
        "planetio.questionnaire.answer", "batch_id", domain=[('section', '=', '1')]
    )
    questionnaire_answer_ids_section_2 = fields.One2many(
        "planetio.questionnaire.answer", "batch_id", domain=[('section', '=', '2')]
    )
    questionnaire_answer_ids_section_3 = fields.One2many(
        "planetio.questionnaire.answer", "batch_id", domain=[('section', '=', '3')]
    )
    questionnaire_answer_ids_section_4 = fields.One2many(
        "planetio.questionnaire.answer", "batch_id", domain=[('section', '=', '4')]
    )
    questionnaire_answer_ids_section_5 = fields.One2many(
        "planetio.questionnaire.answer", "batch_id", domain=[('section', '=', '5')]
    )
    questionnaire_answer_ids_section_6 = fields.One2many(
        "planetio.questionnaire.answer", "batch_id", domain=[('section', '=', '6')]
    )
    questionnaire_answer_ids_section_7 = fields.One2many(
        "planetio.questionnaire.answer", "batch_id", domain=[('section', '=', '7')]
    )

    @api.depends('activation_planetio_tab')
    def _compute_planetio_days_left(self):
        #Calcola il countdown dei giorni rimanenti per la compilazione del questionario PLANETIO
        for record in self:
            if record.questionnaire_validated:
                record.update({'planetio_days_left': False}) # Campo vuoto se il questionario è stato convalidato
            elif record.activation_planetio_tab:
                deadline = record.activation_planetio_tab + timedelta(days=15)
                today = date.today()
                days_left = (deadline - today).days
                record.planetio_days_left = days_left if days_left >= 0 else 0 # Se scaduto, mostra 0
            else:
                record.update({'planetio_days_left': False}) # Campo vuoto se la tab non è attiva

    def _compute_warning_planetio_days_left(self):
        for item in self:
            item.warning_planetio_days_left = False
            item.warning_text_planetio_days_left = ""

            if item.questionnaire_validated:
                # Calcolo il livello a parole
                level_text = ""
                if item.questionnaire_max_score:
                    low = int(item.questionnaire_max_score / 3)
                    medium = int((2 * item.questionnaire_max_score) / 3)
                    score = item.questionnaire_score

                    if score <= low:
                        level_text = _("LOW")
                    elif score <= medium:
                        level_text = _("MEDIUM")
                    else:
                        level_text = _("HIGH")

                item.warning_planetio_days_left = True
                item.warning_text_planetio_days_left = _(
                    "Validated questionnaire. Score obtained %(score)s out of %(max_score)s (%(level)s)."
                ) % {
                    'score': item.questionnaire_score,
                    'max_score': item.questionnaire_max_score,
                    'level': level_text
                }
            elif item.planetio_days_left:
                item.warning_planetio_days_left = True
                item.warning_text_planetio_days_left = _(
                    "Please, note that there are %(days)s days left to complete the EUDR questionnaire."
                ) % {
                    'days': item.planetio_days_left
                }
            else:
                item.warning_planetio_days_left = False
                item.warning_text_planetio_days_left = ""

    @api.depends('questionnaire_score', 'questionnaire_max_score')
    def _compute_questionnaire_score_display(self):
        for record in self:
            if record.questionnaire_validated:
                score_text = ""
                if record.questionnaire_max_score:
                    max_score = record.questionnaire_max_score
                    score = record.questionnaire_score
                    if score <= max_score / 3:
                        score_text = _("LOW")
                    elif score <= (2 * max_score) / 3:
                        score_text = _("MEDIUM")
                    else:
                        score_text = _("HIGH")
                record.questionnaire_score_display = _(
                    "%(score)s out of %(max_score)s - %(text)s"
                ) % {
                    'score': record.questionnaire_score,
                    'max_score': record.questionnaire_max_score,
                    'text': score_text
                }
            else:
                record.questionnaire_score_display = ""

    @api.depends('questionnaire_score', 'questionnaire_max_score')
    def _compute_questionnaire_score_status(self):
        for rec in self:
            if rec.questionnaire_validated and rec.questionnaire_max_score:
                score = rec.questionnaire_score
                max_score = rec.questionnaire_max_score
                if score <= max_score / 3:
                    rec.questionnaire_score_status = 'red'
                elif score <= (2 * max_score) / 3:
                    rec.questionnaire_score_status = 'yellow'
                else:
                    rec.questionnaire_score_status = 'green'
            else:
                rec.questionnaire_score_status = False

    @api.model
    def create(self, vals):
        record = super().create(vals)
        questions = self.env["planetio.question"].search([])
        for question in questions:
            self.env["planetio.questionnaire.answer"].create({
                "batch_id": record.id,
                "question_id": question.id,
            })
        return record
    
    def action_validate_questionnaire(self):
        # Convalida il questionario, imposta readonly e cambia stato
        for record in self:
            total_score = 0
            max_possible_score = 0
            
            answers = self.env["planetio.questionnaire.answer"].search([('batch_id', '=', record.id)])
            
            for answer in answers:
                question = answer.question_id
                if question:
                    weight = int(question.weight)
                    score = question.score
                    max_possible_score += score * weight
                    if answer.answer == "yes":
                        total_score += score * weight
                        
            record.write({
                'questionnaire_validated': True,
                'status_planetio': 'completed',
                'questionnaire_date': datetime.now(),
                'questionnaire_score': total_score,
                'questionnaire_max_score': max_possible_score
            })

            # **Logga nel Chatter**
            record.message_post(
                body=_(
                    "The EUDR Questionnaire has been validated. Score obtained: %(score)s out of %(max_score)s."
                ) % {
                    'score': total_score,
                    'max_score': max_possible_score
                },
                message_type="notification"
            )

    def action_send_questionnaire_reminder(self):
        for record in self:
            compiler = record.questionnaire_compiler

            if not compiler or not compiler.email:
                raise UserError(_("The compiler does not have an associated email address."))

            # Cerchiamo oppure creiamo token se non esiste
            token_obj = self.env['planetio.token.access'].sudo()
            existing_token = token_obj.search([
                ('batch_id', '=', record.id),
                ('active', '=', True),
            ], limit=1)

            if not existing_token:
                existing_token = token_obj.create({
                    'batch_id': record.id,
                    'active': True,
                    'expiration_date': fields.Date.today() + timedelta(days=15),
                })

            # Calcolo giorni alla scadenza
            giorni = record.planetio_days_left or _("few")

            # Costruisco URL pubblico con token
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            public_url = f"{base_url}/planetio/questionario/{existing_token.name}"

            # Contenuto dell’email
            subject = _("EUDR questionnaire completion reminder")
            body_html = _(
                """<p>Gentle %(name)s,</p>
                <p>There are <strong>%(days)s days</strong> left to complete the EUDR questionnaire for the batch <strong>%(protocol)s</strong>.</p>
                <p>Click on the following link to fill in and validate the data entered:</p>
                <p><a href="%(url)s">Fill out the questionnaire</a></p>
                <br/>
                <p>--</p>
                <p>PLANETIO</p>"""
            ) % {
                'name': compiler.name,
                'days': giorni,
                'protocol': record.protocol_number,
                'url': public_url
            }

            # Invio email
            mail_values = {
                'subject': subject,
                'body_html': body_html,
                'email_to': compiler.email,
                'auto_delete': True,
                'email_from': self.env.user.email_formatted or self.env.company.email,
            }
            self.env['mail.mail'].create(mail_values).send()

            # Notifica nel Chatter
            record.message_post(
                body=_(
                    "The reminder was sent to <strong>%(name)s</strong> (%(email)s).<br/>"
                    "<a href='%(url)s' target='_blank'>Public link to the questionnaire</a>"
                ) % {
                    'name': compiler.display_name,
                    'email': compiler.email,
                    'url': public_url,
                },
                message_type="notification"
            )

    def action_print_dds(self):
        return self.env.ref('planetio_todo.report_dds').report_action(self)
    
    def copy(self, default=None):
        # Quando viene duplicata una partita di caffè, il questionario deve essere resettato
        default = dict(default or {})

        # Reset dello stato del questionario e rimozione della convalida
        default.update({
            'status_planetio': 'not_started', # Imposta lo stato su "Questionario Non Compilato"
            'questionnaire_validated': False, # Rimuove la convalida
            'questionnaire_date': False, # Rimuove la data di compilazione
            'questionnaire_compiler': False, # Rimuove il compilatore del questionario
            'activation_planetio_tab': False, # Svuota la data di attivazione della tab PLANETIO
            'planetio_days_left': False, # Resetta anche i giorni rimasti
            'geo_analysis_id': False, # Svuota la Geolocalizzazione
            'geojson_upload_file': False, # Svuota eventuale file caricato
            'geojson_upload_filename': False, # Svuota il nome file caricato
            'eudr_type_override': False, # Svuota il tipo di Azienda che effettua la DDS
            'eudr_third_party_client_id': False, # Svuota il cliente per la quale stiamo effettuando la DDS
        })

        return super(CoffeeBatch, self).copy(default)
    
    def write(self, vals):
        #Intercetta il cambio di stato e salva la data di attivazione della tab Planetio se non è già valorizzata
        for record in self:
            new_state = vals.get('state')
            if new_state == 'confirmed' and record.state == 'draft' and not record.activation_planetio_tab:
                vals['activation_planetio_tab'] = date.today()
                
                record.message_post(
                    body=_("The EUDR tab has been activated. The questionnaire can now be filled out."),
                    message_type="notification"
                )
        return super(CoffeeBatch, self).write(vals)
    
    def open_otp_wizard(self):
        self.ensure_one()

        # Simula invio OTP
        self.message_post(body=_("OTP sent to the phone number entered during certification."))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'otp.verification.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_batch_id': self.id
            }
        }

    # messo in services per evitare dipendenze circolari e troppe modifiche al codice esistente
    def action_transmit_dds(self):
        from ..services.eudr_adapter_odoo import submit_dds_for_batch
        for record in self:
            if record.status_planetio != 'completed':
                raise UserError(_("Puoi trasmettere la DDS solo se il questionario è completato."))
            dds_id = submit_dds_for_batch(record)

    @api.depends('questionnaire_score', 'questionnaire_max_score')
    def _compute_legend_planetio_score(self):
        for record in self:
            if record.questionnaire_validated and record.questionnaire_max_score:
                low = int(record.questionnaire_max_score / 3)
                medium = int((2 * record.questionnaire_max_score) / 3)
                record.legend_planetio_score = _(
                    "LEGEND: %(low_min)d - %(low_max)d: LOW | %(med_min)d - %(med_max)d: MEDIUM | %(high_min)d - %(high_max)d: HIGH"
                ) % {
                    'low_min': 0,
                    'low_max': low,
                    'med_min': low + 1,
                    'med_max': medium,
                    'high_min': medium + 1,
                    'high_max': record.questionnaire_max_score,
                }
            else:
                record.legend_planetio_score = ""

    def action_download_farm_geojson(self):
        for record in self:
            uid = record.protocol_number
            if not uid:
                raise UserError(_("Missing UID to query the farm analysis."))

            api_key = self.env['ir.config_parameter'].sudo().get_param('planetio.pftp_api_key')
            if not api_key:
                raise UserError(_("Missing API key for Tracer."))

            url = f"https://tracer-development.azure.startplanting.org/api/farm-data?uid={uid}"
            headers = {"x-api-key": api_key}

            try:
                response = requests.get(url, headers=headers, timeout=30)
                if response.status_code == 200:
                    geojson_data = response.json()
                    geojson_str = json.dumps(geojson_data, indent=2)

                    # Elimina vecchia analisi
                    record.geo_analysis_id.unlink()

                    props = geojson_data.get("features", [{}])[0].get("properties", {})
                    geometry = geojson_data.get("features", [{}])[0].get("geometry", {})
                    analyses = props.get("analyses", [{}])[0]
                    coords = geometry.get("coordinates", [])

                    try:
                        if geometry.get("type") == "Polygon":
                            lon, lat = coords[0][0]
                        elif geometry.get("type") == "MultiPolygon":
                            lon, lat = coords[0][0][0]
                        else:
                            lon, lat = 0.0, 0.0
                    except Exception:
                        lon, lat = 0.0, 0.0

                    analysis = self.env['caffe.crudo.geo.analysis'].create({
                        'batch_id': record.id,
                        'name': f"Farm for UID {uid}",
                        'latitude': lat,
                        'longitude': lon,
                        'geojson_data': geojson_str,
                        'farm_area': props.get('farmArea', 0),
                        'country_name': props.get('countryName', ''),
                        'country_code': props.get('countryCode', ''),
                        'country_risk': props.get('countryRisk', ''),
                        'country_value': props.get('countryValue', 0),
                        'deforestation_free': analyses.get('deforestationFree', False),
                        'protected_free': analyses.get('protectedFree', False),
                        'reasonable_size': analyses.get('reasonableSize', False),
                        'data_integrity': analyses.get('dataIntegrity', False),
                        'is_on_land': analyses.get('isOnLand', False),
                        'is_not_within_urban_area': analyses.get('isNotWithinUrbanArea', False),
                        'elevation_check': analyses.get('elevationCheck', False),
                        'commodity_region_check': analyses.get('commodityRegionCheck', False),
                        'deforestation_area': analyses.get('area', 0),
                        'built_area_overlap': props.get('builtArea', 0),
                        'water_overlap': props.get('waterArea', 0),
                        'protected_area_overlap': props.get('protectedArea', 0),
                        'analyzed_at': datetime.strptime(props.get('analyzedAt', '')[:19], "%Y-%m-%dT%H:%M:%S") if props.get('analyzedAt') else False,
                    })

                    record.geo_analysis_id = analysis.id
                    record.message_post(body=_("GeoJSON data successfully retrieved and saved."))
                elif response.status_code == 404:
                    raise UserError(_("No data found for this UID."))
                else:
                    raise UserError(_("Tracer API error: %s") % response.text)
            except Exception as e:
                raise UserError(_("Error during API request: %s") % str(e))
        
    def action_upload_farm_geojson(self):
        for record in self:
            if not record.geojson_upload_file:
                raise UserError(_("Nessun file GeoJSON caricato."))
            if not record.protocol_number:
                raise UserError(_("UID (protocol_number) mancante."))

            try:
                geojson_bytes = base64.b64decode(record.geojson_upload_file)
                geojson_str = geojson_bytes.decode('utf-8')
                geojson_data = json.loads(geojson_str)

                payload = {
                    "geoJSON": {
                        "type": "FeatureCollection",
                        "features": [{
                            "type": "Feature",
                            "properties": {
                                "uid": record.protocol_number,
                                "commodity": ["coffee"]
                            },
                            "geometry": geojson_data.get("features", [{}])[0].get("geometry")
                        }]
                    }
                }

                api_key = self.env['ir.config_parameter'].sudo().get_param('planetio.pftp_api_key')
                if not api_key:
                    raise UserError(_("API key per EUDR Tracer mancante."))

                response = requests.post(
                    url="https://tracer-development.azure.startplanting.org/api/farm-data",
                    headers={"x-api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=30
                )

                if response.status_code != 200:
                    raise UserError(_("Errore da Tracer: %s") % response.text)

                analysis_data = response.json()
                geojson_str = json.dumps(analysis_data, indent=2)

                record.geo_analysis_id and record.geo_analysis_id.unlink()

                props = analysis_data.get("features", [{}])[0].get("properties", {})
                geometry = geojson_data.get("features", [{}])[0].get("geometry", {})
                analyses = props.get("analyses", [{}])[0]
                coords = geometry.get("coordinates", [])

                try:
                    if geometry.get("type") == "Polygon":
                        lon, lat = coords[0][0]
                    elif geometry.get("type") == "MultiPolygon":
                        lon, lat = coords[0][0][0]
                    else:
                        lon, lat = 0.0, 0.0
                except Exception:
                    lon, lat = 0.0, 0.0

                analysis = self.env['caffe.crudo.geo.analysis'].create({
                    'batch_id': record.id,
                    'name': f"Farm for UID {record.protocol_number}",
                    'latitude': lat,
                    'longitude': lon,
                    'geojson_data': geojson_str,
                    'farm_area': props.get('farmArea', 0),
                    'country_name': props.get('countryName', ''),
                    'country_code': props.get('countryCode', ''),
                    'country_risk': props.get('countryRisk', ''),
                    'country_value': props.get('countryValue', 0),
                    'deforestation_free': analyses.get('deforestationFree', False),
                    'protected_free': analyses.get('protectedFree', False),
                    'reasonable_size': analyses.get('reasonableSize', False),
                    'data_integrity': analyses.get('dataIntegrity', False),
                    'is_on_land': analyses.get('isOnLand', False),
                    'is_not_within_urban_area': analyses.get('isNotWithinUrbanArea', False),
                    'elevation_check': analyses.get('elevationCheck', False),
                    'commodity_region_check': analyses.get('commodityRegionCheck', False),
                    'deforestation_area': analyses.get('area', 0),
                    'built_area_overlap': props.get('builtArea', 0),
                    'water_overlap': props.get('waterArea', 0),
                    'protected_area_overlap': props.get('protectedArea', 0),
                    'analyzed_at': datetime.strptime(props.get('analyzedAt', '')[:19], "%Y-%m-%dT%H:%M:%S") if props.get('analyzedAt') else False,
                })

                record.geo_analysis_id = analysis.id
                record.geojson_upload_file = False
                record.geojson_upload_filename = False

                record.message_post(body=_("File caricato e inviato a Tracer con successo. Analisi completata."))
            except Exception as e:
                raise UserError(_("Errore durante l'upload: %s") % str(e))
            
    def action_open_map_on_geojson(self):
        for record in self:
            if not record.geo_analysis_id or not record.geo_analysis_id.geojson_data:
                raise UserError(_("Missing GeoJSON data to open the map."))

            # Encode GeoJSON in base64 (URL safe) per passarlo tramite query param
            import urllib.parse
            import json

            geojson_str = record.geo_analysis_id.geojson_data
            encoded_geojson = urllib.parse.quote(geojson_str)

            url = f"https://geojson.io/#data=data:application/json,{encoded_geojson}"

            return {
                'type': 'ir.actions.act_url',
                'url': url,
                'target': 'new',
            }

    def _compute_progress_html(self):
        for rec in self:
            if rec.questionnaire_validated and rec.questionnaire_max_score:
                score = rec.questionnaire_score
                max_score = rec.questionnaire_max_score
                percentage = int((score / max_score) * 100) if max_score else 0

                if score <= max_score / 3:
                    color = 'bg-danger'
                elif score <= (2 * max_score) / 3:
                    color = 'bg-warning'
                else:
                    color = 'bg-success'

                rec.progress_html = f"""
                    <div class="progress rounded-pill" style="position: relative; height: 20px; overflow: hidden; background-color: #e9ecef; border: 1px solid #ced4da;">
                        <!-- Segmenti soglia -->
                        <div style="position: absolute; left: 33%; top: 0; bottom: 0; width: 2px; background: repeating-linear-gradient(
                            to bottom,
                            #555,
                            #555 2px,
                            transparent 2px,
                            transparent 4px
                        ); opacity: 0.5;"></div>
                        <div style="position: absolute; left: 66%; top: 0; bottom: 0; width: 2px; background: repeating-linear-gradient(
                            to bottom,
                            #555,
                            #555 2px,
                            transparent 2px,
                            transparent 4px
                        ); opacity: 0.5;"></div>

                        <!-- Progress effettivo -->
                        <div class="progress-bar {color} text-white" role="progressbar"
                            style="width: {percentage}%; font-weight: bold; font-size: 1.5em;">
                            {percentage}%
                        </div>
                    </div>
                """
            else:
                rec.progress_html = ""

    def action_analyze_documentation(self):
        for rec in self:
            if not rec.attach_geojson_upload_file:
                raise UserError("Nessun GeoJSON allegato.")
            if not rec.attachments_ids:
                raise UserError("Nessun documento allegato.")
            raise UserError("Attenzione: è consigliabile allegare una certificazione di sostenibilità riconosciuta (ad esempio Rainforest Alliance, UTZ, Fairtrade, FSC, PEFC). \n Il lotto di terra alle coordinate [37.6111, -0.4563], [37.6125, -0.4561], [37.612, -0.455], [37.6111, -0.4563] risulta in una porzione di terra ad alto rischio deforestazione.")

    def action_load_cumulative_dds(self):
        for rec in self:
            if not rec.cumulative_dds_ids:
                raise UserError("Nessuna DDS allegata.")
            
            rec.message_post(
                body="DDS cumulative caricate correttamente.",
                message_type="notification"
            )

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Operazione completata',
                    'message': 'DDS caricate correttamente.',
                    'type': 'info',  # tipi: success / warning / danger / info
                    'sticky': False,
                }
            }
