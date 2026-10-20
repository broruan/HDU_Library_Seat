"""Read the same current-user bootstrap as the official library SPA.

Authentication must not depend on whether a four-hour seat search is allowed.
No booking endpoint is called and credentials never follow an HTTP redirect.
"""
from html.parser import HTMLParser
import json
import urllib.error
import urllib.request

from .config import Settings
from .server import DEFAULT_BASE_URL


class _UserBootstrap(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.matches = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            self.depth += 1
        elif dict(attrs).get("id") == "lab-user-data":
            self.depth = 1
            self.matches += 1

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


class _NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _result(status: str, message: str) -> dict:
    return {"authenticated": status == "authenticated", "status": status, "message": message}


def verify_library_session(settings: Settings) -> dict:
    """Return only a sanitized verdict, never the identity or access token."""
    request = urllib.request.Request(DEFAULT_BASE_URL + "/", headers={
        "Accept": "text/html,application/xhtml+xml",
        "Cookie": settings.cookie,
        "User-Agent": settings.user_agent,
        "Cache-Control": "no-cache",
    })
    opener = urllib.request.build_opener(_NoCredentialRedirect())
    try:
        with opener.open(request, timeout=settings.request_timeout) as response:
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                return _result("upstream_error", "图书馆返回的登录页面异常，请重新加载后重试")
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        if code in (301, 302, 303, 307, 308, 401, 403):
            return _result("login_required", "请在学校官方页面完成账号登录后重试")
        return _result("upstream_error", "图书馆登录服务暂时不可用，请稍后重试")
    except (urllib.error.URLError, TimeoutError, OSError):
        return _result("network_error", "登录验证连接失败或超时，请检查网络后重试")

    parser = _UserBootstrap()
    try:
        parser.feed(raw.decode("utf-8", "replace"))
        if parser.matches != 1:
            return _result("upstream_error", "图书馆未返回完整的登录信息，请重新加载后重试")
        user = json.loads("".join(parser.parts))
    except (ValueError, TypeError):
        return _result("upstream_error", "图书馆登录信息解析失败，请重新加载后重试")
    if not isinstance(user, dict):
        return _result("upstream_error", "图书馆登录信息格式异常，请重新加载后重试")
    # Official mH bootstrap falls back from objectId to id, then uses it to
    # initialize unsafeUpdateCurrentUser. An accessToken is not required.
    identity = user.get("objectId") or user.get("id")
    if isinstance(identity, (str, int)) and not isinstance(identity, bool) and str(identity).strip() and identity:
        return _result("authenticated", "图书馆账号登录成功")
    return _result("login_required", "请在学校官方页面完成账号登录后重试")
