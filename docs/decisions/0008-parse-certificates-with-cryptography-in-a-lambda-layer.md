---
status: "accepted"
date: 2026-10-04
decision-makers: Sakariyau Oseni (maintainer)
---

# Parse certificates with cryptography in a Lambda layer

> In the context of CertWatch, facing a checker that must report certificates which have already expired, we decided for cryptography shipped as a Lambda layer and neglected a verifying handshake with the standard library alone, hand-written DER parsing, shelling out to the openssl command, to achieve correctness, maintainability, cold-start cost, accepting that the service now carries a compiled dependency that has to be kept patched.

## Context and Problem Statement

Python's standard library returns a *parsed* certificate only when the handshake verified it, and an expired certificate fails verification. The one case CertWatch exists to report is therefore the one case a verifying handshake refuses to hand over. With verification turned off the peer certificate is available only as raw DER bytes, and the standard library has no X.509 parser to read `notAfter` out of them.

## Decision Drivers

* Correctness: an expired or not-yet-valid certificate must be read and reported, not skipped
* Maintainability: parsing attacker-supplied ASN.1 is not code this project should own
* Cost and cold start: the two API functions must not pay for a dependency they never use

## Considered Options

* cryptography, shipped as a Lambda layer
* cryptography, bundled into every function package
* Hand-written DER parsing in the standard library only
* Shelling out to `openssl s_client -dates`

## Decision Outcome

Chosen option: "cryptography, shipped as a Lambda layer", because it is the only option that reads an expired certificate correctly without this project owning an ASN.1 parser, and the layer keeps it off the functions that do not need it.

We will read the peer certificate with verification disabled, parse its DER bytes with `cryptography.x509`, and attach the library to the checker function alone as `CertificateParsingLayer`. Verification stays off deliberately: the certificate is read and reported, never trusted or acted on. Chain trust and hostname matching are out of scope for phase 3 and would need a second, verifying handshake.

### Consequences

* Good, because an expired certificate is reported with its real expiry date, which is the service's entire purpose
* Good, because the API function packages stay around 68 KB instead of 16 MB, so they build and cold-start as before
* Good, because `issuer`, `subject`, serial and key type come out of the same parse at no extra cost, and make the alert email useful
* Bad, because the project now has a compiled runtime dependency to track for CVEs, pinned by exact version
* Bad, because a layer is a second build artefact: `sam build` must produce both, and the layer's version has to be bumped to patch the library
* Bad, because turning verification off means a reader of the code must be told why, in the module and here

### Confirmation

Unit tests start a local TLS server with a deliberately expired certificate and assert the expiry is read rather than refused; an integration test registers `expired.badssl.com` and asserts the stored status is `expired` with `expires_at` in the past. `du -sh .aws-sam/build/*` shows the API functions under 100 KB and the 16 MB confined to the layer.

## Pros and Cons of the Options

### cryptography, shipped as a Lambda layer

Verification off, DER parsed by cryptography, library attached to the checker only

* Good, because it is the de facto standard X.509 library for Python, and abi3 manylinux wheels install without a compiler
* Good, because only the function that parses certificates carries the 16 MB
* Bad, because two build artefacts instead of one
* Bad, because a layer version has to be republished to patch the library

### cryptography, bundled into every function package

The same library, but in `src/requirements.txt`

* Good, because one build artefact and nothing new to understand
* Bad, because all three functions ship 16 MB, including two that never parse a certificate
* Bad, because it was measured to push LocalStack's CloudFormation Lambda creation past its 120-second resource timeout, failing the stack deploy

### Hand-written DER parsing in the standard library only

Walk the ASN.1 far enough to find `notAfter`

* Good, because no dependency at all
* Bad, because it is a hand-rolled parser for input a stranger controls, which is how parsers become vulnerabilities
* Bad, because it would yield the expiry date and nothing else

### Shelling out to `openssl s_client -dates`

Run the OpenSSL client and scrape its output

* Good, because the binary is already in the runtime image
* Bad, because it parses human-readable output that varies between OpenSSL versions
* Bad, because a subprocess per domain, with its own timeout handling, is slower and harder to bound than a socket

## More Information

Confidence: High.
Review by: When the Lambda Python runtime ships an X.509 parser, or when the checker needs chain validation.
Trade-offs accepted: a compiled runtime dependency that has to be kept patched, and a second build artefact.
Components: AWS Lambda (layer), cryptography 50.0.2.
Requirements addressed: REQ-01, REQ-05.
Part of the CertWatch architecture decision record.
