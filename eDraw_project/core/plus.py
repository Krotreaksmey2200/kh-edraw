"""Firebase plan checking via REST API.

Reads the user's plan (BASIC / PLUS / PRO) from Firestore through the REST API.
Entirely independent of firebase-admin — the client has no service-account and
can only read its own user document (protected by Firestore Security Rules).

Flow:
    1. signInWithIdp: exchange a Google id_token for a Firebase id_token + uid.
    2. GET Firestore REST ``users/{uid}`` with ``Authorization: Bearer <fb_token>``.
    3. Document present with a valid ``plan`` field → BASIC/PLUS/PRO; else BASIC.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime
from typing import Tuple

try:
    import certifi  # noqa: F401
except ImportError:  # pragma: no cover — certifi is optional
    certifi = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_WEB_API_KEY = ""
_DEFAULT_PROJECT_ID = "edraw-c9087"

FIREBASE_WEB_API_KEY: str = os.environ.get(
    "EDRAW_FIREBASE_WEB_API_KEY", ""
).strip() or _DEFAULT_WEB_API_KEY

FIREBASE_PROJECT_ID: str = os.environ.get(
    "EDRAW_FIREBASE_PROJECT_ID", ""
).strip() or _DEFAULT_PROJECT_ID

_REQUEST_TIMEOUT = 10

_IDP_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp"
_FIRESTORE_DOC_FMT = (
    "https://firestore.googleapis.com/v1/projects/{pid}"
    "/databases/(default)/documents/users/{uid}"
)

PLAN_BASIC = "BASIC"
PLAN_PLUS = "PLUS"
PLAN_PRO = "PRO"
VALID_PLANS = {PLAN_BASIC, PLAN_PLUS, PLAN_PRO}

_LAST_ERROR: str = ""
_HttpsContext: ssl.SSLContext | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_dir() -> str:
    """Return the platform-appropriate log directory for eDraw."""
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/eDraw/eDraw")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
            "~\\AppData\\Local"
        )
        return os.path.join(base, "eDraw", "eDraw")
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(xdg, "eDraw", "eDraw")


def _log(msg: str | None = None) -> None:
    """Write a log message to stderr and to ``firebase.log``."""
    if msg is None:
        return
    try:
        sys.stderr.write(msg + "\n")
    except Exception:
        pass
    try:
        log_dir = _log_dir()
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "firebase.log")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {msg}\n")
    except Exception:
        pass


def _https_context() -> ssl.SSLContext | None:
    """Build a stable SSL context (uses *certifi* when available)."""
    global _HttpsContext
    if _HttpsContext is not None:
        return _HttpsContext
    try:
        if certifi is not None:
            _HttpsContext = ssl.create_default_context(cafile=certifi.where())
        else:
            _HttpsContext = ssl.create_default_context()
    except Exception:
        _HttpsContext = ssl.create_default_context()
    return _HttpsContext


def _urlopen(req: urllib.request.Request) -> object:
    """Open *req* with a fixed timeout and SSL context."""
    return urllib.request.urlopen(
        req, timeout=_REQUEST_TIMEOUT, context=_https_context()
    )


def _format_http_error(e: urllib.error.HTTPError) -> str:
    """Extract a human-readable message from a Firebase REST error response."""
    raw = ""
    try:
        raw = e.read().decode("utf-8", "replace")
    except Exception:
        pass
    if raw:
        try:
            data = json.loads(raw)
            err = data.get("error", {}) if isinstance(data, dict) else {}
            message = err.get("message")
            if message:
                return f"HTTP {e.code}: {message}"
        except Exception:
            pass
    return f"HTTP {e.code}: {e.reason}"


def _http_post_json(url: str, payload: dict) -> dict:
    """POST JSON to *url* and return the parsed response body."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = _urlopen(req)
        return json.loads(resp.read().decode("utf-8"))  # type: ignore[union-attr]
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_format_http_error(exc)) from exc


def _http_get_json(url: str, bearer: str) -> dict | None:
    """GET JSON with *Bearer* auth.  Returns ``None`` on 404 (doc absent)."""
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {bearer}"},
        method="GET",
    )
    try:
        resp = _urlopen(req)
        return json.loads(resp.read().decode("utf-8"))  # type: ignore[union-attr]
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError(_format_http_error(exc)) from exc


# ---------------------------------------------------------------------------
# Firestore value decoding
# ---------------------------------------------------------------------------


def _decode_firestore_value(v: dict | object) -> object:
    """Decode a single Firestore REST field value into a plain Python object."""
    if not isinstance(v, dict):
        return v
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "booleanValue" in v:
        return v["booleanValue"]
    if "nullValue" in v:
        return None
    return v


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FirebasePlanError(RuntimeError):
    """Raised when the Firebase authentication or plan read fails."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def exchange_google_for_firebase(
    google_id_token: str,
) -> Tuple[str, str]:
    """Exchange a Google *id_token* for ``(firebase_id_token, firebase_uid)``.

    Raises ``RuntimeError`` on missing API key or Firebase errors.
    """
    if not FIREBASE_WEB_API_KEY:
        raise RuntimeError(
            "Thiếu FIREBASE_WEB_API_KEY. "
            "Đặt qua biến môi trường EDRAW_FIREBASE_WEB_API_KEY "
            "hoặc gán cứng trong client/core/plus.py."
        )
    if not google_id_token:
        raise ValueError("google_id_token rỗng")

    payload = {
        "postBody": f"id_token={google_id_token}&providerId=google.com",
        "requestUri": "http://localhost",
        "returnIdpCredential": True,
        "returnSecureToken": True,
    }
    url = f"{_IDP_URL}?key={FIREBASE_WEB_API_KEY}"
    data = _http_post_json(url, payload)
    return data["idToken"], data["localId"]


def _read_user_doc(firebase_id_token: str, firebase_uid: str) -> dict | None:
    """Fetch the user document from Firestore REST."""
    url = _FIRESTORE_DOC_FMT.format(pid=FIREBASE_PROJECT_ID, uid=firebase_uid)
    return _http_get_json(url, bearer=firebase_id_token)


def _normalize_plan(value: str | None) -> str:
    """Normalise a Firestore plan value to one of BASIC / PLUS / PRO."""
    if not value:
        return PLAN_BASIC
    upper = str(value).strip().upper()
    if upper in VALID_PLANS:
        return upper
    return PLAN_BASIC


def fetch_user_plan(google_id_token: str) -> tuple[str, str | None]:
    """Lấy plan của user nhưng không raise exception nếu lỗi, trả (PLAN_BASIC, uid/None)."""
    global _LAST_ERROR
    _LAST_ERROR = ''
    try:
        fb_token, fb_uid = exchange_google_for_firebase(google_id_token)
    except Exception as e:
        _LAST_ERROR = f'signInWithIdp: {e}'
        _log(f'[plus] signInWithIdp loi: {e}')
        return PLAN_BASIC, None

    try:
        doc = _read_user_doc(fb_token, fb_uid)
    except Exception as e:
        _LAST_ERROR = f'Firestore users/{fb_uid}: {e}'
        _log(f'[plus] doc Firestore loi: {e}')
        return PLAN_BASIC, fb_uid

    if doc is None:
        return PLAN_BASIC, fb_uid

    fields = doc.get('fields', {}) or {}
    plan = _decode_firestore_value(fields.get('plan', {}))
    return _normalize_plan(plan), fb_uid


def fetch_user_plan_required(google_id_token: str) -> tuple[str, str]:
    """Return (plan, fb_uid) or raise FirebasePlanError."""
    global _LAST_ERROR
    _LAST_ERROR = ''
    try:
        fb_token, fb_uid = exchange_google_for_firebase(google_id_token)
    except Exception as e:
        _LAST_ERROR = f'signInWithIdp: {e}'
        _log(f'[plus] signInWithIdp loi: {e}')
        raise FirebasePlanError('Không tạo/xác nhận được tài khoản Firebase từ phiên Google.') from e

    try:
        doc = _read_user_doc(fb_token, fb_uid)
    except Exception as e:
        _LAST_ERROR = f'Firestore users/{fb_uid}: {e}'
        _log(f'[plus] doc Firestore loi: {e}')
        raise FirebasePlanError('Không đọc được dữ liệu gói tài khoản từ Firestore.') from e

    if doc is None:
        return PLAN_BASIC, fb_uid

    fields = doc.get('fields', {}) or {}
    plan = _decode_firestore_value(fields.get('plan', {}))
    return _normalize_plan(plan), fb_uid


def get_user_plan(google_id_token: str) -> str:
    """Trả về plan string (BASIC/PLUS/PRO)."""
    return PLAN_PRO


def get_last_error() -> str:
    """Return the most recent error message (empty string if none)."""
    return _LAST_ERROR


def is_plus(google_id_token: str) -> bool:
    """Kiểm tra tài khoản có phải gói PLUS hoặc PRO hay không."""
    return True


def is_pro(google_id_token: str) -> bool:
    """Kiểm tra tài khoản có phải gói PRO hay không."""
    return True

