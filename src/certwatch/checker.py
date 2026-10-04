"""The daily certificate check: read every registered domain, store the result, alert through SNS.

EventBridge Scheduler invokes this once a day (see template.yaml). Domains are checked one after
another, which keeps the moving parts down and is well inside Lambda's limit for the numbers this
service is built for; see docs/decisions/0005-*.md for when that stops being true.

One run sends at most one email: a digest of everything that needs attention. A domain inside its
alert window is reported on every run until it is renewed, which is the point of the service.
"""

import logging
import os
from datetime import UTC, datetime

import boto3

from certwatch import certs
from certwatch.store import DomainNotFound, DomainStore
from certwatch.validation import DEFAULT_ALERT_DAYS, DEFAULT_PORT

logger = logging.getLogger(__name__)

_store: DomainStore | None = None
_sns = None


def store() -> DomainStore:
    """Created on first use and reused while the Lambda execution environment stays warm."""
    global _store
    if _store is None:
        _store = DomainStore.from_env()
    return _store


def publish(subject: str, message: str) -> None:
    global _sns
    if _sns is None:
        _sns = boto3.client("sns")
    _sns.publish(TopicArn=os.environ["ALERTS_TOPIC_ARN"], Subject=subject, Message=message)


def check_domain(item: dict, timeout: float, now: datetime) -> dict:
    """One domain's result. Never raises: a domain that cannot be checked is a result too."""
    domain = item["domain"]
    port = int(item.get("port") or DEFAULT_PORT)
    alert_days = int(item.get("alert_days") or DEFAULT_ALERT_DAYS)
    base = {"domain": domain, "port": port, "alert_days": alert_days}
    try:
        certificate = certs.inspect(domain, port, timeout)
    except certs.CheckError as exc:
        return base | {"status": exc.status, "detail": str(exc)}
    except Exception as exc:
        # one unexpected failure must not cost every other domain its check
        logger.exception("unexpected failure checking a domain", extra={"domain": domain})
        return base | {"status": certs.CheckError.status, "detail": f"{type(exc).__name__}: {exc}"}
    status, days_remaining = certs.status_for(certificate, alert_days, now)
    return base | {
        "status": status,
        "days_remaining": days_remaining,
        "detail": _expiry_detail(status, certificate, days_remaining, alert_days),
        "certificate": certificate,
    }


def fields_for(result: dict, now: datetime) -> dict:
    """The item attributes a result writes back. A value of None removes the attribute.

    A failed check keeps whatever expiry was last known -- stale information about a host that is
    briefly unreachable is more useful than none -- and records why the check failed.
    """
    checked = {"last_checked_at": now.isoformat(timespec="seconds"), "last_status": result["status"]}
    if "certificate" not in result:
        return checked | {"last_error": result["detail"]}
    certificate = result["certificate"]
    return checked | {
        "expires_at": certificate["expires_at"],
        "days_remaining": result["days_remaining"],
        "issuer": certificate["issuer"],
        "last_error": None,
    }


def run(domains: DomainStore, notify, timeout: float, now: datetime, stage: str) -> dict:
    """Check every registered domain, store each result, and send one digest if anything is wrong."""
    results = []
    for item in domains.iter_all():
        result = check_domain(item, timeout, now)
        results.append(result)
        logger.info(
            "domain checked",
            extra={"domain": result["domain"], "status": result["status"], "detail": result["detail"]},
        )
        try:
            domains.record_check(result["domain"], fields_for(result, now))
        except DomainNotFound:
            logger.info("domain removed mid-run; result discarded", extra={"domain": result["domain"]})

    alerts = [result for result in results if result["status"] != certs.OK]
    if alerts:
        notify(alert_subject(alerts, stage), alert_body(results, alerts, now, stage))
    summary = {
        "checked": len(results),
        "alerted": len(alerts),
        "by_status": _counts(results),
    }
    logger.info("check run finished", extra=summary)
    return summary


def alert_subject(alerts: list[dict], stage: str) -> str:
    """A one-line SNS subject: ASCII, no newlines, within the 100-character limit."""
    noun = "certificate" if len(alerts) == 1 else "certificates"
    return f"CertWatch {stage}: {len(alerts)} {noun} need attention"[:100]


def alert_body(results: list[dict], alerts: list[dict], now: datetime, stage: str) -> str:
    """The digest email: one line per domain that needs attention, worst first."""
    width = max(len(result["status"]) for result in alerts)
    lines = [
        f"CertWatch checked {len(results)} domain(s) in the {stage} stage "
        f"at {now.isoformat(timespec='seconds')}.",
        "",
        f"{len(alerts)} need attention:",
        "",
    ]
    lines += [
        f"  {result['status'].upper():<{width}}  {result['domain']}:{result['port']}  {result['detail']}"
        for result in sorted(alerts, key=_severity)
    ]
    healthy = len(results) - len(alerts)
    if healthy:
        lines += ["", f"The other {healthy} are valid and outside their alert window."]
    return "\n".join(lines)


def handler(event, context):
    timeout = float(os.environ.get("CHECK_TIMEOUT_SECONDS", certs.DEFAULT_TIMEOUT))
    return run(
        store(),
        publish,
        timeout=timeout,
        now=datetime.now(UTC),
        stage=os.environ.get("STAGE", "local"),
    )


# Worst first in the digest: things already broken, then things about to break, then failures.
_SEVERITY = {certs.EXPIRED: 0, certs.NOT_YET_VALID: 1, certs.EXPIRING: 2}


def _severity(result: dict) -> tuple[int, object]:
    status = result["status"]
    return _SEVERITY.get(status, 3), result.get("days_remaining", 0), result["domain"]


def _expiry_detail(status: str, certificate: dict, days_remaining: int, alert_days: int) -> str:
    expires_at = certificate["expires_at"]
    if status == certs.EXPIRED:
        return f"expired on {expires_at} ({abs(days_remaining)} day(s) ago)"
    if status == certs.NOT_YET_VALID:
        # the date that matters here is when it starts working, not when it expires
        return (
            f"not valid until {certificate['starts_at']}; "
            f"the certificate's start date is in the future (expires {expires_at})"
        )
    window = f", alert window {alert_days} day(s)" if status == certs.EXPIRING else ""
    return f"expires on {expires_at} ({days_remaining} day(s) left{window})"


def _counts(results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    return dict(sorted(counts.items()))
