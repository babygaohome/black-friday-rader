"""Minimal AWS Signature Version 4 for the Product Advertising API."""
import hashlib
import hmac
from datetime import datetime, timezone


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def signing_key(secret: str, date_stamp: str, region: str, service: str) -> bytes:
    k = _hmac(("AWS4" + secret).encode(), date_stamp)
    return _hmac(_hmac(_hmac(k, region), service), "aws4_request")


def sign_request(
    *, access_key: str, secret_key: str, region: str, service: str, host: str, path: str,
    headers: dict[str, str], payload: str, now: datetime | None = None, method: str = "POST",
) -> dict[str, str]:
    """Return `headers` plus x-amz-date and Authorization. `headers` must already include content-encoding/type/x-amz-target."""
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    signed = {k.lower(): " ".join(v.split()) for k, v in headers.items()}
    signed["host"] = host
    signed["x-amz-date"] = amz_date
    names = sorted(signed)
    canonical_headers = "".join(f"{n}:{signed[n]}\n" for n in names)
    signed_headers = ";".join(names)
    payload_hash = hashlib.sha256(payload.encode()).hexdigest()
    canonical_request = "\n".join([method, path, "", canonical_headers, signed_headers, payload_hash])

    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
    )
    signature = hmac.new(signing_key(secret_key, date_stamp, region, service), string_to_sign.encode(), hashlib.sha256).hexdigest()

    out = dict(headers)
    out["x-amz-date"] = amz_date
    out["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
    )
    return out
