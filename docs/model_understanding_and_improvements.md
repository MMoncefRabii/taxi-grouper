# Taxi Grouper model understanding and upgrade plan

## 1) Recommended reading order

Read in this sequence to understand the actual business logic from raw input to final grouping:

1. `main.py`
   - entry point for a normal run
   - shows the operational flow
2. `src/core/preprocessing.py`
   - raw input cleanup and schema detection
3. `src/core/zones.py`
   - address normalization and geographic compatibility rules
4. `src/core/destination_cleaner.py`
   - destination resolution and unknown-address handling
5. `src/core/grouper.py`
   - actual grouping strategy and validation
6. `src/core/ml_model.py`
   - optional ML assist logic and training
7. `train.py`
   - how the model is trained and saved
8. `src/config/__init__.py`
   - global constants and capacity rules

This order mirrors the real data flow:

raw file -> detect columns -> normalize addresses -> detect zone/destination -> group -> validate -> optionally use ML -> export

## 2) Why the project is structured this way

### 2.1 `main.py` sets the business workflow
The CLI uses a strict sequence:

- load Excel
- detect columns
- filter rows
- group agents
- validate dispatch
- export output

This is intentional: the application is not a black-box ML predictor. It is a safety-first pipeline. The system tries to produce valid groupings under business rules before it trusts ML scoring.

### 2.2 `preprocessing.py` handles messy real-world Excel input
Real Excel dispatch files often have:

- different header names
- extra repeated historical header rows
- sheet-based organization
- mixed formats for addresses and times

The code therefore:

- accepts alias names for columns (`Adresse`, `Address`, `Lieu`, etc.)
- strips repeated header blocks
- supports sheet-by-sheet reading
- filters data by time, operation, or course type

Why this matters:

- the real system input is messy and inconsistent
- the project chooses flexible schema detection instead of strict assumptions
- this reduces breakage when input files vary by client or month

### 2.3 `zones.py` is the geographic foundation
This file is the base layer for all grouping decisions.

It does three important things:

- normalizes raw text
- maps normalized text to canonical zones
- defines compatibility between zones

The critical design choice is that grouping is not based on raw text alone. It is based on a canonical zone representation, which makes grouping decisions consistent and explainable.

Example:

- `ZONE_COMPATIBILITY` in `src/config/__init__.py` defines which zones are allowed together
- `zones_are_compatible()` checks compatibility by zone, not by arbitrary string comparison

This is an important business rule: taxi groups must respect geographic compatibility, even if destination names differ slightly.

### 2.4 `destination_cleaner.py` turns noisy addresses into valid destinations
This module is where the system converts a messy address string into a useful destination identity.

The design is:

- clean punctuation and Unicode issues
- remove generic noise words like `rue`, `avenue`, `lot`, etc.
- detect known aliases via a curated alias index
- apply fuzzy matching for near-matches
- mark low-confidence or unknown destinations as `needs_manual_validation` or `unknown`

This is intentionally conservative. It avoids creating a false group from a low-confidence destination match.

Why this is a good trade-off:

- bad data is worse than a manual review flag
- the system chooses explicit uncertainty over silent mis-grouping

### 2.5 `grouper.py` is the real business engine
This is the core logic where agents are assigned to taxis.

The grouping strategy is:

1. remove empty rows
2. enrich rows with destination/zone metadata
3. split data into dispatch blocks
4. group by same destination first
5. fill partial taxis by same-zone then compatible-zone logic
6. leave unknown addresses in review buckets
7. assign remaining items to single-agent or fallback groups
8. validate the final taxi groups

This is a robust operational strategy because it mirrors actual dispatch logic:

- same destination first is the most natural grouping
- if a taxi is not full, fill it using same-zone passengers
- if no same-zone options remain, allow compatible zones
- unknown addresses are separated from main grouping to prevent invalid decisions

Important design choice: hard rules are trusted before ML.

The code explicitly states that ML is not used to create groups directly. It only helps rank candidate additions that already pass hard compatibility filters.

This is a critical safety principle.

### 2.6 `ml_model.py` is not the main engine; it is a helper
The ML model is a pairwise classifier for two agents:

- `same_exact_address`
- `address_similarity_score`
- `same_zone`
- `compatible_zone`
- `same_operation`
- `same_site`
- `same_time`
- `same_date`
- `same_block`
- `fuzzy_address_score`
- etc.

It learns from historical data whether two agents should be grouped together.

This is a deliberate design:

- the business rules do the structural grouping
- ML provides ranking and preference only
- final assignment remains constrained by compatibility rules

Why this matters:

- better safety
- easier debugging
- less chance of weird AI-driven grouping

### 2.7 `train.py` exposes the learning loop
Training is built around historical or corrected Excel data with known taxi assignments. The model is trained from pairwise examples derived inside same date/time blocks.

Why the model is pairwise and block-based:

- grouping decisions are relative, not absolute
- two agents are judged against each other
- blocks avoid comparing across unrelated dispatches

This is a very sensible design for taxi dispatch problems.

## 3) Detailed explanation of the actual flow inside `grouper.py`

### 3.1 `enrich_zones()`
This function extends each row with computed geographical information:

- `CleanAddress`
- `DetectedDestination`
- `DestinationZone`
- `MatchedAlias`
- `DestinationStatus`
- `NeedsManualValidation`

Why: group decisions must be based on normalized, canonical data, not raw text.

### 3.2 `group_agents()`
This is the orchestrator.

It does the following:

- cleans empty rows
- enriches data with destination info
- tracks original order for stable output
- loads the model if `use_ml` is enabled
- warns if no model exists
- groups each dispatch block independently
- then applies final validation

Why blocks matter:

- agents should usually be grouped within same dispatch context
- time, type, or operation based blocks reduce invalid cross-block combinations

### 3.3 `_iter_dispatch_blocks()` and `_block_columns()`
The code groups by a small set of business-related columns such as time and type of course.

Why:

- grouping should only happen inside the same operational flow
- you do not want morning dispatch and evening dispatch mixed together
- this preserves context and avoids weird cross-block taxi assignments

### 3.4 `_group_block()`
This function is the most important piece of the grouping logic.

It splits rows into:

- known groupable items
- review items (unknown or ambiguous)

For known items, it creates destination-based partial groups. Then it tries to fill those groups with other compatible partial groups.

This approach is a hybrid of:

- greedy grouping
- zone compatibility logic
- partial-group optimization

This is why it works well for a capacity of 4.

### 3.5 `_create_destination_groups()`
This creates buckets by:

- destination zone
- detected destination

Then it sorts within each bucket using ML, if available.

This ensures that within a same-destination bucket, the model ranks the most likely pairings first.

### 3.6 `_fill_partials()`
This is where partial taxis are filled.

The code tries to fill an incomplete group using:

- same-zone donors first
- then compatible-zone donors

Why this is important:

- it avoids creating taxis with mixed incompatible neighborhoods
- it allows filling when a destination bucket is not large enough to form a full taxi

### 3.7 `_can_add_to_group()`
This is the hard safety gate.

It checks whether a candidate can be added to a taxi by ensuring:

- candidate is known and valid
- zones are compatible
- destinations are compatible

This is the single most important validation rule.

If this function fails, the candidate is never added, regardless of how strong the ML score is.

### 3.8 `_group_zones_valid()`
This validates the final taxi after group assembly.

It checks:

- all zones in the taxi are compatible
- all destinations in the taxi are compatible
- unknown zones are treated carefully

This prevents impossible combinations from being exported.

### 3.9 `validate_dispatch()`
This is the final output safety check.

It validates:

- no empty taxi values
- capacity limit of 4
- multiple times in one taxi are rejected
- multiple dispatch types in one taxi are rejected
- duplicated matricules are flagged
- incompatible destinations/zones are rejected

Why this is strong:

- it protects against bad assignments before Excel export
- it catches issues that could otherwise silently disturb dispatch operations

## 4) Why the code chooses specific structures

### 4.1 Capacity is fixed at 4
`MAX_TAXI_CAPACITY = 4` is a direct domain rule.

The project uses this as a hard business limit and enforces it throughout the pipeline.

This is not a random number; it is a domain constraint of the business process.

### 4.2 Zone compatibility is encoded explicitly
The project does not infer compatibility from ML only. It uses static compatibility maps.

This is good for governance:

- business teams can understand and adjust the rules
- the logic is explainable
- consequences of rule changes are easier to reason about

### 4.3 Unknown destinations are separated from main logic
The system does not “guess” aggressively. It pushes uncertain addresses into a review flow.

This is a very important quality decision in a scheduling system, because wrong grouping is more expensive than manual review.

### 4.4 Pairwise ML is used only as a ranking tool
The design avoids a dangerous pattern of letting ML decide final group membership without guardrails.

This is one of the strongest engineering choices in the project.

### 4.5 The pipeline is deterministic and auditable
The logic uses:

- textual cleaning
- canonical zone assignment
- explicit compatibility rules
- group validation

This makes it much easier to explain why a given taxi was built.

## 5) Main improvement opportunities

### Priority 1: make rule configuration explicit and data-driven
Current issue:
- compatibility rules are embedded in Python dictionaries and heuristics
- changes require code edits

Improvement:
- move compatibility and policy data into YAML/JSON config files
- allow domain experts to tune rules without code deployment

Example:
- `zone_compatibility.json`
- `destination_compatibility.json`
- `grouping_policy.json`

This is valuable because business rules may change by city, month, or client.

### Priority 2: add structured experiment tracking for ML
Current issue:
- model training exists, but there is no clear experiment registry

Improvement:
- store model version, feature list, train date, metrics, source dataset, and performance by zone
- log both positive and negative pair counts
- compare rule-based vs ML-assisted outcomes on a validation set

This will turn the model from a useful artifact into a managed production asset.

### Priority 3: create a formal scoring/decision pipeline for each candidate taxi
Current issue:
- grouping is mostly greedy and heuristic
- there is no explicit optimization objective

Improvement:
- define an objective such as:
  - maximize same-destination pairs
  - minimize mixed-zone taxis
  - maximize capacity utilization
  - minimize manual review queue
- use local search / assignment optimization after initial greedy placement

This could significantly improve grouping quality while preserving safety.

### Priority 4: improve unknown destination recovery
Current issue:
- the system flags unknowns but does not strongly reuse them

Improvement:
- add a learning loop for manual corrections
- persist corrections into a training dataset
- automatically update alias maps and known destinations

This would improve the core quality of destination detection over time.

### Priority 5: separate “business rules” from “ML ranking” more cleanly
Current issue:
- some functions blur responsibilities

Improvement:
- define strict layers:
  - ingestion
  - normalization
  - compatibility
  - grouping
  - ML ranking
  - validation
  - export

This will make the system easier to test, maintain, and extend.

### Priority 6: add more explicit invariants and tests
Current issue:
- there is a lot of safety logic in runtime checks, but fewer formal tests around edge cases

Improvement:
- add tests for:
  - same destination but different zones
  - unknown zone with compatibility failure
  - over-capacity taxi edge cases
  - review-queue handling
  - mixed dispatch type blocks

This is especially important for a taxi-planning tool where bad assignment can have operational cost.

### Priority 7: add explainability for each taxi group
Current issue:
- there are reasons like `same_destination` and `compatible_zone_fill`, but they are not fully traceable to the exact pair choices

Improvement:
- create per-taxi explanation records:
  - group id
  - destination composition
  - zone compatibility summary
  - ML score average
  - manual review count
  - rule path used

This helps operations teams trust and debug the output.

## 6) Summary of the strongest design choices

The project is strongest in these areas:

- safety-first grouping rules
- explicit geographic compatibility logic
- conservative handling of unknown data
- pairwise ML as a helper rather than a decision-maker
- final validation before export

These are the features that make the solution practical in a real dispatch environment.

## 7) Main weakness to watch

The main risk is not the model itself. It is the growing complexity of heuristic rules and ad hoc business adjustments.

As the project grows, the biggest improvement will not be “more ML.” It will be:

- more explicit policy management
- cleaner rule configuration
- better observability
- more testable decision logic

## 8) Recommended next actions

1. read `main.py`, `preprocessing.py`, `zones.py`, `destination_cleaner.py`, `grouper.py`, `ml_model.py` in that exact order
2. create a single canonical specification for grouping rules
3. separate rule configuration from code
4. add a validation dashboard for outputs
5. start building a traceable ML experiment log

This will turn the project from a strong prototype into a maintainable operational system.
