# Sheets Contract for the Fleet Tracker Port

## Input columns and formats

| Purpose | Exact recognized names and aliases | Evidence |
|---|---|---|
| Date | `Date` (column lookup is case-insensitive and normalizes selected accents; no date aliases are declared) | [VERIFIED in code: `src/core/grouper.py` `_find_existing_col`, `_parse_dispatch_dates`] |
| Address (required) | `adresse`, `address`, `lieu`, `localisation`, `adresse ramassage`, `ramassage`, `retour` | [VERIFIED in code: `src/core/preprocessing.py` `ADDRESS_ALIASES`, `detect_columns`] |
| Time | `heure`, `heure arrivee`, `heure d arrivee`, `heure depart`, `heure de depart`, `heure ramassage`, `heure retour` | [VERIFIED in code: `src/core/preprocessing.py` `TIME_ALIASES`] |
| Agent name | `nom`, `nom prenom`, `nom agent`, `agent`, `nom - prenom` | [VERIFIED in code: `src/core/preprocessing.py` `NAME_ALIASES`] |
| Existing taxi/group | `taxi`, `groupe`, `groupe taxi`, `taxi id`, `taxi_group`, `taxi group` | [VERIFIED in code: `src/core/preprocessing.py` `TAXI_ALIASES`] |
| Operation/client | `operation`, `opération`, `client` | [VERIFIED in code: `src/core/preprocessing.py` `OPERATION_ALIASES`] |
| Site | `site` | [VERIFIED in code: `src/core/preprocessing.py` `SITE_ALIASES`] |
| Course type | `type de course`, `ramassage retour`, `ramassage / retour` | [VERIFIED in code: `src/core/preprocessing.py` `TYPE_COURSE_ALIASES`] |
| Source dispatch ID | `DispatchID`, `SourceDispatchID`, `IdDispatch`, `DispatchNumber`, `DispatchNo`, with case and punctuation ignored | [VERIFIED in code: `src/core/preprocessing.py` `DISPATCH_ID_ALIASES`, `_find_dispatch_id_column`] |

- [VERIFIED in code: `src/core/preprocessing.py` `detect_columns`, `_best_column`] Address is required; time, name, taxi, operation, site, and course type are optional. Header matching normalizes text and also permits partial containment rather than requiring only literal equality.
- [VERIFIED in code: `src/schemas/__init__.py` `HISTORIQUE_COLUMNS`, `HISTORIQUE_COLUMNS_WITH_NUMERO`] The recognized repeated Historique header layouts are `Date`, `Matricule`, `Nom - Prénom`, `Opération`, `Site`, `Adresse`, `Heure d'arrivée`, `Taxi`; and `Date`, `Matricule`, `Nom - Prenom`, `Operation`, `Site`, `Numero`, `Adresse`, `Heure d'arrivee`, `Taxi`, `PRIX`.
- [VERIFIED in code: `src/core/preprocessing.py` `load_dispatch_excel`] Excel workbooks are read across all sheets by default; `.ods` is read by the repository's ODS parser. Repeated Historique headers are treated as dispatch-block boundaries. Nonempty rows are retained and repeated header rows are skipped.
- [INFERRED] The aliases above describe importer detection, not a complete Fleet Tracker validation schema. The current code does not enforce a single canonical spelling for optional columns.

## Date interpretation

- [VERIFIED in code: `src/config/__init__.py` `GrouperConfig`; `src/core/grouper.py` `_parse_dispatch_dates`] The default is day-first (`day_first=True`).
- [VERIFIED in code: `src/core/grouper.py` `_parse_dispatch_dates`] Accepted text date forms are ISO `YYYY-MM-DD`, day-first `DD/MM/YYYY`, and day-first `DD-MM-YYYY`. Parsing is strict to those patterns; invalid or other text becomes an invalid date.
- [VERIFIED in code: `src/core/grouper.py` `_parse_dispatch_dates`] Python `date`/`datetime` and pandas `Timestamp` values are used as date values without string-format interpretation.
- [VERIFIED in code: `src/config/__init__.py` `GrouperConfig`; `src/core/grouper.py` `_parse_dispatch_dates`] Numeric Excel serials are accepted inclusively from 43831 through 73415 and converted using the Excel origin `1899-12-30`; numbers outside that range are invalid. Non-integral serials within range are passed through as fractional-day values.
- [INFERRED] Fleet Tracker should preserve Excel's typed date-cell values where available and avoid parsing ambiguous or unrecognized strings using locale guesses.

## Source dispatch/block identity

- [VERIFIED in code: `src/core/preprocessing.py` `_add_dispatch_block_metadata`, `add_dispatch_block_metadata`, `load_dispatch_excel`] When a recognized dispatch-ID column exists, its trimmed value is copied to `SourceDispatchID` and `block_id_origin` is set to `provided`.
- [VERIFIED in code: `src/core/preprocessing.py` `_add_dispatch_block_metadata`, `load_dispatch_excel`] When no recognized dispatch-ID column exists, the importer synthesizes `SourceDispatchID` as `<source_id> | <sheet_name or gid> | <block_ordinal>` and sets `block_id_origin` to `synthesized`. A missing component or non-positive ordinal yields no synthesized ID and an empty origin value.
- [VERIFIED in code: `src/core/preprocessing.py` `load_dispatch_excel`] For workbooks, the default `source_id` is the input filename, the sheet component is the workbook sheet name, and repeated Historique header sections increment the one-based block ordinal independently within each sheet. A workbook sheet without repeated headers gets ordinal 1 for all rows.
- [VERIFIED in code: `src/data/sheets_repository.py` `_read_google_sheet_to_dataframe`] For Google Sheets, the source ID is the spreadsheet ID, the sheet component used in the synthesized ID is the sheet's numeric gid (not its title), and each repeated recognized header advances the block ordinal. Without repeated headers, all data rows in the selected tab receive ordinal 1.
- [VERIFIED in code: `src/core/grouper.py` `group_agents`, `_block_columns`] Grouping partitions on parsed date, source dispatch ID, time, selected course-type columns, and present dispatch/call-center fields. Operation is a filter, not itself a block key.
- [VERIFIED in code: `src/core/grouper.py` `validate_dispatch`] Validation rejects a taxi group with multiple parsed dates or multiple source dispatch IDs, and reports invalid/missing dates or missing IDs when the corresponding columns are present.
- [INFERRED] The implementation exposes the identity as `SourceDispatchID`, not as a field literally named `source_block_id`. A Fleet Tracker schema can map `SourceDispatchID` to `source_block_id` while preserving `block_id_origin`; this mapping is a porting recommendation, not an existing API field contract.
- [INFERRED] Repeated-header ordinal boundaries are reliable only when the source workbook/Google tab uses the recognized Historique header shape. The code does not infer separate dispatch blocks from dates or from arbitrary visual separators.

## Filters

- [VERIFIED in code: `src/api/service.py` `group_sheet_endpoint`; `src/core/preprocessing.py` `filter_dataframe`] `/api/group-sheet` accepts optional `time_filter`, `type_course_filter`, and `operation_filter`; empty values are treated as no filter.
- [VERIFIED in code: `src/core/preprocessing.py` `filter_dataframe`] Time filtering strips surrounding whitespace from each row value and applies a case-insensitive literal substring match against the requested time string.
- [VERIFIED in code: `src/core/preprocessing.py` `filter_dataframe`] Course-type and operation filtering apply case-insensitive substring matches; the row values are stringified, but are not trimmed before matching.
- [VERIFIED in code: `src/core/preprocessing.py` `filter_dataframe`] A requested filter is skipped if its corresponding optional column was not detected.
- [VERIFIED in code: `src/api/service.py` `sheet_info_endpoint`] Sheet metadata exposes distinct nonblank available time and operation values when those columns exist; the endpoint does not expose a corresponding list of course-type values.
- [INFERRED] The current substring behavior may match more than one category (for example, a short operation fragment). Fleet Tracker should preserve this behavior only if that is the intended operator contract; the code does not define whether matching should be exact.

## Destination and zone detection

- [VERIFIED in code: `src/core/destination_cleaner.py` `clean_destination_text`, `detect_clean_destination`, `add_clean_destination_columns`] Addresses are normalized (including accent/transliteration and punctuation cleanup), cleaned of generic address words/noise phrases, then checked against destination aliases using exact, substring, and fuzzy matching.
- [VERIFIED in code: `src/core/destination_cleaner.py` `detect_clean_destination`] Exact and substring alias matches are valid with score 100. Fuzzy scores of at least 85 are valid; scores from 70 through less than 85 need manual validation; lower scores or no match are unknown.
- [VERIFIED in code: `src/core/destination_detector.py` `DESTINATION_ALIASES`; `src/core/destination_cleaner.py` `detect_clean_destination`] The alias records map recognized destinations to zone labels; the built-in records are supplemented by destination alias loading in the cleaner.
- [VERIFIED in code: `src/core/destination_cleaner.py` `add_clean_destination_columns`] Internal destination fields include `CleanAddress`, `DetectedDestination`, `DestinationZone`, `Zone`, `MatchedAlias`, `DestinationScore`, `DestinationConfidence`, `DestinationStatus`, `DetectionMethod`, `NeedsManualValidation`, and `NeedsManualReview`.
- [VERIFIED in code: `src/core/grouper.py` `group_agents`, `_group_block`] Unknown and low-confidence destinations remain in results and generate warnings; they are bucketed for manual review rather than being silently dropped.
- [INFERRED] Detection depends on the active alias data as well as source code, so a Fleet Tracker port that needs equivalent outcomes must migrate or replace that alias data and its maintenance workflow.

## Unassigned reason codes

- [VERIFIED in code: `src/core/grouper.py` `group_agents`] The only assigned `UnassignedReason` codes are `MISSING_DATE` and `MISSING_DISPATCH_ID`. `MISSING_DATE` is set for a missing or unparsable date; `MISSING_DISPATCH_ID` is set when the date is valid but the source dispatch ID is missing.
- [VERIFIED in code: `src/core/grouper.py` `group_agents`, `validate_dispatch`] Rows with either reason are excluded from grouping, have an empty taxi value, and carry an `AssignmentStatus` of `A CORRIGER: date manquante` or `A CORRIGER: identifiant de dispatch manquant`. Their `UnassignedReason` is retained. They do not consume taxi numbers, and validation reports their reason as a warning rather than as a missing-taxi error.
- [VERIFIED in code: `src/core/grouper.py` `group_agents`] There is no separate `AMBIGUOUS_DATE` reason code; invalid date strings use `MISSING_DATE`.
- [VERIFIED in code: `src/core/grouper.py` `_group_block`] `Unknown address`, `Manual review required`, and `Single remaining agent` are `GroupReason` descriptions, not `UnassignedReason` codes.
- [INFERRED] Fleet Tracker should treat `UnassignedReason` as the authoritative machine-readable reason and keep it distinct from explanatory grouping/review text.

## Output tabs and write-back

- [VERIFIED in code: `src/data/sheets_repository.py` `CLIENT_SHEET_NAME`, `INTERNAL_SHEET_NAME`, `CLIENT_SHEET_COLUMNS`] Output uses a client-facing tab named `Taxi Grouper Client Output` with columns, in order: `Date`, `Matricule`, `Nom - Prénom`, `Opération`, `Site`, `Numéro`, `Adresse`, `Heure d'arrivée`, `Groupe Taxi`, `PRIX`, `Statut`. Unassigned rows have an empty `Groupe Taxi` value and show the human-readable status in `Statut`.
- [VERIFIED in code: `src/data/sheets_repository.py` `write_grouped_df_to_sheet`] Every grouping run writes to two distinct new spreadsheets: the client spreadsheet contains only the `Taxi Grouper Client Output` tab and approved client columns; the internal spreadsheet contains only the `Taxi Grouper Internal` tab and every grouped-data column, including internal destination, validation, source, and reason fields when present.
- [VERIFIED in code: `src/data/sheets_repository.py` `_create_google_sheet`] New output spreadsheets are created in the folder configured by `GOOGLE_OUTPUT_FOLDER_ID`. Their titles include the source name, output audience (`Client Output` or `Internal Output`), and a unique run suffix. There is no default to the source's parent folder.
- [VERIFIED in code: `src/data/sheets_repository.py` `write_grouped_df_to_sheet`] The input spreadsheet is read-only for grouping output. If an Office input is converted, the converted spreadsheet is a read-only intermediate as well; neither ID is used as an output target.
- [VERIFIED in code: `src/data/sheets_repository.py` `write_grouped_df_to_sheet`] Each run creates new output spreadsheets by default. Existing spreadsheets are overwritten only when both distinct output spreadsheet IDs and the explicit `overwrite=true` option are supplied; output IDs may not match the source or its converted copy. The overwrite targets must each contain only their expected output tab. Spreadsheets are never reused by title.
- [VERIFIED in code: `src/data/sheets_repository.py` `_write_values_to_sheet`] The target output tab is cleared and rewritten from cell A1 using the Sheets API with `valueInputOption="RAW"`.
- [VERIFIED in code: `src/api/service.py` `group_sheet_endpoint`, `save_drive_endpoint`] API responses expose `client_sheet_url`, `internal_sheet_url`, `client_sheet_id`, and `internal_sheet_id`. For compatibility, `sheet_url` and `sheet_id` alias the client output. Correction validation accepts the client output ID and pre-correction state is keyed by that ID; grouping continues to read from the source ID.
- [VERIFIED in code: `src/config/__init__.py` `Settings`; `src/data/sheets_repository.py` `_create_google_sheet`] Drive access continues to use `drive.file`, not full Drive access. The configured output folder must be writable and accessible to the app under that per-file scope; folder permission failures are returned as output-creation errors. No automatic sharing is performed by the application. Internal spreadsheet confidentiality therefore depends on the owner's Drive access controls and folder permissions, not a hidden tab.
- [VERIFIED in code: `src/adapters/exporter.py` `export_excel`, `export_like_historique`] Excel exports retain the empty taxi value and expose the human-readable unassigned status (`AssignmentStatus` in the grouped-data export and `Statut` in the Historique-style export). Summary taxi counts and per-taxi totals include assigned rows only.
- [VERIFIED in code: `src/data/sheets_repository.py` `_collapse_grouped_taxi_values`, `write_grouped_df_to_sheet`] Repeated taxi values in the client tab are collapsed for display; the internal tab is written from the full grouped dataframe values.
- [INFERRED] Treat the internal spreadsheet as operationally sensitive because it contains more detail than the client spreadsheet. The app does not create sharing permissions; the owner must ensure the configured folder and file ACLs match the intended audience.

## Open questions for the Fleet Tracker port

- [INFERRED] Should filters retain case-insensitive substring matching, or should Fleet Tracker offer exact matching and/or a user-visible choice?
- [INFERRED] What should define a dispatch block when a workbook/tab lacks both a dispatch-ID column and recognizable repeated Historique headers? Current behavior synthesizes one block per source sheet/tab section rather than deriving one per date.
- [INFERRED] Should Fleet Tracker preserve original source column names alongside canonical field names, and which optional columns should become required?
- [INFERRED] Which destination alias dataset and alias-editing workflow should Fleet Tracker use, and how should alias changes be audited?
- [INFERRED] Which internal fields are approved for Fleet Tracker operators, clients, and other callers, and should internal output sharing be managed by a separate operational workflow?
