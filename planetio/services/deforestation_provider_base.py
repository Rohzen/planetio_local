from odoo import models

class DeforestationProviderBase(models.AbstractModel):
    _name = 'deforestation.provider.base'
    _description = 'Base provider interface'

    # deve lanciare UserError con messaggi parlanti se manca configurazione
    def check_prerequisites(self):
        raise NotImplementedError()

    # deve restituire: {'message': str, 'flag': bool|None, 'score': float|None, 'raw': dict}
    def analyze_line(self, line):
        raise NotImplementedError()
