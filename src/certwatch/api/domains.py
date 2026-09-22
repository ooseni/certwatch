"""/domains: register, list, read, update and remove the domains CertWatch monitors.

Routes (HTTP API, payload v2):
    POST   /domains                  201  register a domain
    GET    /domains?limit=&next_token=  200  one page of registered domains
    GET    /domains/{domain}         200  one domain
    PATCH  /domains/{domain}         200  change port and/or alert_days
    DELETE /domains/{domain}         204  stop monitoring a domain
"""

import logging
from urllib.parse import quote

from certwatch.http import error_response, json_response, no_content
from certwatch.store import DomainExists, DomainNotFound, DomainStore, InvalidPageToken
from certwatch.validation import (
    ValidationError,
    normalise_domain,
    parse_changes,
    parse_limit,
    parse_new_domain,
    read_json_body,
)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

logger = logging.getLogger(__name__)
_store: DomainStore | None = None


def store() -> DomainStore:
    """Created on first use and reused while the Lambda execution environment stays warm."""
    global _store
    if _store is None:
        _store = DomainStore.from_env()
    return _store


def create_domain(event: dict) -> dict:
    item = parse_new_domain(read_json_body(event))
    record = store().create(item)
    logger.info("domain registered", extra={"domain": record["domain"]})
    return json_response(201, record, headers={"Location": f"/domains/{quote(record['domain'])}"})


def list_domains(event: dict) -> dict:
    query = event.get("queryStringParameters") or {}
    limit = parse_limit(query.get("limit"), DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    items, next_token = store().list(limit, query.get("next_token"))
    return json_response(200, {"items": items, "next_token": next_token})


def get_domain(event: dict) -> dict:
    domain = _path_domain(event)
    item = store().get(domain)
    if item is None:
        raise DomainNotFound(domain)
    return json_response(200, item)


def update_domain(event: dict) -> dict:
    domain = _path_domain(event)
    changes = parse_changes(read_json_body(event))
    record = store().update(domain, changes)
    logger.info("domain updated", extra={"domain": domain, "fields": sorted(changes)})
    return json_response(200, record)


def delete_domain(event: dict) -> dict:
    domain = _path_domain(event)
    store().delete(domain)
    logger.info("domain removed", extra={"domain": domain})
    return no_content()


ROUTES = {
    "POST /domains": create_domain,
    "GET /domains": list_domains,
    "GET /domains/{domain}": get_domain,
    "PATCH /domains/{domain}": update_domain,
    "DELETE /domains/{domain}": delete_domain,
}


def handler(event, context):
    route = ROUTES.get(event.get("routeKey", ""))
    if route is None:
        return error_response(404, "not_found", "no such route")
    try:
        return route(event)
    except ValidationError as exc:
        return error_response(400, "validation_error", str(exc))
    except InvalidPageToken:
        return error_response(400, "validation_error", "next_token is not valid")
    except DomainNotFound:
        return error_response(404, "not_found", "domain is not registered")
    except DomainExists:
        return error_response(409, "already_exists", "domain is already registered")
    except Exception:
        # log the full traceback for CloudWatch, but never leak internals to the client
        logger.exception("unhandled error", extra={"route": event.get("routeKey")})
        return error_response(500, "internal_error", "something went wrong")


def _path_domain(event: dict) -> str:
    return normalise_domain((event.get("pathParameters") or {}).get("domain"))
