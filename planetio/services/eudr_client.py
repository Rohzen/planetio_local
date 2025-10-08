# -*- coding: utf-8 -*-
"""
Pure EUDR SOAP client (framework-agnostic).
- WS-Security UsernameToken (PasswordDigest/Text)
- SubmitStatementRequest XML with correct element order
- SOAP 1.1 POST via requests
- ddsIdentifier + Business Fault parsing
"""
import base64, hashlib, json, secrets
from datetime import datetime, timedelta, timezone
import requests
import xml.etree.ElementTree as ET

def build_geojson_b64(geojson_dict) -> str:
    if not isinstance(geojson_dict, dict):
        raise ValueError("geojson_dict must be a dict")
    return base64.b64encode(json.dumps(geojson_dict, separators=(",", ":")).encode("utf-8")).decode("ascii")

class EUDRClient:
    def __init__(self, endpoint: str, username: str, apikey: str, wsse_mode: str = "digest",
                 webservice_client_id: str = "eudr-test", timeout: int = 60, session: requests.Session = None):
        self.endpoint = endpoint.rstrip()
        self.username = username
        self.apikey = apikey
        self.wsse_mode = (wsse_mode or "digest").lower()
        self.webservice_client_id = webservice_client_id
        self.timeout = timeout
        self.session = session or requests.Session()

    # --- WS-Security UsernameToken ---
    def _build_wsse_header(self) -> str:
        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        expires = (datetime.now(timezone.utc) + timedelta(seconds=55)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        nonce_bytes = secrets.token_bytes(16)
        nonce_b64 = base64.b64encode(nonce_bytes).decode("ascii")

        if self.wsse_mode == "text":
            pwd_value = self.apikey
            pwd_type = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText"
        else:
            sha1 = hashlib.sha1()
            # PasswordDigest = Base64( SHA1( nonce + created + password ) )
            sha1.update(nonce_bytes + created.encode("utf-8") + self.apikey.encode("utf-8"))
            pwd_value = base64.b64encode(sha1.digest()).decode("ascii")
            pwd_type = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"

        return (
            '<wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
            'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">'
            '<wsu:Timestamp wsu:Id="TS-1">'
            f'<wsu:Created>{created}</wsu:Created>'
            f'<wsu:Expires>{expires}</wsu:Expires>'
            '</wsu:Timestamp>'
            '<wsse:UsernameToken wsu:Id="UsernameToken-1">'
            f'<wsse:Username>{self.username}</wsse:Username>'
            f'<wsse:Password Type="{pwd_type}">{pwd_value}</wsse:Password>'
            '<wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">'
            f'{nonce_b64}</wsse:Nonce>'
            f'<wsu:Created>{created}</wsu:Created>'
            '</wsse:UsernameToken>'
            '</wsse:Security>'
        )


    # --- Build SubmitStatementRequest (order validated) ---
    def build_statement_xml(self, *, internal_ref: str, activity_type: str, company_name: str,
                            company_country: str, company_address: str, eori_value: str,
                            hs_heading: str, description_of_goods: str, net_weight_kg: str,
                            producer_country: str, producer_name: str, geojson_b64: str,
                            operator_type: str = "OPERATOR",
                            country_of_activity: str, border_cross_country: str, comment: str,
                            scientific_name: str = None, common_name: str = None, species_list: list = None) -> str:
        if not geojson_b64:
            raise ValueError("geojson_b64 is required")

        # Prima parte fino a hsHeading
        xml = (
            '<eudr:SubmitStatementRequest '
            'xmlns:eudr="http://ec.europa.eu/tracesnt/certificate/eudr/submission/v1" '
            'xmlns:model="http://ec.europa.eu/tracesnt/certificate/eudr/model/v1" '
            'xmlns:base="http://ec.europa.eu/sanco/tracesnt/base/v4">'
            f'<eudr:operatorType>{operator_type}</eudr:operatorType>'
            '<eudr:statement>'
            f'<model:internalReferenceNumber>{internal_ref}</model:internalReferenceNumber>'
            f'<model:activityType>{activity_type}</model:activityType>'
            '<model:operator>'
            '<model:referenceNumber>'
            '<model:identifierType>eori</model:identifierType>'
            f'<model:identifierValue>{eori_value}</model:identifierValue>'
            '</model:referenceNumber>'
            '<model:nameAndAddress>'
            f'<base:name>{company_name}</base:name>'
            f'<base:country>{company_country}</base:country>'
            f'<base:address>{company_address}</base:address>'
            '</model:nameAndAddress>'
            '</model:operator>'
            f'<model:countryOfActivity>{country_of_activity}</model:countryOfActivity>'
            f'<model:borderCrossCountry>{border_cross_country}</model:borderCrossCountry>'
            f'<model:comment>{comment}</model:comment>'
            '<model:commodities>'
            '<model:position>1</model:position>'
            '<model:descriptors>'
            f'<model:descriptionOfGoods>{description_of_goods}</model:descriptionOfGoods>'
            '<model:goodsMeasure>'
            f'<model:netWeight>{net_weight_kg}</model:netWeight>'
            '</model:goodsMeasure>'
            '</model:descriptors>'
            f'<model:hsHeading>{hs_heading}</model:hsHeading>'
        )

        # --- SPECIES (no <model:species> wrapper) ---
        species_list = species_list or []
        if species_list:
            xml += '<model:speciesList>'
            for sp in species_list:
                sci = (sp.get('scientificName') or '').strip() if isinstance(sp, dict) else ''
                com = (sp.get('commonName') or '').strip() if isinstance(sp, dict) else ''
                if not sci and not com:
                    continue
                xml += '<model:species>'
                if sci:
                    xml += f'<model:scientificName>{sci}</model:scientificName>'
                if com:
                    xml += f'<model:commonName>{com}</model:commonName>'
                xml += '</model:species>'
            xml += '</model:speciesList>'
        elif scientific_name or common_name:
            xml += '<model:speciesInfo>'
            if scientific_name:
                xml += f'<model:scientificName>{scientific_name}</model:scientificName>'
            if common_name:
                xml += f'<model:commonName>{common_name}</model:commonName>'
            xml += '</model:speciesInfo>'

        # Chiusura con producers e resto
        xml += (
            '<model:producers>'
            '<model:position>1</model:position>'
            f'<model:country>{producer_country}</model:country>'
            f'<model:name>{producer_name}</model:name>'
            f'<model:geometryGeojson>{geojson_b64}</model:geometryGeojson>'
            '</model:producers>'
            '</model:commodities>'
            '<model:geoLocationConfidential>false</model:geoLocationConfidential>'
            '</eudr:statement>'
            '</eudr:SubmitStatementRequest>'
        )

        return xml

    def build_envelope(self, submit_request_xml: str) -> str:
        wsse_header = self._build_wsse_header()
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:base="http://ec.europa.eu/sanco/tracesnt/base/v4">'
            '<soapenv:Header>'
            f'{wsse_header}'
            f'<base:WebServiceClientId>{self.webservice_client_id}</base:WebServiceClientId>'
            '</soapenv:Header>'
            '<soapenv:Body>'
            f'{submit_request_xml}'
            '</soapenv:Body>'
            '</soapenv:Envelope>'
        )

    def submit(self, envelope_xml: str) -> (int, str):
        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "SOAPAction": "http://ec.europa.eu/tracesnt/certificate/eudr/submission/submitDds",
            "Accept": "text/xml",
        }
        resp = self.session.post(self.endpoint, data=envelope_xml.encode("utf-8"), headers=headers, timeout=self.timeout)
        return resp.status_code, resp.text

    @staticmethod
    def parse_dds_identifier(response_text: str) -> str:
        try:
            root = ET.fromstring(response_text)
            ns = {"S": "http://schemas.xmlsoap.org/soap/envelope/", "subm": "http://ec.europa.eu/tracesnt/certificate/eudr/submission/v1"}
            el = root.find(".//subm:ddsIdentifier", ns)
            return el.text.strip() if el is not None and el.text else None
        except Exception:
            return None

    @staticmethod
    def parse_reference_number(response_text: str) -> str:
        """
        Estrae il TRACES reference number dalla SubmitStatementResponse:
        //eudr:referenceNumber (namespace submission v1).
        Ritorna None se non presente.
        """
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response_text)
            ns = {
                "S": "http://schemas.xmlsoap.org/soap/envelope/",
                "eudr": "http://ec.europa.eu/tracesnt/certificate/eudr/submission/v1",
            }
            el = root.find(".//eudr:referenceNumber", ns)
            if el is not None and el.text and el.text.strip():
                return el.text.strip()

            # Fallback: qualunque elemento con local-name 'referenceNumber'
            for e in root.iter():
                if e.tag.rsplit('}', 1)[-1] == "referenceNumber" and e.text:
                    return e.text.strip()
        except Exception:
            pass
        return None

    @staticmethod
    def parse_ws_request_id(response_text: str) -> str:
        try:
            root = ET.fromstring(response_text)
            for el in root.iter():
                tag = el.tag.split('}', 1)[-1]
                if tag == "Message" and el.text and len(el.text.strip()) >= 8:
                    return el.text.strip()
        except Exception:
            pass
        return None

    @staticmethod
    def parse_business_errors(response_text: str):
        """Return (ws_request_id, [ {code, message, path}... ]) if present. Very robust to namespaces/variants."""
        import xml.etree.ElementTree as ET

        def L(tag):
            return tag.split('}', 1)[-1] if isinstance(tag, str) else tag

        try:
            root = ET.fromstring(response_text)
        except Exception:
            return (None, [])

        # Reuse existing helper for GUID
        wsid = EUDRClient.parse_ws_request_id(response_text)
        errors = []

        # 1) Restrict search to <detail> if presente (di solito gli errori stanno lì)
        detail_nodes = [n for n in root.iter() if L(n.tag) == "detail"]
        scan_roots = detail_nodes or [root]

        # 2) Cattura elementi che *possono* rappresentare un errore
        ERR_TAGS = {"error", "violation", "validationError", "constraintViolation", "ruleViolation", "entry"}
        CODE_KEYS = {"code", "errorCode"}
        MSG_KEYS = {"message", "msg", "description", "reason", "text"}
        PATH_KEYS = {"path", "xpath", "location", "field", "pointer"}

        def collect_from(node):
            for el in node.iter():
                name = L(el.tag)
                if name in ERR_TAGS:
                    err = {"code": None, "message": None, "path": None}

                    # a) prova da attributi
                    for k, v in el.attrib.items():
                        lk = L(k)
                        if lk in CODE_KEYS and not err["code"]:
                            err["code"] = (v or "").strip()
                        elif lk in MSG_KEYS and not err["message"]:
                            err["message"] = (v or "").strip()
                        elif lk in PATH_KEYS and not err["path"]:
                            err["path"] = (v or "").strip()

                    # b) prova da figli
                    for ch in el:
                        cname = L(ch.tag)
                        if cname in CODE_KEYS and not err["code"]:
                            err["code"] = (ch.text or "").strip()
                        elif cname in MSG_KEYS and not err["message"]:
                            err["message"] = (ch.text or "").strip()
                        elif cname in PATH_KEYS and not err["path"]:
                            err["path"] = (ch.text or "").strip()

                    if err["code"] or err["message"] or err["path"]:
                        errors.append(err)

        for sr in scan_roots:
            collect_from(sr)

        # 3) Fallback extra: coppie <code>/<message> sparse
        if not errors:
            codes = []
            msgs = []
            paths = []
            for el in root.iter():
                n = L(el.tag)
                if n in CODE_KEYS and el.text:
                    codes.append(el.text.strip())
                elif n in MSG_KEYS and el.text:
                    msgs.append(el.text.strip())
                elif n in PATH_KEYS and el.text:
                    paths.append(el.text.strip())
            # allinea lunghezze senza rompere
            m = max(len(codes), len(msgs), len(paths))
            for i in range(m):
                errors.append({
                    "code": codes[i] if i < len(codes) else None,
                    "message": msgs[i] if i < len(msgs) else None,
                    "path": paths[i] if i < len(paths) else None,
                })

        return (wsid, errors)
