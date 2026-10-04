"""The daily check run: what it stores, what it alerts on, and what it survives.

The certificate reader is stubbed here -- certs.inspect has its own tests against real handshakes
in test_certs.py -- so these tests are about the run itself: results written back, the digest, and
a run that keeps going when one domain misbehaves.
"""

from datetime import UTC, datetime, timedelta

import pytest

from certwatch import certs, checker
from certwatch.store import DomainNotFound

NOW = datetime(2026, 10, 4, 7, 0, tzinfo=UTC)


def certificate(expires_in_days, starts_in_days=-10, issuer="Test CA"):
    return {
        "expires_at": (NOW + timedelta(days=expires_in_days)).isoformat(timespec="seconds"),
        "starts_at": (NOW + timedelta(days=starts_in_days)).isoformat(timespec="seconds"),
        "issuer": issuer,
        "subject": "subject.example.com",
        "serial": "2a",
        "key_type": "EC-secp256r1",  # gitleaks:allow -- a curve name, not a key
    }


class FakeStore:
    """Stands in for DomainStore: hands out items and remembers what was written back."""

    def __init__(self, items, deleted_mid_run=()):
        self.items = items
        self.written = {}
        self.deleted_mid_run = set(deleted_mid_run)

    def iter_all(self):
        yield from self.items

    def record_check(self, domain, fields):
        if domain in self.deleted_mid_run:
            raise DomainNotFound(domain)
        self.written[domain] = fields


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def __call__(self, subject, message):
        self.sent.append((subject, message))


@pytest.fixture
def notifier():
    return FakeNotifier()


def inspector(monkeypatch, results):
    """Stub certs.inspect: `results` maps a domain to a certificate dict or an exception to raise."""
    calls = []

    def inspect(host, port=443, timeout=certs.DEFAULT_TIMEOUT):
        calls.append((host, port, timeout))
        outcome = results[host]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(certs, "inspect", inspect)
    return calls


def run(store, notifier, timeout=5.0):
    return checker.run(store, notifier, timeout=timeout, now=NOW, stage="dev")


def test_a_healthy_domain_is_recorded_and_not_alerted(monkeypatch, notifier):
    inspector(monkeypatch, {"good.example.com": certificate(90)})
    store = FakeStore([{"domain": "good.example.com", "port": 443, "alert_days": 30}])

    summary = run(store, notifier)

    assert notifier.sent == []
    assert summary == {"checked": 1, "alerted": 0, "by_status": {"ok": 1}}
    written = store.written["good.example.com"]
    assert written["last_status"] == "ok"
    assert written["last_checked_at"] == "2026-10-04T07:00:00+00:00"
    assert written["days_remaining"] == 90
    assert written["issuer"] == "Test CA"
    assert written["last_error"] is None, "a successful check clears any previous error"


def test_a_domain_inside_its_alert_window_is_alerted(monkeypatch, notifier):
    inspector(monkeypatch, {"soon.example.com": certificate(6)})
    store = FakeStore([{"domain": "soon.example.com", "port": 8443, "alert_days": 14}])

    summary = run(store, notifier)

    assert summary["alerted"] == 1
    ((subject, body),) = notifier.sent
    assert subject == "CertWatch dev: 1 certificate need attention"
    assert "soon.example.com:8443" in body
    assert "EXPIRING" in body
    assert "6 day(s) left" in body
    assert "alert window 14 day(s)" in body
    assert store.written["soon.example.com"]["last_status"] == "expiring"


def test_the_digest_reports_the_worst_first(monkeypatch, notifier):
    inspector(
        monkeypatch,
        {
            "expiring.example.com": certificate(5),
            "expired.example.com": certificate(-2),
            "broken.example.com": certs.Unreachable("could not connect"),
            "fine.example.com": certificate(200),
        },
    )
    store = FakeStore(
        [
            {"domain": "expiring.example.com", "alert_days": 30},
            {"domain": "broken.example.com"},
            {"domain": "expired.example.com"},
            {"domain": "fine.example.com"},
        ]
    )

    run(store, notifier)

    ((_subject, body),) = notifier.sent
    order = [line.split()[0] for line in body.splitlines() if line.startswith("  ")]
    assert order == ["EXPIRED", "EXPIRING", "UNREACHABLE"]
    assert "The other 1 are valid and outside their alert window." in body
    assert "fine.example.com" not in body


def test_a_failed_check_keeps_the_last_known_expiry_and_records_why(monkeypatch, notifier):
    inspector(monkeypatch, {"gone.example.com": certs.Unreachable("no answer within 5s")})
    store = FakeStore([{"domain": "gone.example.com", "expires_at": "2027-01-01T00:00:00+00:00"}])

    run(store, notifier)

    written = store.written["gone.example.com"]
    assert written["last_status"] == "unreachable"
    assert written["last_error"] == "no answer within 5s"
    assert "expires_at" not in written, "a failed check must not erase the expiry it knew"
    assert "days_remaining" not in written


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (certs.BlockedAddress("resolves to 10.0.0.1, a private address"), "blocked"),
        (certs.Unresolvable("no DNS answer"), "unresolvable"),
        (certs.Unreachable("connection refused"), "unreachable"),
        (certs.HandshakeFailed("no certificate"), "handshake_failed"),
    ],
)
def test_every_kind_of_failure_is_stored_and_alerted(monkeypatch, notifier, failure, status):
    inspector(monkeypatch, {"bad.example.com": failure})
    store = FakeStore([{"domain": "bad.example.com"}])

    summary = run(store, notifier)

    assert summary == {"checked": 1, "alerted": 1, "by_status": {status: 1}}
    assert store.written["bad.example.com"]["last_status"] == status
    assert str(failure) in notifier.sent[0][1]


def test_an_unexpected_error_does_not_cost_the_other_domains_their_check(monkeypatch, notifier):
    inspector(
        monkeypatch,
        {
            "boom.example.com": RuntimeError("something nobody predicted"),
            "good.example.com": certificate(90),
        },
    )
    store = FakeStore([{"domain": "boom.example.com"}, {"domain": "good.example.com"}])

    summary = run(store, notifier)

    assert summary["checked"] == 2
    assert store.written["boom.example.com"]["last_status"] == "check_failed"
    assert store.written["good.example.com"]["last_status"] == "ok"
    assert "RuntimeError: something nobody predicted" in notifier.sent[0][1]


def test_a_domain_deleted_mid_run_is_not_recreated(monkeypatch, notifier):
    inspector(monkeypatch, {"going.example.com": certificate(90), "staying.example.com": certificate(90)})
    store = FakeStore(
        [{"domain": "going.example.com"}, {"domain": "staying.example.com"}],
        deleted_mid_run={"going.example.com"},
    )

    summary = run(store, notifier)

    assert summary["checked"] == 2
    assert set(store.written) == {"staying.example.com"}


def test_the_item_supplies_the_port_window_and_the_run_supplies_the_timeout(monkeypatch, notifier):
    calls = inspector(monkeypatch, {"custom.example.com": certificate(10)})
    store = FakeStore([{"domain": "custom.example.com", "port": 8443, "alert_days": 15}])

    run(store, notifier, timeout=2.5)

    assert calls == [("custom.example.com", 8443, 2.5)]
    assert store.written["custom.example.com"]["last_status"] == "expiring"


def test_missing_port_and_window_fall_back_to_the_registration_defaults(monkeypatch, notifier):
    calls = inspector(monkeypatch, {"bare.example.com": certificate(20)})

    run(FakeStore([{"domain": "bare.example.com"}]), notifier)

    assert calls == [("bare.example.com", 443, 5.0)]


def test_numbers_that_came_back_from_dynamodb_as_decimals_are_usable(monkeypatch, notifier):
    from decimal import Decimal

    calls = inspector(monkeypatch, {"decimal.example.com": certificate(20)})
    store = FakeStore(
        [{"domain": "decimal.example.com", "port": Decimal("8443"), "alert_days": Decimal("30")}]
    )

    run(store, notifier)

    assert calls == [("decimal.example.com", 8443, 5.0)]
    assert store.written["decimal.example.com"]["last_status"] == "expiring"


def test_an_empty_table_checks_nothing_and_sends_nothing(notifier):
    summary = run(FakeStore([]), notifier)

    assert summary == {"checked": 0, "alerted": 0, "by_status": {}}
    assert notifier.sent == []


def test_the_summary_counts_every_status(monkeypatch, notifier):
    inspector(
        monkeypatch,
        {
            "a.example.com": certificate(90),
            "b.example.com": certificate(90),
            "c.example.com": certificate(3),
            "d.example.com": certs.Unreachable("down"),
        },
    )
    store = FakeStore([{"domain": f"{letter}.example.com"} for letter in "abcd"])

    summary = run(store, notifier)

    assert summary == {
        "checked": 4,
        "alerted": 2,
        "by_status": {"expiring": 1, "ok": 2, "unreachable": 1},
    }


def test_the_digest_omits_the_healthy_line_when_nothing_is_healthy(monkeypatch, notifier):
    inspector(monkeypatch, {"only.example.com": certificate(1)})

    run(FakeStore([{"domain": "only.example.com"}]), notifier)

    assert "outside their alert window" not in notifier.sent[0][1]


def test_the_subject_is_a_single_line_within_the_sns_limit():
    many = [{"status": "expiring", "domain": f"d{n}.example.com"} for n in range(500)]

    subject = checker.alert_subject(many, "production")

    assert len(subject) <= 100
    assert "\n" not in subject
    assert subject.isascii()
    assert "500 certificates need attention" in subject


def test_a_not_yet_valid_certificate_is_explained(monkeypatch, notifier):
    inspector(monkeypatch, {"early.example.com": certificate(90, starts_in_days=3)})

    run(FakeStore([{"domain": "early.example.com"}]), notifier)

    assert "NOT_YET_VALID" in notifier.sent[0][1]
    assert "start date is in the future" in notifier.sent[0][1]


def test_the_handler_reads_its_settings_from_the_environment(monkeypatch):
    monkeypatch.setenv("STAGE", "prod")
    monkeypatch.setenv("CHECK_TIMEOUT_SECONDS", "1.5")
    calls = inspector(monkeypatch, {"env.example.com": certificate(2)})
    store = FakeStore([{"domain": "env.example.com"}])
    sent = []
    monkeypatch.setattr(checker, "store", lambda: store)
    monkeypatch.setattr(checker, "publish", lambda subject, message: sent.append(subject))

    summary = checker.handler({}, None)

    assert summary["alerted"] == 1
    assert calls == [("env.example.com", 443, 1.5)]
    assert sent == ["CertWatch prod: 1 certificate need attention"]


def test_the_handler_defaults_the_timeout_and_the_stage(monkeypatch):
    monkeypatch.delenv("STAGE", raising=False)
    monkeypatch.delenv("CHECK_TIMEOUT_SECONDS", raising=False)
    calls = inspector(monkeypatch, {"plain.example.com": certificate(1)})
    sent = []
    monkeypatch.setattr(checker, "store", lambda: FakeStore([{"domain": "plain.example.com"}]))
    monkeypatch.setattr(checker, "publish", lambda subject, message: sent.append(subject))

    checker.handler({}, None)

    assert calls == [("plain.example.com", 443, certs.DEFAULT_TIMEOUT)]
    assert sent == ["CertWatch local: 1 certificate need attention"]
