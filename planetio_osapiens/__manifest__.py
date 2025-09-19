# -*- coding: utf-8 -*-
{
    "name": "Planetio oSapiens Integration",
    "summary": "Integrazione EUDR con oSapiens: RFI, plot, lot, DDS, documenti",
    "version": "14.0.1.0.0",
    "author": "Planetio",
    "license": "LGPL-3",
    "website": "https://planetio.example",
    "depends": ["base", "purchase", "planetio"],
    "data": [
        "views/res_config_settings_views.xml",
        "views/purchase_order_views.xml",
        "views/eudr_declaration_actions.xml",
    ],
    "application": False,
    "installable": True,
}