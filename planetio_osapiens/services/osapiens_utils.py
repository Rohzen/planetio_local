# -*- coding: utf-8 -*-
import json
import base64

def to_b64_json(data: dict) -> str:
    return base64.b64encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode('utf-8')).decode('ascii')