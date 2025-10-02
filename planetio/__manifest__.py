{
    'name': 'Planetio',
    'version': '14.0.1.0.6',
    'author': 'Alessandro Vasi / Roberto Zanardo / Encodata S.r.l.',
    'summary': 'Modulo per la compilazione della due-diligence sulla normativa della deforestazione',
    'depends': ['base', 'mail', 'web', 'coffee_species'],
    'data': [
        'security/ir.model.access.csv',
        'views/eudr_views.xml',
        'views/template_views.xml',
        'wizards/import_wizard.xml',
        'wizards/deforestation_geometry_wizard.xml',
        'views/res_config_settings_view.xml',
        'data/eudr_stages.xml',
        'data/seed_template.xml',
        'data/sequence.xml',
        'report/eudr_declaration_report.xml',
        "views/res_company_views.xml",
    ],
    'external_dependencies': {
        'python' : ['pandas', 'requests', 'google-generativeai', 'pyproj', 'shapely'],
    },
    'installable': True,
    'application': True,
}

