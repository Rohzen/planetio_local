{
    'name': 'AI Gateway',
    'version': '14.0.1.0.0',
    'summary': 'Gateway unificato per servizi AI (Gemini default)',
    'author': 'Roberto Zanardo',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/ai_request_views.xml',
    ],
    'installable': True,
}
