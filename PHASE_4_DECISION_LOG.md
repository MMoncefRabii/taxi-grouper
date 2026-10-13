# Phase 4 Decision Log

## Overview
This session completed the Phase 4 migration and hardening work for Taxi Grouper.
The focus was on fixing specific behavior issues, validating ML model selection, tightening OAuth security, and moving legacy code into the new `src/` layered architecture.

## Fixes and why they were made

### 1. EH-9: Prevent regex injection during filtering
- What changed:
  - `src/core/preprocessing.py` now uses `regex=False` in `DataFrame.str.contains(...)` calls.
- Why:
  - This prevents user-provided data from being interpreted as regular expressions and causing incorrect filtering or potential injection-like behavior.

### 2. DC-4: Ensure exporter drops blank historical rows
- What changed:
  - `src/adapters/exporter.py` was updated to recognize blank rows in historical-style exports, including accented headers and mojibake variants.
- Why:
  - Blank rows in the source historique export should not become real grouped rows in output.

### 3. DC-5: Use explicit model metadata to choose the correct feature extractor
- What changed:
  - `src/core/ml_model.py` now loads feature lists from adjacent `config.json` or `training_report.json` metadata files and attaches them to the model as `_feature_names`.
  - `score_pair()` and `score_pairs()` now prefer `_feature_names` and only fall back to `model.n_features_in_` when metadata is absent.
- Why:
  - The previous behavior could silently infer the wrong extractor based on feature count alone.

### 4. Metadata validation safeguard
- What changed:
  - `load_model()` now raises a `ValueError` if loaded model metadata conflicts with the estimator's actual `n_features_in_`.
- Why:
  - This is a fail-fast safety measure to avoid quiet, wrong guesses when model metadata and the model shape disagree.

### 5. SEC-4: Narrow Google OAuth scope
- What changed:
  - `src/config/__init__.py` now defaults to only `https://www.googleapis.com/auth/spreadsheets`.
  - Drive conversion remains explicitly gated by `drive.file` scope if configured.
- Why:
  - Minimizes OAuth scope surface area and avoids unnecessary Drive-wide readonly permissions.

### 6. SEC-7: Stop storing `client_secret` in token storage
- What changed:
  - `src/data/sheets_repository.py` no longer writes `client_secret` into `google_oauth_tokens.json`.
  - Existing persisted token storage was sanitized to remove `client_secret`.
- Why:
  - Protects sensitive OAuth client credentials from being stored in local token state.

### 7. Legacy package migration
- What changed:
  - All remaining `taxi_grouper.*` imports in source and tests were migrated to `src.*`.
  - The legacy `taxi_grouper/` package folder was removed.
- Why:
  - Completes the Phase 2 refactor into the new layered architecture and removes the old package-level compatibility layer.

## Validation
- Full repository test run passed: `39 passed`.
- Focused DC-4/DC-5/preprocessing tests were also validated earlier.

## Notes
- OAuth re-consent:
  - The app now requests a narrower default scope on next authorization.
  - Existing stored tokens can continue to work, but the safest approach is to reauthorize users so they receive the new narrower consent scope and no stale scope data remains.
  - The app now also avoids persisting `client_secret`.

## Files changed
- `src/core/ml_model.py`
- `src/core/preprocessing.py`
- `src/adapters/exporter.py`
- `src/config/__init__.py`
- `src/data/sheets_repository.py`
- `README.md`
- `PHASE_4_DECISION_LOG.md`
