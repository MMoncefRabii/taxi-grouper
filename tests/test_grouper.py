import pandas as pd

from src.config import GrouperConfig
from src.core.grouper import _parse_dispatch_dates, group_agents as _group_agents, validate_dispatch, validate_groups
from src.core.preprocessing import detect_columns


def group_agents(df, columns=None, **kwargs):
    """Keep existing rule tests on one valid dispatch block."""
    df = df.copy()
    if "Date" not in df.columns:
        df["Date"] = "2026-05-28"
    if "SourceDispatchID" not in df.columns:
        df["SourceDispatchID"] = "legacy.xlsx | Sheet1 | 1"
    return _group_agents(df, columns=columns or detect_columns(df), **kwargs)


def test_ambiguous_day_first_date_is_april_3():
    parsed = _parse_dispatch_dates(pd.Series(["03/04/2026"]))

    assert parsed.iloc[0] == pd.Timestamp("2026-04-03")


def test_day_first_date_after_day_twelve_is_april_13():
    parsed = _parse_dispatch_dates(pd.Series(["13/04/2026"]))

    assert parsed.iloc[0] == pd.Timestamp("2026-04-13")


def test_iso_date_is_parsed_as_april_3():
    parsed = _parse_dispatch_dates(pd.Series(["2026-04-03"]))

    assert parsed.iloc[0] == pd.Timestamp("2026-04-03")


def test_day_first_option_is_configurable():
    parsed = _parse_dispatch_dates(pd.Series(["03/04/2026"]), day_first=False)

    assert parsed.iloc[0] == pd.Timestamp("2026-03-04")


def test_day_first_option_is_available_in_grouper_config():
    df = pd.DataFrame(
        {
            "Date": ["03/04/2026", "2026-03-04"],
            "SourceDispatchID": ["dispatch-A"] * 2,
            "Nom": ["Agent 1", "Agent 2"],
            "Adresse": ["Ariana"] * 2,
            "Heure": ["07:00"] * 2,
        }
    )

    grouped, _warnings = _group_agents(
        df,
        detect_columns(df),
        config=GrouperConfig(day_first=False),
        use_ml=False,
    )

    assert grouped["Groupe Taxi"].nunique() == 1


def test_datetime_date_value_is_preserved():
    value = pd.Timestamp("2026-04-03 14:25:36")

    parsed = _parse_dispatch_dates(pd.Series([value]))

    assert parsed.iloc[0] == value


def test_excel_serial_date_is_converted_from_excel_epoch():
    parsed = _parse_dispatch_dates(pd.Series([46115]))

    assert parsed.iloc[0] == pd.Timestamp("2026-04-03")


def test_grouping_never_exceeds_four():
    df = pd.DataFrame(
        {
            "Nom - Prenom": [f"Agent {i}" for i in range(10)],
            "Adresse": ["Ettadhamen"] * 5 + ["Mnihla"] * 3 + ["Raoued"] * 2,
            "Heure": ["07:00"] * 10,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    validate_groups(grouped)
    assert grouped.groupby("Groupe Taxi").size().max() <= 4


def test_same_time_and_course_on_different_dates_never_share_a_taxi():
    df = pd.DataFrame(
        {
            "Date": ["2026-05-28"] * 2 + ["2026-05-29"] * 2,
            "SourceDispatchID": ["dispatch-A"] * 4,
            "Nom": ["A1", "A2", "B1", "B2"],
            "Adresse": ["Ariana"] * 4,
            "Heure": ["07:00"] * 4,
            "Type de course": ["Ramassage"] * 4,
        }
    )

    grouped, _warnings = _group_agents(df, detect_columns(df), use_ml=False)
    taxis_by_date = grouped.groupby("Date")["Groupe Taxi"].apply(set)

    assert taxis_by_date["2026-05-28"].isdisjoint(taxis_by_date["2026-05-29"])


def test_same_date_time_and_course_with_different_dispatch_ids_never_share_a_taxi():
    df = pd.DataFrame(
        {
            "Date": ["2026-05-28"] * 4,
            "SourceDispatchID": ["dispatch-A"] * 2 + ["dispatch-B"] * 2,
            "Nom": ["A1", "A2", "B1", "B2"],
            "Adresse": ["Ariana"] * 4,
            "Heure": ["07:00"] * 4,
            "Type de course": ["Ramassage"] * 4,
        }
    )

    grouped, _warnings = _group_agents(df, detect_columns(df), use_ml=False)
    taxis_by_dispatch = grouped.groupby("SourceDispatchID")["Groupe Taxi"].apply(set)

    assert taxis_by_dispatch["dispatch-A"].isdisjoint(taxis_by_dispatch["dispatch-B"])


def test_validate_dispatch_rejects_external_taxi_with_multiple_dates():
    df = pd.DataFrame(
        {
            "Date": ["2026-05-28", "2026-05-29"],
            "SourceDispatchID": ["dispatch-A"] * 2,
            "Groupe Taxi": [1, 1],
            "Adresse": ["Ariana"] * 2,
            "Zone": ["A"] * 2,
            "DetectedDestination": ["Ariana"] * 2,
        }
    )

    validation = validate_dispatch(df)

    assert not validation["valid"]
    assert any("multiple dates" in error.lower() for error in validation["errors"])


def test_validate_dispatch_rejects_external_taxi_with_multiple_source_blocks():
    df = pd.DataFrame(
        {
            "Date": ["2026-05-28"] * 2,
            "SourceDispatchID": ["dispatch-A", "dispatch-B"],
            "Groupe Taxi": [1, 1],
            "Adresse": ["Ariana"] * 2,
            "Zone": ["A"] * 2,
            "DetectedDestination": ["Ariana"] * 2,
        }
    )

    validation = validate_dispatch(df)

    assert not validation["valid"]
    assert any("multiple source dispatch ids" in error.lower() for error in validation["errors"])


def test_missing_or_unparseable_date_and_missing_dispatch_id_are_unassigned():
    df = pd.DataFrame(
        {
            "Date": [None, "not-a-date", "2026-05-28"],
            "SourceDispatchID": ["dispatch-A", "dispatch-A", None],
            "Nom": ["Missing date", "Invalid date", "Missing dispatch"],
            "Adresse": ["Ariana"] * 3,
            "Heure": ["07:00"] * 3,
        }
    )

    grouped, _warnings = _group_agents(df, detect_columns(df), use_ml=False)

    assert grouped["Groupe Taxi"].isna().all()
    assert grouped["UnassignedReason"].tolist() == ["MISSING_DATE", "MISSING_DATE", "MISSING_DISPATCH_ID"]


def test_same_dispatch_block_still_groups_normally():
    df = pd.DataFrame(
        {
            "Date": ["2026-05-28"] * 4,
            "SourceDispatchID": ["dispatch-A"] * 4,
            "Nom": [f"Agent {i}" for i in range(4)],
            "Adresse": ["Ariana"] * 4,
            "Heure": ["07:00"] * 4,
            "Type de course": ["Ramassage"] * 4,
        }
    )

    grouped, _warnings = _group_agents(df, detect_columns(df), use_ml=False)

    assert grouped["Groupe Taxi"].nunique() == 1
    assert grouped.groupby("Groupe Taxi")["Nom"].apply(set).to_dict() == {
        1: {"Agent 0", "Agent 1", "Agent 2", "Agent 3"}
    }
    assert grouped["UnassignedReason"].eq("").all()


def test_unparseable_date_is_unassigned_with_missing_date_reason():
    df = pd.DataFrame(
        {
            "Date": ["04/31/2026"],
            "SourceDispatchID": ["dispatch-A"],
            "Nom": ["Invalid date"],
            "Adresse": ["Ariana"],
            "Heure": ["07:00"],
        }
    )

    grouped, _warnings = _group_agents(df, detect_columns(df), use_ml=False)

    assert pd.isna(grouped.loc[0, "Groupe Taxi"])
    assert grouped.loc[0, "UnassignedReason"] == "MISSING_DATE"


def test_unknown_not_mixed_with_known():
    df = pd.DataFrame({"Nom": ["A", "B"], "Adresse": ["Unknown place", "Ariana"]})
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    assert grouped["Groupe Taxi"].nunique() == 2


def test_errafeha_groups_with_ibn_khaldoun_family_not_sidi_hssine():
    df = pd.DataFrame(
        {
            "Nom": ["Errafeha", "Ibn", "Omrane", "Mnihla", "Sidi"],
            "Adresse": ["cite errafeha ariana", "ibn khaldou", "omrane sup", "mnihla", "sidi hsin"],
            "Heure": ["07:00"] * 5,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    taxi_by_destination = grouped.groupby("DetectedDestination")["Groupe Taxi"].apply(set).to_dict()
    errafeha_taxis = taxi_by_destination["Cite Errafeha"]
    assert not errafeha_taxis.isdisjoint(taxi_by_destination["Ibn Khaldoun"])
    assert not errafeha_taxis.isdisjoint(taxi_by_destination["Omrane"])
    assert errafeha_taxis.isdisjoint(taxi_by_destination["Sidi Hssine"])


def test_jaafer_family_stays_away_from_soukra():
    df = pd.DataFrame(
        {
            "Nom": ["Jaafer", "Nour", "Ghazela", "Petite", "Soukra"],
            "Adresse": ["jaafer", "nour jaafer", "ghazela", "ariana petite", "soukra"],
            "Heure": ["07:00"] * 5,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    taxi_by_destination = grouped.groupby("DetectedDestination")["Groupe Taxi"].apply(set).to_dict()
    jaafer_taxis = taxi_by_destination["Jaafer"]
    assert not jaafer_taxis.isdisjoint(taxi_by_destination["Ghazela"])
    assert not jaafer_taxis.isdisjoint(taxi_by_destination["Ariana Soghra"])
    assert jaafer_taxis.isdisjoint(taxi_by_destination["Soukra"])


def test_soukra_never_groups_with_ghazela_family():
    df = pd.DataFrame(
        {
            "Nom": ["Soukra", "Ghazela", "Gazelle", "Jaafer", "Nour"],
            "Adresse": ["soukra", "ghazela", "cite gazelle", "jaafer", "nour jaafer"],
            "Heure": ["07:00"] * 5,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    taxi_by_destination = grouped.groupby("DetectedDestination")["Groupe Taxi"].apply(set).to_dict()
    assert taxi_by_destination["Soukra"].isdisjoint(taxi_by_destination["Ghazela"])
    assert taxi_by_destination["Soukra"].isdisjoint(taxi_by_destination["Jaafer"])
    assert not taxi_by_destination["Jaafer"].isdisjoint(taxi_by_destination["Ghazela"])


def test_ghazela_can_complete_with_ariana_family():
    df = pd.DataFrame(
        {
            "Nom": ["Ghazela", "Ariana 1", "Ariana 2", "Ariana 3"],
            "Adresse": ["cite el ghazala", "ariana", "ariana", "ariana"],
            "Heure": ["07:00"] * 4,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    assert grouped["Groupe Taxi"].nunique() == 1
    assert set(grouped["DetectedDestination"]) == {"Ghazela", "Ariana"}


def test_ghazela_is_preferred_with_three_ariana_rows():
    df = pd.DataFrame(
        {
            "Nom": ["Ariana 1", "Ariana 2", "Ariana 3", "Gazelle", "Ghazela", "Jaafer"],
            "Adresse": ["ariana", "ariana", "ariana", "cite la gazelle", "cite el ghazala", "nour jaafer"],
            "Heure": ["07:00"] * 6,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    ghazela_taxi = grouped[grouped["DetectedDestination"].eq("Ghazela")]["Groupe Taxi"].iloc[0]
    taxi_destinations = grouped[grouped["Groupe Taxi"].eq(ghazela_taxi)]["DetectedDestination"].tolist()
    assert taxi_destinations.count("Ariana") == 3
    assert "Ghazela" in taxi_destinations


def test_mornaguia_can_complete_with_oued_lil():
    df = pd.DataFrame(
        {
            "Nom": ["Mornaguia 1", "Mornaguia 2", "Mornaguia 3", "Oued"],
            "Adresse": ["mornaguia", "mornaguia", "mornaguia", "oued ellil manouba"],
            "Heure": ["07:00"] * 4,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    assert grouped["Groupe Taxi"].nunique() == 1
    assert set(grouped["DetectedDestination"]) == {"Mornaguia", "Oued Lil"}


def test_bortal_is_ksar_said_and_can_fill_with_bardo_zone():
    df = pd.DataFrame(
        {
            "Nom": ["Bortal", "Bardo"],
            "Adresse": ["bortal", "bardo"],
            "Heure": ["07:00", "07:00"],
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    assert grouped["DetectedDestination"].tolist() == ["Bardo", "Ksar Said"] or grouped["DetectedDestination"].tolist() == ["Ksar Said", "Bardo"]
    assert grouped["DestinationZone"].eq("F").all()
    assert grouped["Groupe Taxi"].nunique() == 1


def test_same_destination_remainder_stays_together_before_zone_fill():
    df = pd.DataFrame(
        {
            "Nom": [f"Rades {i}" for i in range(6)] + ["Medina", "Ezzahra"],
            "Adresse": [
                "rades",
                "cite med ali rades",
                "rades plage",
                "rue hannibal rades",
                "rades med ali",
                "rades centre",
                "medina jedida",
                "zahra",
            ],
            "Heure": ["07:00"] * 8,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    rades_groups = grouped[grouped["DetectedDestination"].eq("Radès")].groupby("Groupe Taxi").size().sort_values().tolist()
    assert rades_groups == [2, 4]


def test_mourouj_variants_are_same_destination_and_stay_together():
    df = pd.DataFrame(
        {
            "Nom": [f"Mourouj {i}" for i in range(6)],
            "Adresse": ["mourouj 2", "mourouj 4", "mourouj 5", "mourouj 6", "mourouj 7", "el mourouj 7"],
            "Heure": ["07:00"] * 6,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    assert grouped["DetectedDestination"].eq("El Mourouj").all()
    mourouj_groups = grouped.groupby("Groupe Taxi").size().sort_values().tolist()
    assert mourouj_groups == [2, 4]


def test_destination_remainder_is_not_split_when_filling_zone():
    df = pd.DataFrame(
        {
            "Nom": [f"Mourouj {i}" for i in range(6)] + ["Naasen 1", "Naasen 2", "Kabaria"],
            "Adresse": ["mourouj 2", "mourouj 4", "mourouj 5", "mourouj 6", "mourouj 7", "el mourouj 7", "naasen", "naasen", "kabaria"],
            "Heure": ["07:00"] * 9,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    remainder_taxis = grouped[grouped["DetectedDestination"].eq("El Mourouj")].groupby("Groupe Taxi").size().sort_values().tolist()
    assert remainder_taxis == [2, 4]


def test_destination_remainder_fills_with_same_zone_destination():
    df = pd.DataFrame(
        {
            "Nom": [f"Agent {i}" for i in range(8)],
            "Adresse": ["denden"] * 6 + ["bardo"] * 2,
            "Heure": ["07:00"] * 8,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    sizes = sorted(grouped.groupby("Groupe Taxi").size().tolist())
    assert sizes == [4, 4]
    mixed = grouped.groupby("Groupe Taxi")["DetectedDestination"].apply(lambda values: set(values)).tolist()
    assert {"Danden"} in mixed
    assert {"Danden", "Bardo"} in mixed


def test_small_same_zone_destinations_merge_to_full_taxi():
    df = pd.DataFrame(
        {
            "Nom": ["Aouina 1", "Aouina 2", "Lac", "Ain"],
            "Adresse": ["aouina", "aouina", "lac 2", "ain zaghouen"],
            "Heure": ["07:00"] * 4,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    assert grouped["Groupe Taxi"].nunique() == 1
    assert set(grouped["DetectedDestination"]) == {"Aouina", "Lac 2", "Ain Zaghouen"}


def test_destination_overrides_inside_same_zone_f():
    df = pd.DataFrame(
        {
            "Nom": ["Ibn 1", "Ibn 2", "Sidi", "Zah"],
            "Adresse": ["ibn khaldoun", "ibn khaldou", "sidi hsin", "zahrouni"],
            "Heure": ["07:00"] * 4,
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    taxi_by_destination = grouped.groupby("DetectedDestination")["Groupe Taxi"].apply(set).to_dict()
    assert taxi_by_destination["Ibn Khaldoun"].isdisjoint(taxi_by_destination["Sidi Hssine"])
    assert taxi_by_destination["Ibn Khaldoun"].isdisjoint(taxi_by_destination["Zahrouni"])
    assert not taxi_by_destination["Sidi Hssine"].isdisjoint(taxi_by_destination["Zahrouni"])


def test_rades_not_grouped_with_mornaguia():
    df = pd.DataFrame(
        {
            "Nom": ["Rades", "Mornaguia"],
            "Adresse": ["cite med ali rades", "mornaguia"],
            "Heure": ["07:00", "07:00"],
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    assert grouped["DetectedDestination"].tolist() == ["Radès", "Mornaguia"]
    assert grouped["Groupe Taxi"].nunique() == 2
