{
    'name': 'Planetio',
<<<<<<< HEAD
    'version': '14.0.1.0.0',
    'author': 'Alessandro Vasi / Roberto Zanardo / Encodata S.r.l.',
    'summary': 'Modulo per la compilazione della due-diligence sulla normativa della deforestazione',
    'depends': ['base', 'mail', 'web', 'coffee_species'],
=======
    'version': '14.0.1.0.6',
    'author': 'Alessandro Vasi / Roberto Zanardo / Encodata S.r.l.',
    'summary': 'Modulo per la compilazione della due-diligence sulla normativa della deforestazione',
    'depends': ['base', 'mail', 'web', 'coffee_species', 'web_progress'],
>>>>>>> 823bb1258a0473c1135fe37802bcf0567c9472f2
    'data': [
        'security/ir.model.access.csv',
        'views/eudr_views.xml',
        'views/template_views.xml',
        'wizards/import_wizard.xml',
<<<<<<< HEAD
=======
        'wizards/deforestation_geometry_wizard.xml',
>>>>>>> 823bb1258a0473c1135fe37802bcf0567c9472f2
        'views/res_config_settings_view.xml',
        'data/eudr_stages.xml',
        'data/seed_template.xml',
        'data/sequence.xml',
<<<<<<< HEAD
    ],
=======
        'report/eudr_declaration_report.xml',
        "views/res_company_views.xml",
    ],
    'assets': {
        'web.assets_backend': [
        ],
    },
>>>>>>> 823bb1258a0473c1135fe37802bcf0567c9472f2
    'external_dependencies': {
        'python' : ['pandas', 'requests', 'google-generativeai', 'pyproj', 'shapely'],
    },
    'installable': True,
    'application': True,
}

