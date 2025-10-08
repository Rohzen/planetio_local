# -*- coding: utf-8 -*-
"""
EUDR Retrieval Client
- Estende EUDRClient aggiungendo le chiamate al servizio di Retrieval (EUDRRetrievalServiceV1)
- Consente di verificare l'esistenza di una DDS e ottenere referenceNumber / verificationNumber
"""
from typing import List, Dict, Optional, Union
import xml.etree.ElementTree as ET

from .eudr_client import EUDRClient  # riusa WSSE, session, envelope base


class EUDRRetrievalClient(EUDRClient):
    """
    Estensione di EUDRClient per il servizio di Retrieval.
    Nota: in Acceptance/Prod il servizio di Retrieval ha endpoint distinto dal Submit.
    Usa quindi un endpoint specifico quando istanzi questa classe.
    """

    # SOAPAction del metodo retrieveDdsNumber
    RETR_SOAP_ACTION = "http://ec.europa.eu/tracesnt/certificate/eudr/retrieval/retrieveDdsNumber"

    DEFAULT_ROOT_TAG = "retrieveDdsNumberRequest"

    def __init__(
        self,
        endpoint: str,
        username: str,
        apikey: str,
        wsse_mode: str = "digest",
        webservice_client_id: str = "eudr-test",
        timeout: int = 60,
        session=None,
        retrieval_root_tag: Optional[str] = None,
    ):
        super().__init__(
            endpoint,
            username,
            apikey,
            wsse_mode=wsse_mode,
            webservice_client_id=webservice_client_id,
            timeout=timeout,
            session=session,
        )
        self.retrieval_root_tag = self._sanitize_root_tag(retrieval_root_tag)

    @classmethod
    def _sanitize_root_tag(cls, value: Optional[str]) -> str:
        tag = (value or "").strip()
        if not tag:
            return cls.DEFAULT_ROOT_TAG

        # Rimuove eventuali prefissi namespace come "retr:" oppure colon sparsi.
        if ":" in tag:
            tag = tag.split(":", 1)[-1]

        # Mantiene solo caratteri ammessi in un QName semplice (lettere, numeri, underscore)
        cleaned = "".join(ch for ch in tag if ch.isalnum() or ch == "_")
        if not cleaned or not cleaned[0].isalpha():
            return cls.DEFAULT_ROOT_TAG

        return cleaned

    def build_retrieval_xml(self, uuids: Union[str, List[str]]) -> str:
        """
        Costruisce il body XML (senza envelope) per RetrieveDdsNumberRequest.
        Accetta uno o più UUID (ddsIdentifier).
        """
        if isinstance(uuids, str):
            uuids = [uuids]
        uuids = [u.strip() for u in uuids if (u or "").strip()]
        if not uuids:
            raise ValueError("At least one DDS UUID is required")

        # Alcuni ambienti (es. Acceptance) validano l'XML rispetto allo schema e
        # richiedono che l'elemento radice sia "retrieveDdsNumberRequest" oppure
        # "RetrieveDdsNumberRequest" (la validazione cambia tra ambienti). Il
        # tag può quindi essere configurato via parametro Odoo, mentre questo
        # client applica un valore di fallback compatibile.
        root_tag = self.retrieval_root_tag or self.DEFAULT_ROOT_TAG

        return (
            f'<retr:{root_tag} '
            'xmlns:retr="http://ec.europa.eu/tracesnt/certificate/eudr/retrieval/v1" '
            'xmlns:base="http://ec.europa.eu/sanco/tracesnt/base/v4">'
            '<retr:uuids>'
            + "".join(f"<retr:uuid>{u}</retr:uuid>" for u in uuids) +
            '</retr:uuids>'
            f'</retr:{root_tag}>'
        )

    def build_retrieval_envelope(self, retrieval_xml: str) -> str:
        """
        Costruisce l'envelope SOAP 1.1 con WSSE e WebServiceClientId.
        """
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
            f'{retrieval_xml}'
            '</soapenv:Body>'
            '</soapenv:Envelope>'
        )

    def retrieve_dds(self, uuids: Union[str, List[str]]) -> (int, str):
        """
        Esegue la chiamata SOAP retrieveDdsNumber.
        Ritorna (status_code, response_text).
        """
        env_xml = self.build_retrieval_envelope(self.build_retrieval_xml(uuids))
        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "SOAPAction": self.RETR_SOAP_ACTION,
            "Accept": "text/xml",
        }
        resp = self.session.post(
            self.endpoint,
            data=env_xml.encode("utf-8"),
            headers=headers,
            timeout=self.timeout,
        )
        return resp.status_code, resp.text

    @staticmethod
    def parse_ws_request_id(response_text: str) -> Optional[str]:
        """
        Estrae l'eventuale WS_REQUEST_ID dall'header SOAP.
        """
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
    def parse_retrieval_result(response_text: str) -> List[Dict[str, Optional[str]]]:
        """
        Estrae una lista di record con chiavi: uuid, status, referenceNumber,
        verificationNumber, internalReferenceNumber, date, updatedBy.
        È tollerante a leggere local-name diversi (acceptance/prod possono
        variare).
        """
        try:
            root = ET.fromstring(response_text)
        except Exception:
            return []

        def L(tag: str) -> str:
            return tag.split('}', 1)[-1] if isinstance(tag, str) else tag

        out: List[Dict[str, Optional[str]]] = []

        # Cerca blocchi che rappresentano una DDS nella risposta (i nomi possono variare)
        candidate_blocks = []
        for node in root.iter():
            if L(node.tag) in {"dds", "ddsInfo", "ddsEntry", "ddsNumbers", "entry"}:
                candidate_blocks.append(node)

        # Se non troviamo blocchi principali, proviamo a costruire dai singoli campi dispersi
        if not candidate_blocks:
            rec = {
                "uuid": None,
                "status": None,
                "referenceNumber": None,
                "verificationNumber": None,
                "internalReferenceNumber": None,
                "date": None,
                "updatedBy": None,
            }
            for el in root.iter():
                n = L(el.tag)
                if n in {"uuid", "ddsIdentifier"} and el.text:
                    rec["uuid"] = el.text.strip()
                elif n in {"status", "ddsStatus"} and el.text:
                    rec["status"] = el.text.strip()
                elif n in {"referenceNumber", "ddsReferenceNumber"} and el.text:
                    rec["referenceNumber"] = el.text.strip()
                elif n == "verificationNumber" and el.text:
                    rec["verificationNumber"] = el.text.strip()
                elif n in {"internalReferenceNumber", "internalReference"} and el.text:
                    rec["internalReferenceNumber"] = el.text.strip()
                elif n in {"date", "statusDate", "lastUpdateDate", "updatedOn"} and el.text:
                    rec["date"] = el.text.strip()
                elif n in {"updatedBy", "lastUpdatedBy"} and el.text:
                    rec["updatedBy"] = el.text.strip()
            return [rec] if rec.get("uuid") else []

        for node in candidate_blocks:
            rec = {
                "uuid": None,
                "status": None,
                "referenceNumber": None,
                "verificationNumber": None,
                "internalReferenceNumber": None,
                "date": None,
                "updatedBy": None,
            }
            # Scansione profonda per local-names comuni
            for ch in node.iter():
                n = L(ch.tag)
                if n in {"uuid", "ddsIdentifier"} and ch.text:
                    rec["uuid"] = ch.text.strip()
                elif n in {"status", "ddsStatus"} and ch.text:
                    rec["status"] = ch.text.strip()
                elif n in {"referenceNumber", "ddsReferenceNumber"} and ch.text:
                    rec["referenceNumber"] = ch.text.strip()
                elif n == "verificationNumber" and ch.text:
                    rec["verificationNumber"] = ch.text.strip()
                elif n in {"internalReferenceNumber", "internalReference"} and ch.text:
                    rec["internalReferenceNumber"] = ch.text.strip()
                elif n in {"date", "statusDate", "lastUpdateDate", "updatedOn"} and ch.text:
                    rec["date"] = ch.text.strip()
                elif n in {"updatedBy", "lastUpdatedBy"} and ch.text:
                    rec["updatedBy"] = ch.text.strip()
            if rec.get("uuid"):
                out.append(rec)

        return out

    # Convenience
    def get_numbers(self, uuid: str) -> Dict[str, Optional[str]]:
        """
        Recupera e ritorna un singolo dict per l'UUID dato.
        Esempio di output:
        {
            'uuid': '...',
            'status': 'Available',
            'referenceNumber': 'EUDR.IT.XXXX/....',
            'verificationNumber': 'ABCD-1234'
        }
        """
        status, text = self.retrieve_dds(uuid)
        result = {
            "uuid": uuid,
            "status": None,
            "referenceNumber": None,
            "verificationNumber": None,
            "internalReferenceNumber": None,
            "date": None,
            "updatedBy": None,
            "httpStatus": status,
            "wsRequestId": self.parse_ws_request_id(text) if text else None,
            "raw": text,
        }
        if status != 200 or not text:
            return result

        entries = self.parse_retrieval_result(text) or []
        hit = next((e for e in entries if e.get("uuid") == uuid), None) or (entries[0] if entries else None)
        if hit:
            result.update({
                "status": hit.get("status"),
                "referenceNumber": hit.get("referenceNumber"),
                "verificationNumber": hit.get("verificationNumber"),
                "internalReferenceNumber": hit.get("internalReferenceNumber"),
                "date": hit.get("date"),
                "updatedBy": hit.get("updatedBy"),
            })
        return result
