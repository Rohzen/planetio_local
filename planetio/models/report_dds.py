from odoo import models
import io
import base64
import logging

from PyPDF2 import PdfFileMerger

_logger = logging.getLogger(__name__)

class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, res_ids=None, data=None):
        pdf_content, content_type = super()._render_qweb_pdf(res_ids=res_ids, data=data)

        # ATTENZIONE: interveniamo solo se è il report DDS nostro
        if self.report_name != 'planetio_todo.report_dds_template':
            return pdf_content, content_type

        merger = PdfFileMerger()
        try:
            merger.append(io.BytesIO(pdf_content), import_bookmarks=False)
        except Exception as e:
            _logger.warning(f"Errore durante l'append del PDF principale: {e}")

        docs = self.env[self.model].browse(res_ids)

        for doc in docs:
            all_answers = (
                doc.questionnaire_answer_ids_section_1 +
                doc.questionnaire_answer_ids_section_2 +
                doc.questionnaire_answer_ids_section_3 +
                doc.questionnaire_answer_ids_section_4 +
                doc.questionnaire_answer_ids_section_5 +
                doc.questionnaire_answer_ids_section_6 +
                doc.questionnaire_answer_ids_section_7
            )
            for answer in all_answers:
                if answer.attachment and answer.attachment_filename and answer.attachment_filename.endswith('.pdf'):
                    try:
                        pdf_data = base64.b64decode(answer.attachment)
                        try:
                            merger.append(io.BytesIO(pdf_data), import_bookmarks=False)
                        except Exception as e:
                            _logger.warning(f"Errore durante l'append del PDF principale: {e}")
                    except Exception as e:
                        _logger.warning(f"Failed to attach PDF from answer {answer.id}: {str(e)}")
                        continue

        output_stream = io.BytesIO()
        merger.write(output_stream)
        merger.close()

        return (output_stream.getvalue(), 'pdf')