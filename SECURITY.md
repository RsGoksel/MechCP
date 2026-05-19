# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.3.x   | yes       |
| earlier | no, please upgrade |

## Reporting a vulnerability

If you have found a security issue in MechCP, please report it privately. Do NOT open a public GitHub issue.

Preferred channels:

1. **GitHub Security Advisory** (preferred). Open a draft advisory at
   https://github.com/RsGoksel/MechCP/security/advisories/new. This keeps the
   discussion private until a fix is ready.
2. **Direct email** to the maintainer listed in the GitHub profile of the
   repo owner.

Please include:

- A concise description of the vulnerability.
- A proof-of-concept or reproducer.
- The affected version (run `git rev-parse HEAD` in your clone, or note the
  release tag).
- Your suggested CVSS score and severity.

We aim to acknowledge reports within 72 hours and provide a fix or mitigation
plan within 14 days for HIGH/CRITICAL findings.

## Scope

In scope:

- The MCP server code under `src/`.
- The vendored `py2js` package under `vendor/py2js/`.
- The default Chrome flags in `src/stealth_scripts.py` and the
  `addScriptToEvaluateOnNewDocument` payload (any escape from that sandbox
  is in scope).
- The AST validator in `src/safe_code.py` and any path-resolution issue in
  `src/path_safety.py`.

Out of scope:

- Detection of MechCP-driven browsers by individual anti-bot services. The
  stealth posture is best-effort and intentionally documented as such in the
  README.
- Vulnerabilities in upstream dependencies (`nodriver`, `fastmcp`, `pydantic`)
  that are not aggravated by MechCP's usage. Please report those upstream.
- Issues in your own MCP client / agent configuration.

## Responsible disclosure timeline

- T+0: report received.
- T+3 days: triage acknowledgement.
- T+14 days: fix or mitigation plan communicated.
- T+90 days: public disclosure if no fix has shipped (negotiable).

Reporters who follow this process are credited in the release notes unless
they request anonymity.
