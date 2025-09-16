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
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
