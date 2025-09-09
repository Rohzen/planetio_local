
{
    "name": "Planetio",
    "version": "14.0.1.0.0",
    'author': "Alessandro Vasi / Roberto Zanardo / Encodata S.r.l.",
    'summary': 'Modulo per la compilazione della due-diligence sulla normativa della deforestazione',
    'depends': [
        'base',
        'mail',
        'web'
        ],
    "data": [
        "security/ir.model.access.csv",
        "views/eudr_views.xml",
        "views/eudr_views_inh.xml",
        "views/template_views.xml",
        "views/wizard_views.xml",
        'views/planetio_question_views.xml',
        'views/public_questionnaire_template.xml',
        'views/public_questionnaire_success.xml',
        'views/public_questionnaire_error.xml',
        'views/res_config_settings_inh.xml',
        'views/otp_verification_wizard.xml',
        'views/job_views.xml',
        'reports/report_dds.xml',
        'reports/report_dds_template.xml',
        'data/planetio_eudr_params.xml',
    ],
    "installable": True,
    "application": True,
}
