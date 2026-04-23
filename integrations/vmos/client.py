import binascii
import datetime
import hashlib
import hmac
import json
import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


class VmosClient:
    API_HOST = "api.vmoscloud.com"
    CONTENT_TYPE = "application/json;charset=UTF-8"
    SERVICE = "armcloud-paas"
    ALGORITHM = "HMAC-SHA256"

    def __init__(self, ak=None, sk=None, host=None):
        self.ak = ak or os.environ.get("VMOS_AK")
        self.sk = sk or os.environ.get("VMOS_SK")
        self.host = host or os.environ.get("VMOS_HOST", self.API_HOST)

        if not self.ak or not self.sk:
            raise ValueError("VMOS_AK and VMOS_SK must be set")
        if self.ak.startswith("PASTE_") or self.sk.startswith("PASTE_"):
            logger.warning("AK/SK appear to be placeholder values - API calls may fail")

    def _get_x_date(self):
        return datetime.datetime.now().utcnow().strftime("%Y%m%dT%H%M%SZ")

    def _sha256_hex(self, data):
        if isinstance(data, dict):
            data = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        elif not isinstance(data, str):
            data = str(data)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def _hmac_sha256(self, key, data):
        if isinstance(key, str):
            key = key.encode("utf-8")
        if isinstance(data, str):
            data = data.encode("utf-8")
        return hmac.new(key, data, hashlib.sha256).digest()

    def _get_signature(self, x_date, body):
        short_date = x_date[:8]
        x_content_sha256 = self._sha256_hex(body) if body else self._sha256_hex("")

        canonical_string = (
            f"host:{self.host}\n"
            f"x-date:{x_date}\n"
            f"content-type:{self.CONTENT_TYPE}\n"
            f"signedHeaders:content-type;host;x-content-sha256;x-date\n"
            f"x-content-sha256:{x_content_sha256}"
        )

        credential_scope = f"{short_date}/{self.SERVICE}/request"

        hash_canonical = self._sha256_hex(canonical_string)

        string_to_sign = (
            f"{self.ALGORITHM}\n"
            f"{x_date}\n"
            f"{credential_scope}\n"
            f"{hash_canonical}"
        )

        k_date = self._hmac_sha256(self.sk, short_date)
        k_service = self._hmac_sha256(k_date, self.SERVICE)
        sign_key = self._hmac_sha256(k_service, "request")

        signature = self._hmac_sha256(sign_key, string_to_sign)
        return binascii.hexlify(signature).decode()

    def _get_authorization_header(self, x_date, body):
        signature = self._get_signature(x_date, body)
        short_date = x_date[:8]
        credential_scope = f"{short_date}/{self.SERVICE}/request"

        return (
            f"HMAC-SHA256 Credential={self.ak}/{credential_scope}, "
            f"SignedHeaders=content-type;host;x-content-sha256;x-date, "
            f"Signature={signature}"
        )

    def request(self, method, path, data=None, timeout=30):
        x_date = self._get_x_date()

        body_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if data else ""

        headers = {
            "content-type": self.CONTENT_TYPE,
            "x-date": x_date,
            "x-host": self.host,
            "authorization": self._get_authorization_header(x_date, body_str),
        }

        url = f"{self.host}{path}"

        logger.info(f"VMOS API Request: {method} {url}")
        if data:
            logger.debug(f"Request body: {body_str}")

        try:
            if method.upper() == "POST":
                response = requests.post(
                    url,
                    headers=headers,
                    data=body_str.encode("utf-8"),
                    timeout=timeout
                )
            else:
                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    data=body_str.encode("utf-8") if body_str else None,
                    timeout=timeout
                )

            logger.info(f"Response status: {response.status_code}")

            try:
                result = response.json()
                logger.debug(f"Response: {result}")
                return result
            except json.JSONDecodeError:
                logger.warning(f"Response is not JSON: {response.text[:200]}")
                return {"raw": response.text, "status_code": response.status_code}

        except requests.exceptions.Timeout:
            logger.error(f"Request timeout after {timeout}s")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise

    def get_sts_token(self, pad_code):
        path = "/vcpcloud/api/padApi/stsTokenByPadCode"
        data = {"padCode": pad_code}
        return self.request("POST", path, data)

    def get_instance_list(self, page=1, rows=10):
        path = "/vcpcloud/api/padApi/infos"
        data = {"page": page, "rows": rows}
        return self.request("POST", path, data)

    def get_instance_info(self, pad_code):
        path = "/vcpcloud/api/padApi/padInfo"
        data = {"padCode": pad_code}
        return self.request("POST", path, data)

    def get_task_status(self, task_id):
        path = "/vcpcloud/api/padApi/padTaskDetail"
        data = {"taskIds": [task_id]}
        return self.request("POST", path, data)


def get_client():
    return VmosClient()