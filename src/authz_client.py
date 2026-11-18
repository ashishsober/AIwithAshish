"""Asks authz-api (repo ai-authorization-api) whether someone is a super admin, the way auth-api does.

Super admins have no daily Qwen Chat limit and may use /api/chat/admin/*. The shared token comes from the
authz-internal Secret (AUTHZ_INTERNAL_TOKEN); without it nobody counts as a super admin here.
Answers are kept for a minute, so a question costs at most one extra call a minute.
"""
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger("chat_api.authz")

AUTHZ_API_URL = os.getenv("AUTHZ_API_URL", "http://authz-api:7100").rstrip("/")
CACHE_SECONDS = 60


class AuthzUnavailable(Exception):
    pass


_cache: dict = {}
_lock = threading.Lock()


def is_super_admin(user_id: int) -> bool:
    """True or False from authz-api. Raises AuthzUnavailable when it can't answer."""
    token = os.getenv("AUTHZ_INTERNAL_TOKEN", "")
    if not token:
        raise AuthzUnavailable("AUTHZ_INTERNAL_TOKEN is not set")
    now = time.monotonic()
    with _lock:
        hit = _cache.get(user_id)
        if hit and hit[0] > now:
            return hit[1]
    req = urllib.request.Request(f"{AUTHZ_API_URL}/authz/internal/access/{int(user_id)}",
                                 headers={"X-Internal-Token": token, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            answer = bool(json.loads(res.read().decode()).get("is_super_admin"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AuthzUnavailable(str(exc)) from exc
    with _lock:
        _cache[user_id] = (now + CACHE_SECONDS, answer)
    return answer


def is_super_admin_or_false(user_id: int) -> bool:
    """For limits: if authz-api can't answer, the person's own plan applies."""
    try:
        return is_super_admin(user_id)
    except AuthzUnavailable as exc:
        log.warning("authz-api unavailable, applying the plan limit: %s", exc)
        return False
