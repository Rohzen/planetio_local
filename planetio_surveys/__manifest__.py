{
    'name': 'Planetio Surveys',
    'version': '14.0.1.0.0',
    'summary': 'Link EUDR declarations with Odoo surveys.',
    'category': 'Tools',
    'depends': ['planetio', 'survey'],
    'data': [
        'views/eudr_declaration_views.xml',
        'views/survey_user_input_views.xml',
        'data/survey_data.xml',
<<<<<<< HEAD
=======
        'views/res_partner_view.xml',
        'views/res_config_settings_view.xml',
>>>>>>> 823bb1258a0473c1135fe37802bcf0567c9472f2
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
