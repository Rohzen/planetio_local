# -*- coding: utf-8 -*-
{
    "name": "HS Codes",
    "version": "14.0.1.1.0",
    "summary": "Catalog of HS codes with associated species information",
    "category": "Productivity",
    "author": "Roberto + AI",
    "license": "LGPL-3",
    "depends": ["base", "sale", "product"],
    "data": [
        "security/ir.model.access.csv",
        "views/hs_code_views.xml",
        "data/hs_code_data.xml",
    ],
    "installable": True,
    "application": False
}
