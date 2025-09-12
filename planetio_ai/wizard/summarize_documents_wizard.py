from odoo import api, fields, models

class PlanetioSummarizeWizard(models.Model):
    _inherit = 'eudr.declaration'

    def action_ai_analyze(self):
        for doc in self.attachment_ids:
            # Analyze documents via AI-gateway module
            pass
