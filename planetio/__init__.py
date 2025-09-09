from . import models, controllers
from odoo import api, SUPERUSER_ID

def populate_questions(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    question_model = env["planetio.question"]
    
    questions = [
        # Section 1: GENERAL INFORMATION ABOUT THE SUPPLIER (3 questions)
        {"name": "Is your company registered and legally recognized in the country of origin?", "score": 5, "section": "1"},
        {"name": "Does your company have an EORI (Economic Operators Registration and Identification) code?", "score": 3, "section": "1"},
        {"name": "Does your company have previous experience in exporting raw materials to the EU?", "score": 3, "section": "1"},
        
        # Section 2: TRACEABILITY AND GEOLOCATION (4 questions)
        {"name": "Can you provide precise geolocation (GPS coordinates) of the plots producing the raw material?", "score": 5, "section": "2"},
        {"name": "Does the supplied raw material come exclusively from registered and traceable plots?", "score": 5, "section": "2"},
        {"name": "Do you have a documented system to ensure full traceability of the supply chain?", "score": 4, "section": "2"},
        {"name": "Can you provide a GeoJSON file or another accepted format for geolocating production areas?", "score": 4, "section": "2"},
        
        # Section 3: EUDR COMPLIANCE AND LOCAL LEGISLATION (3 questions)
        {"name": "Does your company guarantee that the supplied raw material does not come from deforested land after December 31, 2020?", "score": 4, "section": "3"},
        {"name": "Was the raw material produced in compliance with the national laws of the country of origin?", "score": 4, "section": "3"},
        {"name": "Is your company able to provide official documentation to demonstrate compliance with EUDR requirements?", "score": 4, "section": "3"},
        
        # Section 4: SUPPLY CHAIN AND INTERMEDIARIES (3 questions)
        {"name": "Does the supplied raw material come exclusively from direct producers and not from intermediaries?", "score": 3, "section": "4"},
        {"name": "If the raw material passes through intermediaries, can you guarantee that each step of the supply chain is traceable?", "score": 3, "section": "4"},
        {"name": "Do the involved intermediaries comply with the same traceability and compliance standards required by EUDR?", "score": 3, "section": "4"},
        
        # Section 5: CERTIFICATIONS AND SUSTAINABILITY (3 questions)
        {"name": "Does your company hold recognized sustainability certifications (e.g., Rainforest Alliance, UTZ, Fairtrade, FSC, PEFC)?", "score": 4, "section": "5"},
        {"name": "Is your company willing to undergo independent audits or third-party inspections to verify EUDR compliance?", "score": 4, "section": "5"},
        {"name": "Have policies been adopted to ensure the protection of workers' rights and local communities involved in production?", "score": 3, "section": "5"},
        
        # Section 6: RESPECT FOR INDIGENOUS PEOPLES' RIGHTS (5 questions)
        {"name": "Is the raw material produced on land traditionally occupied or used by indigenous communities?", "score": 4, "section": "6"},
        {"name": "If yes, have formal agreements been established with indigenous communities for the use of these lands?", "score": 3, "section": "6"},
        {"name": "Do these agreements fully respect the rights of indigenous communities as established by local and international legislation?", "score": 5, "section": "6"},
        {"name": "Has your company implemented measures to ensure the free, prior, and informed consent of indigenous communities involved?", "score": 5, "section": "6"},
        {"name": "Are there procedures in place to monitor and resolve potential conflicts with indigenous communities regarding land use?", "score": 4, "section": "6"},
        
        # Section 7: RISK MANAGEMENT AND DOCUMENTATION (4 questions)
        {"name": "Does your company have an internal protocol to assess the risk of deforestation and forest degradation?", "score": 4, "section": "7"},
        {"name": "If yes, can you provide documentation or internal reports in support?", "score": 4, "section": "7"},
        {"name": "Has your company ever received reports of non-compliance related to deforestation or forest degradation?", "score": 4, "section": "7"},
        {"name": "If yes, have corrective measures been documented and implemented?", "score": 4, "section": "7"},
    ]
    
    for question in questions:
        if not question_model.search([("name", "=", question["name"])], limit=1):
            question_model.create(question)
