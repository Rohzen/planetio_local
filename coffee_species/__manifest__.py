# -*- coding: utf-8 -*-
{
    "name": "Coffee Species",
    "version": "14.0.1.0.1",
    "summary": "Catalog of coffee species with common and scientific names",
    "category": "Productivity",
    "author": "Roberto + AI",
    "license": "LGPL-3",
    "depends": ["base", "product"],
    "data": [
        "security/ir.model.access.csv",
        "views/coffee_species_views.xml",
        "data/coffee_species_data.xml",
    ],
    "installable": True,
    "application": False
}
