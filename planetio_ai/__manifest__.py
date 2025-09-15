{
    'name': 'Planetio AI Bridge',
    'version': '14.0.1.0.0',
    'summary': 'Bridge tra Planetio e AI Gateway',
    'author': 'Roberto',
    'license': 'LGPL-3',
    'depends': ['ai_gateway', 'planetio', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/summarize_documents_wizard_views.xml',
    ],
    'installable': True,
}
