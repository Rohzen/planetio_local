{
    'name': 'Planetio AI Bridge',
    'version': '14.0.1.0.0',
    'summary': 'Bridge tra Planetio e AI Gateway',
    'author': 'Roberto',
    'license': 'LGPL-3',
<<<<<<< HEAD
    'depends': ['ai_gateway', 'planetio', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/summarize_documents_wizard_views.xml',
        'report/ai_summary_report.xml',
=======
    'depends': ['ai_gateway', 'planetio', 'mail','web_progress'],
    'data': [
        'data/ai_data_defaults.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/summarize_documents_wizard_views.xml',
        'report/ai_summary_report.xml',
        'report/eudr_declaration_ai_report.xml',
>>>>>>> 823bb1258a0473c1135fe37802bcf0567c9472f2
    ],
    'installable': True,
}
