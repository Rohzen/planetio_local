from odoo import fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ai_prompt_deforestation_critical_issues = fields.Text(
        string="AI prompt: deforestation critical issues",
        help=_(
            "Istruzioni predefinite che guidano l'AI nell'evidenziare gli "
            "aspetti critici legati alla deforestazione durante l'analisi dei documenti."
        ),
    )

    ai_prompt_corrective_actions = fields.Text(
        string="AI prompt: corrective actions",
        help=_(
            "Istruzioni predefinite che guidano l'AI nel suggerire azioni "
            "correttive in base ai rischi rilevati."
        ),
    )

    def get_values(self):
        res = super().get_values()
        icp = self.env["ir.config_parameter"].sudo()
        res.update(
            {
                "ai_prompt_deforestation_critical_issues": icp.get_param(
                    "planetio_ai.prompt_deforestation_critical_issues", ""
                ),
                "ai_prompt_corrective_actions": icp.get_param(
                    "planetio_ai.prompt_corrective_actions", ""
                ),
            }
        )
        return res

    def set_values(self):
        super().set_values()
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param(
            "planetio_ai.prompt_deforestation_critical_issues",
            self.ai_prompt_deforestation_critical_issues or "",
        )
        icp.set_param(
            "planetio_ai.prompt_corrective_actions",
            self.ai_prompt_corrective_actions or "",
        )
