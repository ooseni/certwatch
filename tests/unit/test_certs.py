"""The certificate reader and its SSRF guard.

The handshakes here are real: each test starts a TLS server on the loopback interface with a
certificate generated for the case at hand, so the parsing, the timeouts and the "read an expired
certificate instead of refusing it" behaviour are exercised rather than mocked. No test touches
the network. The guard blocks loopback addresses, so these tests call read_certificate with an
already-vetted address, which is how certs.inspect calls it too.
"""

import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from certwatch import certs

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def make_certificate(tmp_path, common_name="localhost", starts=-1, expires=90, key=None):
    """A self-signed certificate valid from `starts` to `expires` days from NOW, as (cert, key) files."""
    key = key or ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, common_name)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(0x2A)
        .not_valid_before(datetime.now(UTC).replace(tzinfo=None) + timedelta(days=starts))
        .not_valid_after(datetime.now(UTC).replace(tzinfo=None) + timedelta(days=expires))
        .sign(key, hashes.SHA256())
    )
    cert_file = tmp_path / f"{common_name}-{starts}-{expires}.pem"
    key_file = tmp_path / f"{common_name}-{starts}-{expires}.key"
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_file, key_file


class Listener:
    """A socket on 127.0.0.1 that serves `handle` once per connection, in a background thread."""

    def __init__(self, handle):
        self._handle = handle
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(5)
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def address(self) -> tuple[int, tuple]:
        return socket.AF_INET, self._socket.getsockname()

    def _serve(self):
        while not self._stop:
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            try:
                self._handle(connection)
            except OSError:
                pass
            finally:
                connection.close()

    def close(self):
        self._stop = True
        self._socket.close()
        self._thread.join(timeout=2)


@pytest.fixture
def tls_server(tmp_path):
    """Starts TLS servers for the certificate files given to it; all are closed afterwards."""
    listeners = []

    def start(cert_file, key_file):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_file, key_file)

        def handle(connection):
            with context.wrap_socket(connection, server_side=True) as tls:
                tls.recv(1)

        listener = Listener(handle)
        listeners.append(listener)
        return listener

    yield start
    for listener in listeners:
        listener.close()


def read(listener, host="localhost", timeout=5.0):
    family, sockaddr = listener.address
    return certs.read_certificate(host, sockaddr[1], family, sockaddr, timeout)


# --- the SSRF guard ---------------------------------------------------------------------------

BLOCKED = [
    ("10.0.0.1", "private"),
    ("172.16.31.9", "private"),
    ("192.168.1.1", "private"),
    ("127.0.0.1", "loopback"),
    ("127.1.2.3", "loopback"),
    ("169.254.169.254", "link-local"),  # the EC2 instance metadata service
    ("100.64.0.1", "not a globally routable"),  # carrier-grade NAT: neither private nor global
    ("192.0.0.1", "private"),
    ("198.18.0.5", "private"),  # benchmarking range
    ("0.0.0.0", "private"),  # noqa: S104 -- an address the guard must refuse, not one we bind
    ("224.0.0.1", "multicast"),
    ("239.255.255.250", "multicast"),
    ("240.0.0.1", "private"),
    ("255.255.255.255", "private"),
    ("::1", "loopback"),
    ("fe80::1", "link-local"),
    ("fc00::1", "private"),
    ("::", "private"),
    ("ff02::1", "multicast"),
    ("::ffff:127.0.0.1", "loopback"),  # IPv4-mapped loopback
    ("::ffff:10.0.0.1", "private"),  # IPv4-mapped private
    ("2002:7f00:1::", "private"),  # 6to4 wrapping 127.0.0.1
    ("2001:0:4136:e378:8000:63bf:3fff:fdd2", "private"),  # Teredo
]


@pytest.mark.parametrize(("address", "reason"), BLOCKED)
def test_non_public_addresses_are_refused(address, reason):
    import ipaddress

    why = certs._why_not_public(ipaddress.ip_address(address))

    assert why is not None, f"{address} should not be treated as public"
    assert reason in why


@pytest.mark.parametrize(
    "address",
    ["93.184.216.34", "1.1.1.1", "8.8.8.8", "2606:2800:220:1:248:1893:25c8:1946", "2a00:1450:4009:81f::200e"],
)
def test_public_addresses_are_allowed(address):
    import ipaddress

    assert certs._why_not_public(ipaddress.ip_address(address)) is None


def addrinfo(*addresses):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]


def test_resolving_returns_every_public_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: addrinfo("93.184.216.34", "1.1.1.1"))

    addresses = certs.resolve_public_addresses("example.com", 443)

    assert [sockaddr[0] for _family, sockaddr in addresses] == ["93.184.216.34", "1.1.1.1"]


def test_one_internal_answer_blocks_the_whole_name(monkeypatch):
    """A name resolving to a public and a private address is a rebinding attempt, not a host."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: addrinfo("93.184.216.34", "10.0.0.1"))

    with pytest.raises(certs.BlockedAddress, match="10.0.0.1"):
        certs.resolve_public_addresses("sneaky.example.com", 443)


def test_a_name_that_does_not_resolve_is_unresolvable(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", fail)

    with pytest.raises(certs.Unresolvable):
        certs.resolve_public_addresses("nope.example.com", 443)


def test_an_empty_dns_answer_is_unresolvable(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])

    with pytest.raises(certs.Unresolvable):
        certs.resolve_public_addresses("empty.example.com", 443)


def test_blocked_and_failed_checks_carry_their_status():
    assert certs.BlockedAddress.status == "blocked"
    assert certs.Unresolvable.status == "unresolvable"
    assert certs.Unreachable.status == "unreachable"
    assert certs.HandshakeFailed.status == "handshake_failed"
    assert issubclass(certs.BlockedAddress, certs.CheckError)


# --- reading a certificate -------------------------------------------------------------------


def test_a_valid_certificate_is_described(tmp_path, tls_server):
    listener = tls_server(*make_certificate(tmp_path, "good.example.com", expires=90))

    described = read(listener, host="good.example.com")

    assert described["subject"] == "good.example.com"
    assert described["issuer"] == "good.example.com"  # self-signed
    assert described["serial"] == "2a"
    assert described["key_type"] == "EC-secp256r1"
    expires_at = datetime.fromisoformat(described["expires_at"])
    assert expires_at.tzinfo is not None
    assert 88 <= (expires_at - datetime.now(UTC)).days <= 90


def test_an_expired_certificate_is_still_read(tmp_path, tls_server):
    """The whole point: a verifying handshake would fail here, and the alert would never be sent."""
    listener = tls_server(*make_certificate(tmp_path, "old.example.com", starts=-400, expires=-30))

    described = read(listener, host="old.example.com")

    assert datetime.fromisoformat(described["expires_at"]) < datetime.now(UTC)
    assert certs.status_for(described, alert_days=30) == (certs.EXPIRED, -31)


def test_an_rsa_key_is_described(tmp_path, tls_server):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    listener = tls_server(*make_certificate(tmp_path, "rsa.example.com", key=key))

    assert read(listener, host="rsa.example.com")["key_type"] == "RSA-2048"


def test_a_closed_port_is_unreachable():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    sockaddr = probe.getsockname()
    probe.close()  # nothing is listening on this port now

    with pytest.raises(certs.Unreachable):
        certs.read_certificate("example.com", sockaddr[1], socket.AF_INET, sockaddr, 2.0)


def test_a_host_that_never_completes_the_handshake_times_out():
    listener = Listener(lambda connection: threading.Event().wait(5))
    try:
        with pytest.raises(certs.Unreachable, match="within 0.3s"):
            read(listener, timeout=0.3)
    finally:
        listener.close()


def test_a_port_that_is_not_tls_fails_the_handshake():
    listener = Listener(lambda connection: connection.sendall(b"220 smtp ready\r\n"))
    try:
        with pytest.raises(certs.HandshakeFailed):
            read(listener, timeout=2.0)
    finally:
        listener.close()


def test_a_certificate_that_cannot_be_parsed_fails_the_handshake():
    with pytest.raises(certs.HandshakeFailed, match="could not be parsed"):
        certs.describe(b"not a certificate")


def test_inspect_falls_back_to_the_next_address(monkeypatch, tmp_path, tls_server):
    listener = tls_server(*make_certificate(tmp_path, "two.example.com"))
    _family, working = listener.address
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    broken = dead.getsockname()
    dead.close()
    monkeypatch.setattr(
        certs,
        "resolve_public_addresses",
        lambda host, port: [(socket.AF_INET, broken), (socket.AF_INET, working)],
    )

    assert certs.inspect("two.example.com", working[1], timeout=2.0)["subject"] == "two.example.com"


def test_inspect_reports_the_last_failure_when_no_address_works(monkeypatch):
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    broken = dead.getsockname()
    dead.close()
    monkeypatch.setattr(certs, "resolve_public_addresses", lambda host, port: [(socket.AF_INET, broken)] * 2)

    with pytest.raises(certs.Unreachable):
        certs.inspect("dead.example.com", broken[1], timeout=2.0)


def test_inspect_does_not_swallow_a_blocked_address(monkeypatch):
    def blocked(host, port):
        raise certs.BlockedAddress("nope")

    monkeypatch.setattr(certs, "resolve_public_addresses", blocked)

    with pytest.raises(certs.BlockedAddress):
        certs.inspect("internal.example.com")


# --- turning a certificate into a status ------------------------------------------------------


def certificate(expires_in_days, starts_in_days=-1):
    return {
        "expires_at": (NOW + timedelta(days=expires_in_days)).isoformat(timespec="seconds"),
        "starts_at": (NOW + timedelta(days=starts_in_days)).isoformat(timespec="seconds"),
    }


@pytest.mark.parametrize(
    ("expires_in_days", "alert_days", "status", "days_remaining"),
    [
        (90, 30, certs.OK, 90),
        (31, 30, certs.OK, 31),
        (30, 30, certs.EXPIRING, 30),  # the window is inclusive
        (1, 30, certs.EXPIRING, 1),
        (0, 30, certs.EXPIRED, 0),  # expires exactly now
        (-5, 30, certs.EXPIRED, -5),
        (365, 365, certs.EXPIRING, 365),
        (2, 1, certs.OK, 2),
    ],
)
def test_status_follows_the_alert_window(expires_in_days, alert_days, status, days_remaining):
    assert certs.status_for(certificate(expires_in_days), alert_days, NOW) == (status, days_remaining)


def test_part_of_a_day_left_counts_as_zero_days_and_still_alerts():
    almost = {
        "expires_at": (NOW + timedelta(hours=23)).isoformat(timespec="seconds"),
        "starts_at": (NOW - timedelta(days=1)).isoformat(timespec="seconds"),
    }

    assert certs.status_for(almost, 14, NOW) == (certs.EXPIRING, 0)


def test_a_certificate_that_is_not_valid_yet_is_reported():
    future = certificate(expires_in_days=90, starts_in_days=2)

    assert certs.status_for(future, 30, NOW) == (certs.NOT_YET_VALID, 90)


def test_status_defaults_to_the_current_time():
    status, _days = certs.status_for(
        {
            "expires_at": (datetime.now(UTC) + timedelta(days=200)).isoformat(),
            "starts_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        },
        30,
    )

    assert status == certs.OK
