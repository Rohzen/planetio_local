from odoo import models, fields

class PlanetioAttachment(models.Model):
    _name = 'planetio.attachment'
    _description = 'Allegati multipli alla DDS Planetio'

    name = fields.Char("Nome")
    file = fields.Binary("File", required=True)
    batch_id = fields.Integer()  # fields.Many2one('caffe.crudo.todo.batch', required=True)
    # batch_id = fields.Many2one("caffe.crudo.todo.batch", string="Batch collegato", required=True, ondelete='cascade')
