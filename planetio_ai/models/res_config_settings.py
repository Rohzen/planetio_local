from odoo import fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ai_prompt_deforestation_critical_issues = fields.Text(
        string="AI prompt: deforestation critical issues",
        config_parameter="planetio_ai.prompt_deforestation_critical_issues",
        help=_(
            "Istruzioni predefinite che guidano l'AI nell'evidenziare gli "
            "aspetti critici legati alla deforestazione durante l'analisi dei documenti."
        ),
    )

    ai_prompt_corrective_actions = fields.Text(
        string="AI prompt: corrective actions",
        config_parameter="planetio_ai.prompt_corrective_actions",
        help=_(
            "Istruzioni predefinite che guidano l'AI nel suggerire azioni "
            "correttive in base ai rischi rilevati."
        ),
    )
