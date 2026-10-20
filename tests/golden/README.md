# Golden dispatch-day snapshot

`expected_groups.json` is the accepted, rule-based partition for the
anonymized 110-agent fixture in `../fixtures/golden_day.xlsx`. It protects the
grouping rules from silently changing a client-accepted result: every agent
must be assigned once, no taxi may exceed four agents, validation must remain
clean, and the row-position partition must match the snapshot.

The snapshot was generated only after comparing `group_agents(use_ml=False)`
on the original workbook's `Feuille 1` and the anonymized workbook in memory.
The address replacements retain detected destination labels and use synthetic
ordering tokens so that rule-based ordering remains equivalent; unknown
destinations use generic synthetic filler. Five operation values occurring
once were generalized.

To regenerate after an approved rule change, first review the new behavior and
obtain approval. Then deliberately run:

```powershell
python tests/test_golden_day.py --regenerate-expected-groups
```

The command requires the explicit `--regenerate-expected-groups` flag, reads
only the committed anonymized fixture, runs with ML disabled, checks the
invariants, and replaces the JSON snapshot. It is never run automatically by
the tests. Review the resulting JSON diff before committing it.

The tracked `data/destination_aliases.json` file is an empty JSON object
(3 bytes). It is sufficient as the manual-alias file: destination detection
uses the built-in `DESTINATION_ALIASES` in
`src/core/destination_detector.py`; no ignored data or model files are needed
for these tests.
