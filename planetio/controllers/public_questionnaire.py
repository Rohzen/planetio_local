from odoo import http, _
from odoo.http import request
from werkzeug.utils import secure_filename
import base64

class PlanetioPublicController(http.Controller):

    @http.route(['/planetio/questionario/<string:token>'], type='http', auth='public', website=True)
    def public_questionnaire(self, token, **kwargs):
        access = request.env['planetio.token.access'].sudo().search([('name', '=', token)], limit=1)
        if not access or not access.is_valid():
            return request.render('planetio_todo.public_questionnaire_error')

        batch = access.batch_id.sudo()
        return request.render('planetio_todo.public_questionnaire_page', {
            'batch': batch,
            'token': token,
        })

    @http.route(['/planetio/questionario/salva'], type='http', auth='public', website=True, csrf=False)
    def save_questionnaire(self, **post):
        token = post.get('token')
        access = request.env['planetio.token.access'].sudo().search([('name', '=', token)], limit=1)
        
        if not access or not access.is_valid():
            return request.render('planetio_todo.public_questionnaire_error')

        batch = access.batch_id.sudo()

        # Unisce tutte le risposte da ogni sezione
        all_answers = (
            batch.questionnaire_answer_ids_section_1 +
            batch.questionnaire_answer_ids_section_2 +
            batch.questionnaire_answer_ids_section_3 +
            batch.questionnaire_answer_ids_section_4 +
            batch.questionnaire_answer_ids_section_5 +
            batch.questionnaire_answer_ids_section_6 +
            batch.questionnaire_answer_ids_section_7
        )

        for answer in all_answers:
            answer_id_str = str(answer.id)
            answer_val = post.get(f'answer_{answer_id_str}')
            info_val = post.get(f'info_{answer_id_str}')
            file_storage = request.httprequest.files.get(f'attachment_{answer_id_str}')

            values = {}

            if answer_val:
                values['answer'] = answer_val
            if info_val:
                values['additional_info'] = info_val
            if file_storage:
                values['attachment'] = base64.b64encode(file_storage.read()).decode()
                values['attachment_filename'] = secure_filename(file_storage.filename)

            if values:
                answer.write(values)

        # Convalida questionario come da logica Odoo
        batch.action_validate_questionnaire()

        # Disattivo il token per impedirne il riutilizzo
        access.active = False

        # Invio mail al compilatore, se presente
        if batch.questionnaire_compiler and batch.questionnaire_compiler.email:
            template = _(
                """<p>Gentle %s,<p>
                <p>The compilation of the EUDR question for coffee batch <strong>%s</strong> was received correctly.<p>
                <p>Thank you for your cooperation.<p>
                <br/>
                <p>--</p>
                <p>PLANETIO</p>"""
            ) % (batch.questionnaire_compiler.name, batch.protocol_number)

            request.env['mail.mail'].sudo().create({
                'subject': _('Confirmation of completion of EUDR questionnaire'),
                'body_html': f"{template}",
                'email_to': batch.questionnaire_compiler.email,
            }).send()

        return request.render('planetio_todo.public_questionnaire_success', {
            'protocol_number': batch.protocol_number
        })
    
    @http.route('/planetio/questionario/update_answer', type='json', auth='public', methods=['POST'], csrf=False)
    def update_answer(self):
        data = request.jsonrequest

        token = data.get('token')
        answer_id = data.get('answer_id')

        try:
            answer_id = int(answer_id)
        except (TypeError, ValueError):
            return {'error': 'Invalid answer_id type'}

        answer_value = data.get('answer_value')
        additional_info = data.get('additional_info')
        remove_attachment = data.get('remove_attachment', False)
        attachment = data.get('attachment')
        attachment_filename = data.get('attachment_filename')

        # Validazione token
        token_rec = request.env['planetio.token.access'].sudo().search([('name', '=', token), ('active', '=', True)], limit=1)
        if not token_rec or not token_rec.is_valid():
            return {'error': 'Invalid or expired token'}

        # Trova la risposta
        answer_rec = request.env['planetio.questionnaire.answer'].sudo().browse(answer_id)
        if not answer_rec.exists() or answer_rec.batch_id.id != token_rec.batch_id.id:
            return {'error': 'Invalid answer'}

        vals = {}

        # Aggiorna risposta sì/no
        if answer_value:
            vals['answer'] = answer_value

        # Aggiorna info aggiuntive
        if additional_info is not None:
            vals['additional_info'] = additional_info

        # Se JS manda remove_attachment: true → pulizia completa
        if remove_attachment:
            attachments = request.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'planetio.questionnaire.answer'),
                ('res_field', '=', 'attachment'),
                ('res_id', '=', answer_rec.id),
            ])
            if attachments:
                attachments.unlink()

            vals['attachment'] = False
            vals['attachment_filename'] = False

        # Se JS manda un nuovo attachment → salva l'allegato
        if attachment and attachment_filename:
            vals['attachment'] = attachment
            vals['attachment_filename'] = attachment_filename

        if vals:
            answer_rec.write(vals)

        return {'success': True}