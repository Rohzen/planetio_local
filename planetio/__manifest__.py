{
    'name': 'Planetio Todo',
    'version': '14.0.8.18.0',
    'category': 'Custom',
    'author': "Alessandro Vasi / Encodata S.r.l.",
    'summary': 'Modulo per la compilazione della due-diligence sulla normativa della deforestazione',
    'depends': [
        'base', 
        'mail',
        'caffe_crudo_todo',
        'web'
        ],
    'data': [
        "security/ir.model.access.csv",
        'views/caffe_crudo_todo_views_inh.xml',
        'views/planetio_question_views.xml',
        'views/public_questionnaire_template.xml',
        'views/public_questionnaire_success.xml',
        'views/public_questionnaire_error.xml',
        'views/res_config_settings_inh.xml',
        'views/otp_verification_wizard.xml',
        'reports/report_dds.xml',
        'reports/report_dds_template.xml',
        'data/planetio_eudr_params.xml',
    ],
    'post_init_hook': 'populate_questions',
    'installable': True,
    'application': False,
}