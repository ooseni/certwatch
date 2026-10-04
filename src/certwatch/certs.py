"""Read a domain's TLS certificate, with an SSRF guard in front of every connection.

Registration already restricts domains to public DNS names (see certwatch.validation), but DNS
changes after registration and a name anyone can submit may come to resolve inward. So every
address is vetted again here, immediately before the socket is opened, and the connection is made
to the vetted address rather than to the name. See docs/decisions/0006-*.md.

Certificate verification is deliberately off: an expired certificate is exactly what this service
exists to report, and a verifying handshake would fail instead of handing it over. Nothing is
trusted because of the handshake -- the certificate is read, never acted on.
"""

import ipaddress
import socket
import ssl
from datetime import UTC, datetime

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec, rsa

DEFAULT_TIMEOUT = 5.0

# Statuses a check can end in. Everything but OK is worth an alert.
OK = "ok"
EXPIRING = "expiring"
EXPIRED = "expired"
NOT_YET_VALID = "not_yet_valid"


class CheckError(Exception):
    """A domain's certificate could not be read. The status reported for the domain."""

    status = "check_failed"


class BlockedAddress(CheckError):
    """The domain resolves to an address the checker must not connect to."""

    status = "blocked"


class Unresolvable(CheckError):
    """The domain has no DNS answer."""

    status = "unresolvable"


class Unreachable(CheckError):
    """The address refused the connection, or did not answer in time."""

    status = "unreachable"


class HandshakeFailed(CheckError):
    """The host answered but did not complete a TLS handshake, or sent no certificate."""

    status = "handshake_failed"


def resolve_public_addresses(host: str, port: int) -> list[tuple[int, tuple]]:
    """Every address `host` resolves to, as (family, sockaddr), when all of them are public.

    All or nothing on purpose: a name resolving to both a public and an internal address is a
    DNS-rebinding attempt, not a host to monitor, so one bad answer blocks the whole name.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise Unresolvable("the name could not be resolved") from exc
    addresses = []
    for family, _type, _proto, _canonname, sockaddr in infos:
        reason = _why_not_public(ipaddress.ip_address(sockaddr[0]))
        if reason:
            raise BlockedAddress(f"resolves to {sockaddr[0]}, {reason}")
        addresses.append((family, sockaddr))
    if not addresses:
        raise Unresolvable("the name could not be resolved")
    return addresses


def read_certificate(host: str, port: int, family: int, sockaddr: tuple, timeout: float) -> dict:
    """The certificate served at one already-vetted address, with SNI set to `host`."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Read, do not validate: see the module docstring. Both lines are required, and
    # check_hostname must be cleared first or assigning verify_mode raises.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            with context.wrap_socket(sock, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
    except TimeoutError as exc:
        raise Unreachable(f"no answer from {sockaddr[0]}:{port} within {timeout:g}s") from exc
    except ssl.SSLError as exc:
        raise HandshakeFailed(f"TLS handshake with {sockaddr[0]}:{port} failed: {exc.reason or exc}") from exc
    except OSError as exc:
        raise Unreachable(f"could not connect to {sockaddr[0]}:{port}: {exc.strerror or exc}") from exc
    if not der:
        raise HandshakeFailed(f"{sockaddr[0]}:{port} completed a handshake without a certificate")
    return describe(der)


def describe(der: bytes) -> dict:
    """The fields CertWatch stores about a certificate, from its DER bytes."""
    try:
        cert = x509.load_der_x509_certificate(der)
    except ValueError as exc:
        raise HandshakeFailed(f"the certificate could not be parsed: {exc}") from exc
    return {
        "expires_at": cert.not_valid_after_utc.isoformat(timespec="seconds"),
        "starts_at": cert.not_valid_before_utc.isoformat(timespec="seconds"),
        "issuer": _common_name(cert.issuer) or cert.issuer.rfc4514_string(),
        "subject": _common_name(cert.subject) or cert.subject.rfc4514_string(),
        "serial": format(cert.serial_number, "x"),
        "key_type": _key_description(cert),
    }


def inspect(host: str, port: int = 443, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Resolve, vet and read `host`'s certificate, trying each address it resolves to.

    Raises a CheckError subclass if no address yields a certificate; the last failure wins, so
    the reported status describes the address that got furthest.
    """
    failure: CheckError | None = None
    for family, sockaddr in resolve_public_addresses(host, port):
        try:
            return read_certificate(host, port, family, sockaddr, timeout)
        except CheckError as exc:
            failure = exc
    raise failure if failure else Unresolvable("the name could not be resolved")


def status_for(certificate: dict, alert_days: int, now: datetime | None = None) -> tuple[str, int]:
    """The status of a certificate and the whole days left before it expires (negative if past).

    Days are truncated towards zero, so a certificate with 23 hours left has 0 days left and a
    14-day alert window catches it.
    """
    now = now or datetime.now(UTC)
    expires_at = datetime.fromisoformat(certificate["expires_at"])
    starts_at = datetime.fromisoformat(certificate["starts_at"])
    days_remaining = (expires_at - now).days
    if expires_at <= now:
        return EXPIRED, days_remaining
    if starts_at > now:
        return NOT_YET_VALID, days_remaining
    if days_remaining <= alert_days:
        return EXPIRING, days_remaining
    return OK, days_remaining


def _why_not_public(address) -> str | None:
    """Why this address must not be connected to, or None if it is a public one.

    `is_global` is the test that matters: it is false for private, loopback, link-local,
    unspecified, reserved and shared (carrier-grade NAT) ranges, and for IPv6 forms that wrap an
    IPv4 address -- IPv4-mapped, 6to4 and Teredo -- which a blocklist of prefixes tends to miss.
    Multicast is the one exception: multicast addresses are global, and are not hosts.
    """
    if address.is_multicast:
        return "a multicast address"
    if address.is_loopback:
        return "a loopback address"
    if address.is_link_local:
        return "a link-local address"
    if address.is_private:
        return "a private address"
    if not address.is_global:
        return "not a globally routable address"
    return None


def _common_name(name: x509.Name) -> str | None:
    values = name.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    return str(values[0].value) if values else None


def _key_description(cert: x509.Certificate) -> str:
    key = cert.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        return f"RSA-{key.key_size}"
    if isinstance(key, ec.EllipticCurvePublicKey):
        return f"EC-{key.curve.name}"
    return type(key).__name__.removeprefix("_").removesuffix("PublicKey")
