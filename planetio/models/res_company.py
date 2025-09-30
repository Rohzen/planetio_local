from odoo import api, fields, models, _

class ResCompany(models.Model):
    _inherit = "res.company"

    eudr_company_type = fields.Selection(
        selection=[
            ("operator", "Operator"),
            ("trader", "Trader"),
            ("mixed", "Mixed"),
            ("third_party_trader", "Third Party Trader"),
        ],
        string="EUDR Company Type",
        help=(
            "Classification used by PLANETIO/TRACES for DDS submission:\n"
            "- Operator: places products on the EU market for the first time or exports them\n"
            "- Trader: buys/sells products already placed on the EU market (SME/non-SME)\n"
            "- Mixed: may act either as operator or trader depending on the case\n"
            "- Third Party Trader: submits on behalf of another party, with mandate and EU establishment"
        ),
        default="operator",
    )

    # Opzionali ma utili per le prossime regole
    eudr_is_sme = fields.Boolean(
        string="Trader is SME",
        help="Relevant only if the company operates as Trader / Mixed (in Trader mode)."
    )
    eudr_third_party_has_mandate = fields.Boolean(
        string="Third Party: Signed mandate",
    )
    eudr_third_party_established_in_eu = fields.Boolean(
        string="Third Party: Established in the EU",
    )
