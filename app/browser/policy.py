"""BUDDY Browser Security and URL Policy.

Enforces scheme allowlisting, SSRF prevention, private network isolation,
cloud metadata endpoint blocking, strict domain allow/block matching,
and redirect destination re-evaluation.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import List, Optional, Set
from urllib.parse import urlparse

from app.browser.config import BrowserConfig
from app.browser.exceptions import BrowserSecurityError

logger = logging.getLogger("buddy.browser.policy")

# Strict scheme allowlist
ALLOWED_SCHEMES: Set[str] = {"http", "https"}

# Forbidden schemes that must be strictly rejected
FORBIDDEN_SCHEMES: Set[str] = {
    "file",
    "javascript",
    "data",
    "vbscript",
    "chrome",
    "edge",
    "about",
    "blob",
    "view-source",
    "ws",
    "wss",
    "ftp",
}

# Dangerous internal / private top-level or search domains
INTERNAL_TLDS: Set[str] = {
    ".local",
    ".internal",
    ".lan",
    ".corp",
    ".home",
    ".test",
    ".localhost",
    ".invalid",
}

# Cloud metadata addresses
CLOUD_METADATA_IPS: Set[str] = {
    "169.254.169.254",   # AWS, GCP, Azure, OpenStack
    "100.100.100.100",   # Alibaba Cloud
    "169.254.170.2",     # AWS ECS task metadata
}

CLOUD_METADATA_HOSTNAMES: Set[str] = {
    "metadata.google.internal",
    "metadata.internal",
    "instance-data",
}


class BrowserPolicy:
    """Evaluates and validates URLs against SSRF, domain, and scheme policies."""

    def __init__(self, config: Optional[BrowserConfig] = None) -> None:
        self._config = config or BrowserConfig()

    @property
    def config(self) -> BrowserConfig:
        return self._config

    def validate_url(self, url: str) -> str:
        """Validate and normalize a URL.

        Raises:
            BrowserSecurityError: If URL violates any security constraint.
        """
        if not url or not isinstance(url, str):
            raise BrowserSecurityError("URL must be a non-empty string.")

        clean_url = url.strip()

        # 1. Reject forbidden scheme patterns upfront (including javascript:...)
        scheme_prefix_match = re.match(r"^([a-zA-Z0-9+.-]+):", clean_url)
        if scheme_prefix_match:
            scheme = scheme_prefix_match.group(1).lower()
            if scheme in FORBIDDEN_SCHEMES:
                raise BrowserSecurityError(
                    f"Forbidden URL scheme '{scheme}:'. Browser only permits HTTP and HTTPS."
                )
            if scheme not in ALLOWED_SCHEMES:
                raise BrowserSecurityError(
                    f"Unsupported URL scheme '{scheme}:'. Only HTTP and HTTPS are allowed."
                )
        else:
            raise BrowserSecurityError(f"Missing scheme in URL: '{clean_url}'")

        try:
            parsed = urlparse(clean_url)
        except Exception as e:
            raise BrowserSecurityError(f"Failed to parse URL: {e}") from e

        scheme = (parsed.scheme or "").lower()
        if scheme not in ALLOWED_SCHEMES:
            raise BrowserSecurityError(
                f"URL scheme '{scheme}' is not allowed. Only HTTP and HTTPS are permitted."
            )

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise BrowserSecurityError("URL does not contain a valid hostname.")

        # 2. Check Punycode / Deceptive Unicode domain
        if hostname.startswith("xn--") or "xn--" in hostname:
            logger.warning("Punycode / IDN domain detected: %s", hostname)

        # 3. Check internal TLDs and hostnames
        for tld in INTERNAL_TLDS:
            if hostname.endswith(tld) or hostname == tld.lstrip("."):
                if not self._config.browser_allow_localhost:
                    raise BrowserSecurityError(
                        f"Navigation to internal domain '{hostname}' rejected by security policy."
                    )

        if hostname in CLOUD_METADATA_HOSTNAMES:
            raise BrowserSecurityError(
                f"SSRF defense: access to cloud metadata hostname '{hostname}' is blocked."
            )

        # 4. IP-based SSRF checks
        ip_obj = self._try_parse_ip(hostname)
        if ip_obj:
            self._validate_ip_address(ip_obj, hostname)
        else:
            # 5. Domain policy (allowlist / blocklist)
            self._validate_domain_policy(hostname)

            # 6. DNS resolution verification (detect SSRF via DNS rebinding / private IP resolution)
            if not self._config.browser_allow_localhost or not self._config.browser_allow_private_networks:
                self._validate_resolved_dns(hostname)

        return clean_url

    def _try_parse_ip(self, host: str) -> Optional[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            return None

    def _validate_ip_address(
        self,
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
        host_str: str,
    ) -> None:
        """Enforce SSRF restrictions on explicit IP addresses."""
        if str(ip) in CLOUD_METADATA_IPS:
            raise BrowserSecurityError(
                f"SSRF defense: access to cloud metadata IP '{ip}' is blocked."
            )

        if ip.is_loopback:
            if not self._config.browser_allow_localhost:
                raise BrowserSecurityError(
                    f"SSRF defense: access to loopback IP '{ip}' is blocked by default."
                )
            return

        if ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            if not self._config.browser_allow_private_networks:
                raise BrowserSecurityError(
                    f"SSRF defense: access to private/link-local/reserved network IP '{ip}' is blocked."
                )

    def _validate_domain_policy(self, hostname: str) -> None:
        """Validate hostname against configured allowed_domains and blocked_domains.

        Uses strict exact or hierarchical subdomain matching.
        NEVER uses substring matching.
        """
        # Blocklist check first
        for blocked in self._config.browser_blocked_domains:
            blocked_clean = blocked.lower().strip()
            if self._domain_matches(hostname, blocked_clean):
                raise BrowserSecurityError(
                    f"Domain '{hostname}' is blocked by browser domain policy (matched '{blocked}')."
                )

        # Allowlist check (if allowlist is populated)
        if self._config.browser_allowed_domains:
            matched = False
            for allowed in self._config.browser_allowed_domains:
                allowed_clean = allowed.lower().strip()
                if self._domain_matches(hostname, allowed_clean):
                    matched = True
                    break
            if not matched:
                raise BrowserSecurityError(
                    f"Domain '{hostname}' is not in the browser allowed domains list."
                )

    def _domain_matches(self, hostname: str, rule: str) -> bool:
        """Strict domain match check.

        Matches exact domain or subdomains.
        Example rule 'example.com':
          - 'example.com' -> True
          - 'api.example.com' -> True
          - 'evil-example.com' -> False
          - 'notexample.com' -> False
        """
        if rule.startswith("*."):
            rule = rule[2:]

        if hostname == rule:
            return True

        if hostname.endswith("." + rule):
            return True

        return False

    def _validate_resolved_dns(self, hostname: str) -> None:
        """Resolve hostname and check if resolved IPs target private/loopback/metadata."""
        # Special case localhost string
        if hostname == "localhost":
            if not self._config.browser_allow_localhost:
                raise BrowserSecurityError(
                    f"SSRF defense: access to '{hostname}' is blocked by default."
                )
            return

        try:
            # Force IPv4 socket resolution or standard resolution
            addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            for family, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                ip_obj = ipaddress.ip_address(ip_str)

                # RFC 6052 Well-Known NAT64 Prefix (64:ff9b::/96) translation
                if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj in ipaddress.IPv6Network("64:ff9b::/96"):
                    ip_obj = ipaddress.IPv4Address(ip_obj.packed[-4:])

                if str(ip_obj) in CLOUD_METADATA_IPS:
                    raise BrowserSecurityError(
                        f"SSRF defense: '{hostname}' resolved to cloud metadata IP '{ip_obj}'."
                    )

                if ip_obj.is_loopback:
                    if not self._config.browser_allow_localhost:
                        raise BrowserSecurityError(
                            f"SSRF defense: '{hostname}' resolved to loopback IP '{ip_obj}'."
                        )
                    continue

                if (ip_obj.is_private or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_unspecified) and not self._config.browser_allow_private_networks:
                    raise BrowserSecurityError(
                        f"SSRF defense: '{hostname}' resolved to private network IP '{ip_obj}'."
                    )
        except (socket.gaierror, OSError) as e:
            logger.debug("DNS resolution for '%s' failed during policy check: %s", hostname, e)
            # If DNS fails here, it might be an internal test hostname or offline mock;
            # allow standard Playwright to attempt navigation or fail with navigation error

    def validate_redirect(self, from_url: str, to_url: str, redirect_count: int = 1) -> str:
        """Re-validate destination URL after an HTTP redirect and enforce max_navigation_redirects limit.

        Never inherits trust from the origin URL.
        """
        logger.info("Re-evaluating redirect #%d from '%s' to '%s'", redirect_count, from_url, to_url)
        max_redirects = self._config.max_navigation_redirects
        if redirect_count > max_redirects:
            raise BrowserSecurityError(
                f"Redirect chain limit exceeded: reached {redirect_count} redirects, maximum allowed is {max_redirects}."
            )
        return self.validate_url(to_url)
