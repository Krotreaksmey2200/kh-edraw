# core/auth.py
# Quản lý đăng nhập Google OAuth2, lưu Refresh Token qua Keyring, lấy userinfo.
from __future__ import annotations
import os
import base64
import html as _html
import json
import urllib.parse
import urllib.request
import webbrowser
import wsgiref.simple_server
import wsgiref.util

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import keyring

from core.i18n import current_language, t

KEYRING_SERVICE = 'eDrawApp'
KEYRING_USERNAME = 'refresh_token'
KEYRING_PROFILE_USERNAME = 'user_profile'
PROFILE_FIELDS = ('sub', 'email', 'name', 'picture')

CLIENT_CONFIG = {
    'web': {
        'client_id': os.environ.get('GOOGLE_CLIENT_ID', ''),
        'client_secret': os.environ.get('GOOGLE_CLIENT_SECRET', ''),
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
        'redirect_uris': ['http://localhost:8080/'],
    }
}

SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
]

_PAGE_CSS = '''*,*::before,*::after{box-sizing:border-box;margin:0}
:root{--navy:#172033;--teal:#14b8a6;--teal2:#0f766e;--bg:#eef3f8;--soft:#f6f9fc;--line:#d4dde8;--text:#172033;--muted:#5e7288}
html,body{min-height:100vh}
body{font:16px/1.74 "DM Sans",system-ui,sans-serif;color:var(--text);background:linear-gradient(180deg,#f8fbff 0,var(--bg) 60%,#edf3fa 100%);display:flex;flex-direction:column}
.site-header{background:var(--navy);border-bottom:1px solid rgba(255,255,255,.08);box-shadow:0 2px 20px rgba(0,0,0,.16)}
.header-inner{height:58px;display:flex;align-items:center;padding:0 clamp(16px,4vw,40px)}
.brand{display:flex;align-items:center;gap:11px;text-decoration:none}
.brand-icon{width:36px;height:36px;border-radius:10px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.14);display:grid;place-items:center;flex-shrink:0}
.brand-icon svg{width:22px;height:22px}
.brand-text .name{display:block;color:#fff;font-weight:800;font-family:"Bricolage Grotesque",sans-serif}
.brand-text .tagline{display:block;color:rgba(255,255,255,.45);font-size:.72rem}
main{flex:1;display:flex;align-items:center;justify-content:center;padding:60px 20px}
.auth-card{width:min(460px,100%);background:#fff;border:1px solid var(--line);border-radius:18px;padding:42px 36px 32px;box-shadow:0 16px 50px rgba(23,32,51,.13);text-align:center;position:relative;overflow:hidden}
.auth-card::after{content:'';position:absolute;left:0;right:0;bottom:0;height:3px}
.card-success::after{background:linear-gradient(90deg,var(--teal),var(--teal2))}
.card-failure::after{background:linear-gradient(90deg,#dc2626,#f97316)}
.auth-icon{width:72px;height:72px;border-radius:18px;display:grid;place-items:center;margin:0 auto 18px}
.auth-icon svg{width:40px;height:40px}
.icon-success{background:rgba(20,184,166,.1);border:1px solid rgba(20,184,166,.2)}
.icon-failure{background:rgba(220,38,38,.08);border:1px solid rgba(220,38,38,.18)}
h1{font-family:"Bricolage Grotesque",sans-serif;font-size:1.7rem;font-weight:800;margin:0 0 8px;line-height:1.12;color:var(--text)}
.sub{font-size:1rem;color:var(--muted);margin:0 0 18px;line-height:1.6}
.hint{padding:12px 14px;border-radius:10px;background:var(--soft);border:1px solid var(--line);color:var(--muted);font-size:.92rem;text-align:left;line-height:1.6}
.hint strong{color:var(--text)}
.hint ul{padding-left:20px;margin-top:6px}
.hint li{margin-top:4px}
.hint p{margin-top:8px}
.error-code{display:inline-block;font-family:Consolas,Menlo,monospace;font-size:.82rem;color:#dc2626;background:#fee2e2;border:1px solid #fecaca;border-radius:6px;padding:3px 10px;margin-bottom:14px}
kbd{padding:1px 7px;border-radius:6px;background:#fff;border:1px solid var(--line);font-family:Consolas,monospace;font-size:.86em;color:var(--text)}
.auth-badge{display:inline-flex;align-items:center;gap:7px;padding:5px 13px;border-radius:999px;background:rgba(20,184,166,.1);border:1px solid rgba(20,184,166,.22);font-size:.78rem;font-weight:800;color:var(--teal2);text-transform:uppercase;letter-spacing:.06em;margin-top:18px}
.auth-badge::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--teal)}
.site-footer{background:var(--navy);padding:18px clamp(16px,4vw,40px);text-align:center}
.site-footer p{color:rgba(255,255,255,.4);font-size:.82rem}
@media(max-width:640px){.auth-card{padding:32px 22px}h1{font-size:1.4rem}}
'''

_BRAND_SVG = '''<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="none">
  <path d="M4 17 C 8 4, 16 20, 20 7"
        stroke="#fff" stroke-width="2.2"
        stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="4"  cy="17" r="1.4" fill="#14b8a6"/>
  <circle cx="8"  cy="4"  r="1.4" fill="#14b8a6"/>
  <circle cx="16" cy="20" r="1.4" fill="#14b8a6"/>
  <circle cx="20" cy="7"  r="1.4" fill="#14b8a6"/>
</svg>'''

_LOGO_SVG = '''<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="none">
  <path d="M4 17 C 8 4, 16 20, 20 7"
        stroke="{stroke}" stroke-width="2.2"
        stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="4"  cy="17" r="1.6" fill="{dot}"/>
  <circle cx="8"  cy="4"  r="1.6" fill="{dot}"/>
  <circle cx="16" cy="20" r="1.6" fill="{dot}"/>
  <circle cx="20" cy="7"  r="1.6" fill="{dot}"/>
</svg>'''

_CLOSE_TAB_JS = """function tryClose() {
  try { window.opener = window; } catch (e) {}
  try { window.open('', '_self'); } catch (e) {}
  try { window.close(); } catch (e) {}
  try { self.close(); } catch (e) {}
}
setTimeout(tryClose, 80);
setTimeout(tryClose, 400);
setTimeout(tryClose, 1200);
"""


def _render_page(
    *,
    title: str,
    h1: str,
    sub: str,
    body_html: str,
    logo_variant: str,
    role: str,
    aria_live: str,
    extra_script: str,
) -> str:
    """Wrapper HTML chung — header (brand), card (icon + h1 + sub + body), footer."""
    if logo_variant == 'failure':
        card_class = 'card-failure'
        icon_class = 'icon-failure'
        logo_svg = _LOGO_SVG.format(stroke='#dc2626', dot='#f97316')
    else:
        card_class = 'card-success'
        icon_class = 'icon-success'
        logo_svg = _LOGO_SVG.format(stroke='#0f766e', dot='#14b8a6')

    script_block = f'<script>{extra_script}</script>' if extra_script else ''
    lang = current_language()
    return ''.join([
        '<!DOCTYPE html>\n<html lang="',
        f'{lang}',
        '">\n<head>\n  <meta charset="utf-8">\n  <title>eDraw · ',
        f'{title}',
        '</title>\n  <meta name="viewport" content="width=device-width,initial-scale=1">\n  <link rel="preconnect" href="https://fonts.googleapis.com">\n  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n  <link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,700&display=swap" rel="stylesheet">\n  <style>',
        f'{_PAGE_CSS}',
        '</style>\n</head>\n<body>\n<header class="site-header">\n  <div class="header-inner">\n    <div class="brand">\n      <div class="brand-icon" aria-hidden="true">',
        f'{_BRAND_SVG}',
        '</div>\n      <div class="brand-text">\n        <span class="name">eDraw</span>\n        <span class="tagline">',
        f"{t('Bảng viết số · Hình học · PDF · Trí tuệ nhân tạo')}",
        '</span>\n      </div>\n    </div>\n  </div>\n</header>\n<main>\n  <div class="auth-card ',
        f'{card_class}',
        '" role="',
        f'{role}',
        '" aria-live="',
        f'{aria_live}',
        '">\n    <div class="auth-icon ',
        f'{icon_class}',
        '" aria-hidden="true">\n      ',
        f'{logo_svg}',
        '\n    </div>\n    <h1>',
        f'{h1}',
        '</h1>\n    <p class="sub">',
        f'{sub}',
        '</p>\n    ',
        f'{body_html}',
        '\n  </div>\n</main>\n<footer class="site-footer"><p>',
        f"{t('© 2026 eDraw · Bảng viết kỹ thuật số & Soạn đề AI')}",
        '</p></footer>\n',
        f'{script_block}',
        '\n</body>\n</html>\n',
    ])


def get_success_page() -> str:
    return _render_page(
        title=t('Đăng nhập thành công'),
        h1=t('Đăng nhập thành công'),
        sub=t('eDraw đã nhận phiên đăng nhập của bạn. Hãy quay lại ứng dụng để tiếp tục.'),
        body_html='<div class="hint">' + t('<strong>Mẹo:</strong> Nếu tab này không tự đóng, bạn có thể đóng tay bằng <kbd>Ctrl</kbd>+<kbd>W</kbd>. eDraw đã tiếp tục khởi động.') + f'</div><span class="auth-badge">{t("Đã kết nối")}</span>',
        logo_variant='success',
        role='status',
        aria_live='polite',
        extra_script=_CLOSE_TAB_JS,
    )


def _render_failure_page(error_code: str | None = None, error_description: str | None = None) -> str:
    """Sinh HTML lỗi với mã + mô tả đã escape an toàn."""
    code = _html.escape(error_code or 'unknown_error')
    desc_html = ''
    if error_description:
        desc_html = f'<p>{t("<strong>Chi tiết:</strong> ")}{_html.escape(error_description)}</p>'
    body_html = (
        f'<span class="error-code">{code}</span><div class="hint">{t("<strong>Lý do thường gặp:</strong>")}<ul>'
        f'<li>{t("Đóng cửa sổ đăng nhập trước khi cấp quyền.")}</li>'
        f'<li>{t("Mất kết nối mạng tạm thời.")}</li>'
        f'<li>{t("Tài khoản Google bị hạn chế quyền truy cập ứng dụng.")}</li></ul>'
        + desc_html +
        f'<p>{t("Vui lòng quay lại cửa sổ <strong>eDraw</strong> và bấm <strong>Thử lại</strong>. Nếu lỗi tái diễn, kiểm tra kết nối mạng hoặc tài khoản Google của bạn.")}</p></div>'
    )
    return _render_page(
        title=t('Đăng nhập không thành công'),
        h1=t('Đăng nhập không thành công'),
        sub=t('eDraw chưa nhận được phiên đăng nhập từ Google.'),
        body_html=body_html,
        logo_variant='failure',
        role='alert',
        aria_live='assertive',
        extra_script='',
    )


class _HtmlRedirectApp:
    """WSGI callback app trả HTML thương hiệu eDraw thay vì text/plain."""

    def __init__(self, success_html: str | None = None):
        self.last_request_uri = None
        self.error_code = None
        self.error_description = None
        self._success_html = success_html

    def __call__(self, environ, start_response):
        request_uri = wsgiref.util.request_uri(environ)
        self.last_request_uri = request_uri
        try:
            qs = urllib.parse.urlparse(request_uri).query
            params = urllib.parse.parse_qs(qs)
        except Exception:
            params = {}

        error = (params.get('error') or [''])[0]
        if error:
            self.error_code = error
            self.error_description = (params.get('error_description') or [''])[0]
            html_body = _render_failure_page(error, self.error_description or '')
            status = '200 OK'
        else:
            html_body = self._success_html
            status = '200 OK'

        body = html_body.encode('utf-8')
        start_response(status, [
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Content-Length', str(len(body))),
            ('Cache-Control', 'no-store'),
        ])
        return [body]


def _run_local_server_html(flow, port: int, prompt: str, access_type: str, success_html: str):
    """Chạy OAuth local-server flow nhưng trả callback dạng HTML."""
    wsgi_app = _HtmlRedirectApp(success_html)
    wsgiref.simple_server.WSGIServer.allow_reuse_address = False
    local_server = wsgiref.simple_server.make_server(
        'localhost', port, wsgi_app, handler_class=wsgiref.simple_server.WSGIRequestHandler
    )
    try:
        flow.redirect_uri = f'http://localhost:{local_server.server_port}/'
        auth_url, _ = flow.authorization_url(prompt=prompt, access_type=access_type)
        webbrowser.open(auth_url, new=1, autoraise=True)
        print(f'Please visit this URL to authorize this application: {auth_url}')
        local_server.handle_request()
        if not wsgi_app.last_request_uri:
            raise RuntimeError(t('Không nhận được callback đăng nhập Google.'))
        if wsgi_app.error_code:
            desc = wsgi_app.error_description or ''
            msg = t('Google trả về lỗi: {error}', error=wsgi_app.error_code)
            if desc:
                msg += f' — {desc}'
            raise RuntimeError(msg)
        authorization_response = wsgi_app.last_request_uri.replace('http', 'https', 1)
        flow.fetch_token(authorization_response=authorization_response)
        local_server.server_close()
        return flow.credentials
    finally:
        local_server.server_close()


def login_with_google():
    """Thực hiện luồng đăng nhập Google và lưu Refresh Token vào hệ thống."""
    print('Đang khởi tạo luồng đăng nhập Google...')
    flow = InstalledAppFlow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
    credentials = _run_local_server_html(
        flow, port=8080, prompt='consent', access_type='offline', success_html=get_success_page()
    )
    id_token = credentials.id_token
    refresh_token = credentials.refresh_token
    _fetch_and_save_user_profile(credentials)
    print('\n--- ĐĂNG NHẬP THÀNH CÔNG ---')
    if refresh_token:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, refresh_token)
        print('Đã lưu Refresh Token vào hệ thống an toàn (Keyring).')
    return id_token, credentials


def get_saved_refresh_token() -> str | None:
    """Đọc refresh_token đã lưu trong Keyring (nếu có)."""
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        return None


def _load_saved_user_profile() -> dict:
    try:
        raw = keyring.get_password(KEYRING_SERVICE, KEYRING_PROFILE_USERNAME)
        if not raw:
            return {}
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def _save_user_profile(info: dict | None = None) -> None:
    """Lưu các trường hồ sơ ổn định, đặc biệt là picture URL."""
    try:
        profile = {
            key: str(info.get(key, '') or '')
            for key in PROFILE_FIELDS
            if info.get(key)
        }
        if not profile:
            return
        keyring.set_password(
            KEYRING_SERVICE,
            KEYRING_PROFILE_USERNAME,
            json.dumps(profile, ensure_ascii=False),
        )
    except Exception:
        pass


def _fetch_and_save_user_profile(credentials=None) -> dict:
    """Lấy Google userinfo để giữ avatar thật ổn định khi refresh token."""
    token = getattr(credentials, 'token', None)
    if not token:
        return {}
    try:
        req = urllib.request.Request(
            'https://openidconnect.googleapis.com/v1/userinfo',
            headers={'Authorization': f'Bearer {token}'},
        )
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if isinstance(data, dict):
            _save_user_profile(data)
            return data
        return {}
    except Exception as e:
        print(f'[auth] Không lấy được Google userinfo: {e}')
        return {}


def is_logged_in() -> bool:
    """Kiểm tra nhanh: đã từng lưu refresh_token chưa (không validate online)."""
    token = get_saved_refresh_token()
    return bool(token)


def refresh_credentials():
    """Validate refresh_token bằng cách gọi token endpoint của Google."""
    rt = get_saved_refresh_token()
    if not rt:
        return None, None
    web = CLIENT_CONFIG['web']
    creds = Credentials(
        token=None,
        refresh_token=rt,
        token_uri=web['token_uri'],
        client_id=web['client_id'],
        client_secret=web['client_secret'],
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
        _fetch_and_save_user_profile(creds)
        return creds.id_token, creds
    except Exception as e:
        print(f'Refresh token không còn hợp lệ: {e}')
        return None, None


def get_user_info(id_token: str | None = None) -> dict:
    """Decode (không verify chữ ký) phần payload của id_token để lấy uid/email."""
    if not id_token:
        return _load_saved_user_profile()
    try:
        payload_b64 = id_token.split('.')[1]
        payload_b64 += '=' * (-len(payload_b64) % 4)
        info = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        info = {}

    saved = _load_saved_user_profile()
    same_email = bool(saved.get('email')) and bool(info.get('email')) and saved.get('email') == info.get('email')
    same_sub = bool(saved.get('sub')) and bool(info.get('sub')) and saved.get('sub') == info.get('sub')
    if same_email and same_sub:
        for key in PROFILE_FIELDS:
            if not info.get(key) and saved.get(key):
                info[key] = saved[key]
    _save_user_profile(info)
    return info


def logout() -> None:
    """Xóa refresh_token đã lưu khỏi Keyring."""
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass
    except Exception:
        pass

    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_PROFILE_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass
    except Exception:
        pass
