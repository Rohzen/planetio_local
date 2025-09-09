from odoo import fields, models, api, _

class PlanetioQuestion(models.Model):
    _name = "planetio.question"
    _description = "Questions EUDR questionnaire"

    name = fields.Char(string="Question", required=True, translate=True)
    score = fields.Integer(string="Score", required=True, default=5)
    weight = fields.Selection(
        [("1", "Low"), ("2", "Medium"), ("3", "High")],
        string="Weight",
        required=True,
        default="2"
    )
    section = fields.Selection(
        [
            ("1", "GENERAL INFORMATION ABOUT THE SUPPLIER"),
            ("2", "TRACEABILITY AND GEOLOCATION"),
            ("3", "EUDR COMPLIANCE AND LOCAL LEGISLATION"),
            ("4", "SUPPLY CHAIN AND INTERMEDIARIES"),
            ("5", "CERTIFICATIONS AND SUSTAINABILITY"),
            ("6", "RESPECT FOR INDIGENOUS PEOPLES' RIGHTS"),
            ("7", "RISK MANAGEMENT AND DOCUMENTATION"),
        ],
        string="Section",
        required=True
    )