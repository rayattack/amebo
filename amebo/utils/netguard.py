"""SSRF guard for user-supplied webhook URLs.

Amebo's whole job is POSTing event payloads to URLs that applications register
(an application's ``address``). When subscribers are *untrusted third parties*
(a multi-tenant, internet-facing broker), an application could point delivery at
internal-only services — loopback, RFC-1918 ranges, or the cloud metadata
endpoint (169.254.169.254) — turning the broker into an SSRF proxy that can
exfiltrate IAM credentials or reach admin interfaces.

But the common self-hosted topology is the opposite: Amebo co-located with the
app it serves, deliberately delivering over ``localhost`` or an internal/Docker
hostname. There, a private target is the point, not an attack.

So the default is **allow** (don't break the trusted self-hosted case), and strict
blocking is **opt-in** for operators who accept untrusted subscriber URLs:

    AMEBO_BLOCK_PRIVATE_WEBHOOKS=1   # reject non-routable delivery targets

When strict mode is on, ``validate_webhook_url`` rejects non-http(s) schemes and
any URL whose hostname resolves to a non-publicly-routable address. It is enforced
where the URL *enters* the system (application provisioning / address update) so a
bad address is rejected up front with clear feedback — not on the hot delivery path.

Residual risk (strict mode): a host that resolves to a public IP at registration
time but a private one at delivery time (DNS rebinding) is not caught here. Pinning
the delivered-to IP to a validated address would close that gap and is tracked
separately.
"""
import ipaddress
import socket
from os import environ
from urllib.parse import urlparse


def strict_mode() -> bool:
    """True when the operator has opted into blocking non-routable delivery targets.

    Off by default: a self-hosted, single-tenant bus typically delivers to
    localhost/internal hosts on purpose. Turn on for multi-tenant / public
    deployments that accept untrusted subscriber URLs.
    """
    return environ.get('AMEBO_BLOCK_PRIVATE_WEBHOOKS', '').strip().lower() in ('1', 'true', 'yes', 'on')


def _ip_is_blocked(ip_str: str) -> bool:
    """True if the address is not safe to deliver to (loopback, private,
    link-local incl. cloud metadata, reserved, multicast, unspecified)."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local   # 169.254.0.0/16 — covers the cloud metadata endpoint
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def validate_webhook_url(url) -> "tuple[bool, str | None]":
    """Return ``(ok, reason)``. ``ok`` is False with a human-readable ``reason``
    when the URL is unsafe to register as a delivery target.

    A no-op (always ``(True, None)``) unless :func:`strict_mode` is enabled.
    """
    if not strict_mode():
        return True, None

    try:
        parsed = urlparse(str(url))
    except Exception:
        return False, 'malformed URL'

    if parsed.scheme not in ('http', 'https'):
        return False, 'URL scheme must be http or https'

    host = parsed.hostname
    if not host:
        return False, 'URL has no host'

    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except Exception:
        return False, f'could not resolve host {host!r}'

    # Reject if ANY resolved address is non-public — an attacker who controls a
    # multi-record domain can't slip a private IP past us behind a public one.
    for info in infos:
        ip = info[4][0]
        if _ip_is_blocked(ip):
            return False, f'address {ip} (for host {host!r}) is not publicly routable'

    return True, None
