{
    'name': 'Planetio',
    'version': '14.0.1.0.0',
    'author': 'Alessandro Vasi / Roberto Zanardo / Encodata S.r.l.',
    'summary': 'Modulo per la compilazione della due-diligence sulla normativa della deforestazione',
    'depends': ['base', 'mail', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/eudr_views.xml',
        # 'views/job_views.xml',
        'views/template_views.xml',
        'views/wizard_views.xml',
        'views/res_config_settings_view.xml',
        'data/eudr_stages.xml',
        'data/eudr_params.xml',
        'data/seed_template.xml',
        'data/sequence.xml',
    ],
    'external_dependencies': {
        'python' : ['pandas', 'requests', 'google-generativeai', 'pyproj', 'shapely'],
    },
    'installable': True,
    'application': True,
}

