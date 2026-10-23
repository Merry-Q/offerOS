"""Bounded anonymous fetch with public DNS validation and IP-pinned connections."""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

MAX_BYTES = 2_000_000


def public_target(url: str) -> tuple:
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
            raise ValueError()
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port != (443 if parts.scheme == "https" else 80):
            raise ValueError()
        if any(re.search(r"token|secret|password|auth|session|email|phone|key", key, re.I) for key, _ in parse_qsl(parts.query)):
            raise ValueError()
        host = parts.hostname.encode("idna").decode()
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ips = list(dict.fromkeys(a[4][0] for a in addresses))
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise ValueError()
        if any(c in url for c in "\r\n\x00"):
            raise ValueError()
        return parts, host, port, ips[0]
    except (ValueError, OSError, UnicodeError):
        raise ValueError("招聘链接不是可安全访问的公开网址") from None


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip, tls):
        super().__init__(host, port, timeout=12)
        self.ip, self.tls = ip, tls

    def connect(self):
        self.sock = socket.create_connection((self.ip, self.port), self.timeout)
        if self.tls:
            self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=self.host)


def fetch_public_page(url: str) -> tuple[str, str]:
    """No proxy, cookies, auth, JS, third-party readers, or unchecked redirects."""
    for _ in range(4):
        parts, host, port, ip = public_target(url)
        connection = _PinnedHTTP(host, port, ip, parts.scheme == "https")
        try:
            path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            connection.request("GET", path, headers={"Host": host, "User-Agent": "OfferOS/1.0 public-job-verifier", "Accept": "text/html,application/ld+json", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                target = response.getheader("Location")
                if not target:
                    raise ValueError("招聘页面跳转失败")
                url = urljoin(url, target)
                continue
            if response.status != 200:
                raise ValueError(f"招聘页无法访问（HTTP {response.status}）")
            content_type = response.getheader("Content-Type", "").lower()
            if not any(t in content_type for t in ("text/html", "text/plain", "application/xhtml", "application/ld+json", "application/json")):
                raise ValueError("招聘页不是可读取的文本页面")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("招聘页面压缩格式不支持安全读取")
            chunks, size, deadline = [], 0, time.monotonic() + 20
            while True:
                chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES or time.monotonic() > deadline:
                    raise ValueError("招聘页面过大或读取超时，未完成核验")
            raw = b"".join(chunks)
            if len(raw) > MAX_BYTES:
                raise ValueError("招聘页面过大，未完成核验")
            charset = re.search(r"charset=[\"']?([\w-]+)", content_type) or re.search(r"charset=[\"']?([\w-]+)", raw[:4096].decode("ascii", errors="ignore"), re.I)
            encoding = charset[1] if charset else "utf-8"
            try:
                return raw.decode(encoding, errors="replace"), url
            except LookupError:
                return raw.decode("utf-8", errors="replace"), url
        except (OSError, http.client.HTTPException):
            raise ValueError("招聘页连接失败或读取超时") from None
        finally:
            connection.close()
    raise ValueError("招聘链接跳转过多，未完成核验")
