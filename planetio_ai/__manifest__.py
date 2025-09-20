{
    'name': 'Planetio AI Bridge',
    'version': '14.0.1.0.0',
    'summary': 'Bridge tra Planetio e AI Gateway',
    'author': 'Roberto',
    'license': 'LGPL-3',
    'depends': ['ai_gateway', 'planetio', 'mail'],
    'data': [
        'data/ai_data_defaults.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/summarize_documents_wizard_views.xml',
        'report/ai_summary_report.xml',
    ],
    'installable': True,
}
