# Code Compliance Standard

## Purpose

This document defines mandatory code quality, security, and privacy controls for Janam.
All contributions must comply before merge and release.

## 1. Code Quality Requirements

- Python version compatibility must match project runtime.
- New backend code must include type hints.
- Public API changes must update request/response schemas.
- Avoid breaking existing API contracts without version plan.
- Keep functions focused and side effects explicit.

## 2. Testing Requirements

Minimum for every backend change:

- Unit/API tests for new logic
- Regression tests for fixed bugs
- All tests passing:

```bash
python -m pytest backend/tests/test_api.py -q
```

For ingest changes, include test coverage for:

- valid signed request
- invalid signature
- missing signature headers
- anonymized persistence behavior

## 3. Security Requirements

- Never commit real secrets or production credentials.
- Enforce explicit API keys in non-dev environments.
- Require signed webhook verification for `/ingest/n8n`.
- Use constant-time comparisons for secret checks.
- Validate timestamp skew to reduce replay risk.

## 4. Privacy and Data Protection Requirements

- Keep `anonymous_mode=true` as default for untrusted reporter channels.
- Do not persist raw personal identifiers for citizen reporters.
- Scrub sensitive text content where configured.
- Keep `JANAM_STORE_INGEST_RAW_PAYLOAD=false` unless explicitly justified.
- Coarsen GPS precision for public/citizen submissions.

## 5. Dependency and Supply Chain Requirements

- Pin dependency ranges in `requirements.txt`.
- Review dependency updates for known vulnerabilities.
- Prefer maintained libraries and remove unused dependencies.

## 6. Documentation Requirements

Any change to one of the following must update docs:

- API route behavior
- environment variables
- authentication model
- ingest schema or signature contract

Required docs to update when applicable:

- `README.md`
- `docs/api-reference.md`
- `docs/deployment.md`
- `docs/operations-runbook.md`

## 7. Release Compliance Checklist

Before release, verify all items:

- Tests pass in CI/local
- No placeholder secrets in deployment environment
- CORS restricted to trusted origins
- Signed ingest endpoint validated with real signature test
- Privacy defaults validated (`anonymous_mode`, payload minimization, GPS coarsening)
- Rollback and incident contacts documented

## 8. Non-Compliance Handling

- Non-compliant pull requests must not be merged.
- Critical security/privacy violations require immediate patch release.
- Post-incident review must include compliance gap analysis and corrective action.
