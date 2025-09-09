from odoo import models, fields
import uuid

class PlanetioTokenAccess(models.Model):
    _name = 'planetio.token.access'
    _description = 'Public access to the Planetio questionnaire'

    name = fields.Char(string='Token', default=lambda self: str(uuid.uuid4()), readonly=True)
    batch_id = fields.Many2one('caffe.crudo.todo.batch', required=True)
    active = fields.Boolean(default=True)
    expiration_date = fields.Date()

    def is_valid(self):
        return self.active and (not self.expiration_date or self.expiration_date >= fields.Date.today())
