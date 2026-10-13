# Taxi Grouper - Grand Tunis

Taxi Grouper is a Python application for grouping company agents into taxis for Tunis transport planning.
It supports Excel dispatch input, address normalization, zone compatibility, optional ML-assisted ordering, and both Streamlit and FastAPI interfaces.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Install](#install)
- [Run the CLI](#run-the-cli)
- [Run the Streamlit app](#run-the-streamlit-app)
- [Run the FastAPI backend](#run-the-fastapi-backend)
- [Training the ML model](#training-the-ml-model)
- [Input data expectations](#input-data-expectations)
- [Output files](#output-files)
- [Run the tests](#run-the-tests)
- [Project structure](#project-structure)
- [Architecture](#architecture)

---

## Prerequisites

1. Windows, macOS, or Linux.
2. Python 3.10+ installed and available as `python`.
3. `pip` available in the selected Python environment.
4. For the frontend only: Node.js and npm if you want to run the React/Vite app under `frontend/`.

---

## Install

Open a terminal at the repository root (`c:\Users\MSI\Desktop\taxi_grouper`) and run:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If you want the UI-specific package set instead of the full API stack, use:

```bash
pip install -r requirements-ui.txt
```

> On macOS/Linux use `source .venv/bin/activate` instead of the Windows activate command.


### Frontend environment

If you run the frontend from `frontend/`, create a `frontend/.env` file containing:

```dotenv
VITE_GOOGLE_API_KEY=<your-Google-API-key>
```

The frontend uses `VITE_GOOGLE_API_KEY`, so a root `.env` with `GOOGLE_API_KEY` is not sufficient for Vite.

---

## Run the CLI

The main grouping entrypoint is `main.py`.

```bash
python main.py --input <input.xlsx> --output <output.xlsx>
```

Example:

```bash
python main.py --input data/raw/sample_agents.xlsx --output outputs/grouped_output.xlsx --time 07:00
```

Optional arguments:

- `--time <HH:MM>` — filter rows by arrival/departure time
- `--type-course <Ramassage|Retour>` — filter by course type
- `--operation <name>` — filter by client or operation
- `--no-ml` — disable ML-assisted ordering and use rule-based grouping only

The CLI validates grouped output and writes a formatted Excel file plus a validation report.

---

## Run the Streamlit app

The Streamlit user interface is available in `app.py`.

```bash
streamlit run app.py
```

Features:

- upload Excel files (`.xlsx` or `.xls`)
- filter by time, course type, and operation
- run automatic grouping
- preview grouped results interactively
- download grouped Excel output
- save corrected results to `data/corrected/`

The Streamlit app uses shared core grouping logic from `src.core`.

---

## Run the FastAPI backend

The API backend is defined in `src/api/service.py`.

```bash
uvicorn src.api.service:app --reload
```

Available endpoints include:

- `GET /health` — health check
- `GET /api/auth/login-url` — Google OAuth login URL
- `GET /api/auth/status` — OAuth sign-in status
- `POST /api/group-sheet` — group agents from a Google Sheet and write results back

For frontend builders or scripting integrations, see [`docs/api_usage.md`](docs/api_usage.md).

The backend uses shared services from `src.api`, `src.core`, and `src.data`.

> Google Sheet integration requires proper Google OAuth setup. Token state is stored in `data/google_oauth_tokens.json`, and the system no longer persists `client_secret` there.

> **Current deployment model:** the app is designed for a single server instance using local filesystem persistence only (`data/` and `models/`). This is safe for one server / one client deployment, but multi-instance/load-balanced deployment is a known future constraint.

Note: The app requires both the Sheets scope and the Drive "file" scope (`https://www.googleapis.com/auth/drive.file`) so the Google Picker and backend Drive metadata/convert operations can access the user-selected file. Using Sheets-only caused 403s when the picker selected files.

---

## Training the ML model

Taxi Grouper can optionally use a trained ML model to improve ordering inside the grouping rules.

Training expects historical or corrected Excel data containing a valid address column and a grouping column such as `Taxi`, `Groupe`, `Groupe Taxi`, or `Taxi ID`.

Train a model with:

```bash
python train.py --data data/training_files/ --output models/
```

Or train from corrected data:

```bash
python train.py --data data/corrected/ --output models/
```

The model files are saved under `models/`:

- `models/taxi_grouping_model.pkl`
- `models/config.json`

If no trained model exists, the system falls back to rule-based grouping.

---

## Input data expectations

Supported input files are Excel files containing dispatch rows.

Recommended column names:

- `Date`
- `Matricule`
- `Nom - Prénom`
- `Opération`
- `Site`
- `Adresse`
- `Heure d'arrivée`
- `Heure de départ`
- `Taxi`
- `Groupe Taxi`
- `Client`
- `Type de course`

The code is flexible about column order. Address fields may appear with variant names such as:

- `Adresse`
- `Address`
- `Lieu`
- `Localisation`
- `Adresse Ramassage`

The grouping pipeline performs:

1. column detection via `src.core.preprocessing.detect_columns`
2. row filtering via `src.core.preprocessing.filter_dataframe`
3. address normalization and zone detection
4. taxi grouping with a maximum of 4 passengers per taxi

Unknown or unrecognized addresses are marked as `UNKNOWN` and handled separately.

---

## Output files

Grouped Excel files are written to the path you specify in the CLI or exported automatically by Streamlit.

Corrected UI output is saved to `data/corrected/`.

The CLI writes an additional validation report in the same output folder with a `_validation_report.xlsx` suffix.

---

## Run the tests

The repository uses `pytest` for automated tests.

From the project root:

```bash
pytest
```

To run a single file:

```bash
pytest tests/test_grouper.py
```

---

## Architecture

The codebase now uses a layered `src/` architecture:

- `src/api/` — FastAPI service and endpoint routing
- `src/core/` — core domain logic, grouping, ML model loading, preprocessing, zone handling, and validation
- `src/data/` — Google Sheets and Drive integration, OAuth token flow, and file imports
- `src/adapters/` — export helpers for Excel output and historique-style Excel formatting
- `src/config/` — environment-driven settings, paths, and defaults
- `src/schemas/` — shared constants and schema-level definitions

Other key folders:

- `data/` — runtime data, corrected outputs, OAuth token storage
- `models/` — trained ML artifacts and metadata
- `outputs/` — generated Excel export outputs
- `frontend/` — React/Vite frontend code
- `tests/` — unit and integration tests

---

## Project structure

```text
.
├── api.py
├── app.py
├── main.py
├── train.py
├── models/
├── data/
├── outputs/
├── src/
│   ├── adapters/
│   ├── api/
│   ├── config/
│   ├── core/
│   ├── data/
│   ├── logging_config.py
│   ├── schemas/
├── frontend/
├── tests/
├── requirements.txt
├── requirements-ui.txt
```

---

## Architecture notes

- `main.py`, `api.py`, and `app.py` now orchestrate the new `src/` packages.
- Model metadata is loaded from `models/config.json` or `models/training_report.json` and attached explicitly to ML models.
- OAuth token storage no longer persists sensitive `client_secret` values.
- Default Google scopes are now limited to `https://www.googleapis.com/auth/spreadsheets`.
- Compatibility rules and constants are in `src/config/__init__.py`.
- Grouping logic is implemented in `src/core/grouper.py`.
- Export formatting lives in `src/adapters/exporter.py`.
- Column detection and input filtering live in `src/core/preprocessing.py`.

### Important behaviors

- Maximum taxi capacity is enforced by the grouping logic.
- ML ordering is optional and cannot override hard zone rules.
- Unknown addresses are preserved and flagged separately.

### Optional frontend

If you want to inspect or extend the React/Vite frontend under `frontend/`, install Node dependencies and use:

```bash
cd frontend
npm install
npm run dev
```

---

## Troubleshooting

- If `streamlit` is not found, confirm the virtual environment is active and that `streamlit` is installed.
- If Excel files fail to load, verify the file format is `.xlsx` or `.xls` and that the sheet contains recognized headers.
- If Google Sheet operations fail, ensure OAuth credentials are configured and `data/google_oauth_tokens.json` is writable.
