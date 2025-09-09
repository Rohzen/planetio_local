{
    'name' : 'AI Copilot – Prompt > Domain',
    'version' : '14.0.1.0.0',
    'summary' : """
    Chat/Wizard per query conversazionali sicure che generano domini Odoo""",
    'author' : 'Roberto Zanardo',
    'company' : 'Encodata S.r.l.',
    'website' : 'https://www.encodata.com',
    'category' : 'Tools',
    'license' : 'AGPL-3',
    'installable' : True,
    'application' : False,
    'depends' : [
        'base',
        'account',
        'mrp',
        'stock'
    ],
    'data' : [
        'security/ir.model.access.csv',
        'views/ai_chat_views.xml'
    ],
    'demo' : [
    ],
}