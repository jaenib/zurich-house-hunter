from __future__ import annotations

import json
import re
import time
from typing import Dict, Optional
from urllib import error, parse, request

META_CHARSET_RE = re.compile(br"charset=['\"]?([A-Za-z0-9._-]+)", re.IGNORECASE)


class HttpClient:
    def __init__(self, user_agent: str, timeout_seconds: int, request_pause_seconds: float) -> None:
        self._user_agent = user_agent
        self._timeout_seconds = timeout_seconds
        self._request_pause_seconds = request_pause_seconds
        self._last_request_at = 0.0
        self._max_retries = 2

    def get_text(self, url: str, timeout_seconds: Optional[int] = None) -> str:
        response = self._open(url, timeout_seconds=timeout_seconds)
        body = response.read()
        charset = self._detect_charset(body, response.headers.get_content_charset())
        text = body.decode(charset, errors="replace")
        if charset.lower() in {"iso-8859-1", "latin-1", "windows-1252"} and text.count("Ã") >= 2:
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                pass
        return self._repair_mojibake(text)

    def post_form(self, url: str, payload: Dict[str, str], timeout_seconds: Optional[int] = None) -> Dict[str, object]:
        encoded = parse.urlencode(payload).encode("utf-8")
        response = self._open(url, data=encoded, timeout_seconds=timeout_seconds)
        body = response.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"ok": False, "description": body}

    def _open(self, url: str, data: Optional[bytes] = None, timeout_seconds: Optional[int] = None):
        last_error = None
        effective_timeout = timeout_seconds or self._timeout_seconds
        for attempt in range(self._max_retries + 1):
            self._respect_pause()
            req = request.Request(url=url, data=data)
            req.add_header("User-Agent", self._user_agent)
            req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
            req.add_header("Accept-Language", "de-CH,de;q=0.9,en;q=0.8")
            req.add_header("Connection", "close")
            if data is not None:
                req.add_header("Content-Type", "application/x-www-form-urlencoded")
            try:
                return request.urlopen(req, timeout=effective_timeout)
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code in {429, 500, 502, 503, 504} and attempt < self._max_retries:
                    last_error = RuntimeError("HTTP {0} for {1}: {2}".format(exc.code, url, body[:300]))
                    time.sleep(1 + attempt)
                    continue
                raise RuntimeError("HTTP {0} for {1}: {2}".format(exc.code, url, body[:300]))
            except (error.URLError, OSError) as exc:
                reason = getattr(exc, "reason", exc)
                last_error = RuntimeError("Network error for {0}: {1}".format(url, reason))
                if attempt < self._max_retries:
                    time.sleep(1 + attempt)
                    continue
                raise last_error
            finally:
                self._last_request_at = time.time()
        if last_error is not None:
            raise last_error
        raise RuntimeError("Request failed for {0}".format(url))

    def _respect_pause(self) -> None:
        if self._last_request_at <= 0:
            return
        elapsed = time.time() - self._last_request_at
        remaining = self._request_pause_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _detect_charset(self, body: bytes, header_charset: Optional[str]) -> str:
        meta_match = META_CHARSET_RE.search(body[:4096])
        if meta_match:
            return meta_match.group(1).decode("ascii", errors="ignore") or "utf-8"
        return header_charset or "utf-8"

    def _repair_mojibake(self, text: str) -> str:
        if not any(marker in text for marker in ["Ã", "Â", "â"]):
            return text
        try:
            repaired = text.encode("latin-1", errors="ignore").decode("utf-8")
        except UnicodeDecodeError:
            return text
        return repaired if repaired.count("Ã") < text.count("Ã") else text
