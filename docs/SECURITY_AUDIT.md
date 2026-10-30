# Dependency security audit

Reviewed 2026-10-30 against the four committed dependency locks. No findings
remain accepted or ignored. `pip-audit`'s baseline records included duplicate
records for the same advisory ID; the unique findings and their package counts
are described below.

## Findings and disposition

| Package and advisory | Affected feature | Project reachability | Disposition |
| --- | --- | --- | --- |
| `cryptography` 49.0.0 - PYSEC-2026-3552 (CVE-2026-69247) | `pkcs7_decrypt_der`, `pkcs7_decrypt_pem`, and `pkcs7_decrypt_smime` can expose distinguishable RSA PKCS#1 v1.5 decryption failures, including recovered key length/timing, creating a Bleichenbacher oracle when an application decrypts attacker-controlled CMS EnvelopedData and reflects the result. | `cryptography` is installed transitively through `google-auth`. A source search found no direct `cryptography` imports, calls to the affected PKCS#7 APIs, or application handling of attacker-supplied CMS EnvelopedData. | Resolved in the runtime, UI, desktop, and test locks with `cryptography` 50.0.2 (fixed in 50.0.0). |
| `oauthlib` 3.3.1 - PYSEC-2026-4114 (CVE-2026-49265) | The OAuth 2 authorization-code PKCE verifier functions `code_challenge_method_plain` and `code_challenge_method_s256` compare values non-constantly, permitting a timing side channel. | `oauthlib` is present through `google-auth-oauthlib` -> `requests-oauthlib`. The application implements its Google authorization-code flow directly and does not import or call these libraries' PKCE verifier functions; the flow uses a one-time state value instead of PKCE. | Resolved in the runtime, UI, desktop, and test locks with `oauthlib` 4.0.0. |
| `oauthlib` 3.3.1 - CVE-2026-49272 | `DeviceCodeGrant.validate_token_request` does not validate the supplied device code in the OAuth device-authorization token flow. | The `oauthlib` dependency is installed as above, but the application does not implement a device-code flow or call `DeviceCodeGrant`. Its Google sign-in uses an authorization-code callback. | Resolved in the runtime, UI, desktop, and test locks with `oauthlib` 4.0.0. |
| `pillow` 12.3.0 - 39 advisories | The advisories affect image decoders and plugins (including BMP, GIF, JPEG, PNG, TIFF, and WMF), PDF/EPS handling, and related image/text operations. They include malformed-input memory safety errors, hangs, and excessive memory or CPU use. | Pillow is a Streamlit dependency in the UI lock, not the runtime container lock. The application source has no Pillow/PIL imports or image-processing calls; its UI accepts spreadsheet data rather than using Pillow image features. | Resolved in the UI lock with `pillow` 13.0.0 (fixed version for all 39 reported advisories). |

## Upgrade and dependency resolution

The minimum constraints are recorded in `requirements.in`
(`cryptography>=50.0.0`, `oauthlib>=4.0.0`) and `requirements-ui.in`
(`pillow>=13.0.0`). Fresh resolver runs using `pip-compile` completed without
dependency conflicts:

- `cryptography` 50.0.0 resolved with `google-auth`; no upper-bound conflict
  was encountered. The generated lock selected 50.0.2.
- `oauthlib` 4.0.0 resolved with `google-auth-oauthlib` and
  `requests-oauthlib` 2.0.0. Neither imposed a conflicting upper bound; the
  generated lock selected both requested versions. The installed metadata
  specifies `cryptography>=38.0.3` for `google-auth`,
  `requests-oauthlib>=0.7.0` for `google-auth-oauthlib`, and
  `oauthlib>=3.0.0` for `requests-oauthlib`; none has an upper bound.
- `pillow` 13.0.0 resolved with Streamlit 1.66.1. The UI lock is not installed
  in the runtime container.

No compatibility code changes were required. No advisory IDs are ignored, so
the documented `pip-audit` commands fail on any reported finding.

## Audit results

| Lock | Before | After |
| --- | --- | --- |
| `requirements.txt` (runtime) | 5 records: `cryptography` 2, `oauthlib` 3 | No known vulnerabilities |
| `requirements-ui.txt` | 44 records: `cryptography` 2, `oauthlib` 3, `pillow` 39 | No known vulnerabilities |
| `requirements-desktop.txt` | 5 records: `cryptography` 2, `oauthlib` 3 | No known vulnerabilities |
| `requirements-test.lock` | 5 records: `cryptography` 2, `oauthlib` 3 | No known vulnerabilities |

The duplicate records represent duplicate entries for the same advisory IDs;
the finding descriptions and dispositions above deduplicate them.
