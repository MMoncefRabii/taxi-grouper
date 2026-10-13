Canonical JSONL format for captured user corrections
===============================================

One JSON object per line. Each object captures a single corrected assignment (one row change).

Example line (from a recent simulated run):

{"row_index": 0, "before": "2", "after": "7779", "row_data": {"Adresse": "123 Main St", "Groupe Taxi": "7779", "Date": "2026-07-01"}}

Fields:
- `row_index`: index of the row in the pre/post DataFrame (int or original index key).
- `before`: the model's original assignment (string).
- `after`: the user-corrected assignment (string).
- `row_data`: the full post-correction row as a JSON object (all columns with corrected values).

Storage location:
- Default file: `data/auto_training_corrections.jsonl` (one JSON per line).
- Backcompat fallback (legacy): `data/training_files/auto_corrections.xlsx`.

Guidance on avoiding noisy examples (cosmetic renumbering):
- Current extractor treats any `before != after` as a correction.
- To avoid training on purely cosmetic renumbering (e.g., group label changes that don't alter cluster membership), apply a semantic check before persisting:
  - Compute a lightweight fingerprint of the group's content (e.g., sorted addresses or a hash of representative features).
  - Only persist the example when the fingerprint of the `before` group differs from the fingerprint of the `after` group, indicating a true re-assignment of rows between clusters rather than a relabel.
  - Alternatively, require that multiple rows from the same original group changed membership (increase precision at cost of recall).

If you want, I can implement a minimal semantic-check heuristic in `extract_training_examples_from_corrections` that records examples only when the fingerprint differs.
