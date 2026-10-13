import pandas as pd

from src.core.destination_cleaner import clean_destination_text, detect_clean_destination, validate_cleaned_destinations
from src.core.grouper import group_agents
from src.core.preprocessing import detect_columns


def assert_clean_destination(address, destination, zone):
    result = detect_clean_destination(address)
    assert result["detected_destination"] == destination
    assert result["zone"] == zone
    assert result["similarity_score"] >= 85
    assert result["validation_status"] == "valid"


def test_clean_destination_text_examples():
    assert clean_destination_text("Rue *** Denden") == "denden"
    assert clean_destination_text("AVENUE Habib Bourguiba DANDEN") == "habib bourguiba danden"
    assert clean_destination_text("Cite La Gazelle") == "gazelle"
    assert clean_destination_text("Hammam-Lif") == "hammam lif"
    assert clean_destination_text("D enden") == "denden"
    assert clean_destination_text("d e n d e n") == "denden"


def test_detect_clean_destination_examples():
    examples = [
        ("denden", "Danden", "F"),
        ("dAnden", "Danden", "F"),
        ("d enden", "Danden", "F"),
        ("dnden", "Danden", "F"),
        ("rue sdjksj denden", "Danden", "F"),
        ("rue danden", "Danden", "F"),
        ("hammam-lif", "Hammam Lif", "A"),
        ("hamem lif", "Hammam Lif", "A"),
        ("nkhilet", "Nkhilette", "I"),
        ("ariana soghra", "Ariana Soghra", "I"),
        ("lac2", "Lac 2", "K"),
        ("cite la gazelle", "Cité La Gazelle", "H"),
        ("medina jadida", "Medina Jedida", "B"),
        ("bhar lazrag", "Bhar Lazreg", "J"),
        ("oued lil manouba", "Oued Lil", "G"),
        ("oued ellil manouba", "Oued Lil", "G"),
        ("cite med ali rades", "Radès", "B"),
        ("ibn khaldou", "Ibn Khaldoun", "F"),
        ("cite errafeha ariana", "Cite Errafeha", "F"),
        ("rafeha", "Cite Errafeha", "F"),
        ("jaafer", "Jaafer", "I"),
        ("nour jaafer", "Jaafer", "I"),
        ("ghazela", "Ghazela", "H"),
        ("ghazala", "Ghazela", "H"),
        ("gazelle", "Ghazela", "H"),
        ("cite ghazela", "Ghazela", "H"),
        ("ariana jaafer", "Jaafer", "I"),
        ("bortal", "Ksar Said", "F"),
        ("ariana petite", "Ariana Soghra", "I"),
        ("petite ariana", "Ariana Soghra", "I"),
    ]
    for address, destination, zone in examples:
        assert_clean_destination(address, destination, zone)


def test_grouping_uses_clean_destination_columns():
    df = pd.DataFrame(
        {
            "Date": ["2026-05-29", "2026-05-29"],
            "Matricule": [1, 2],
            "Nom - Prénom": ["A", "B"],
            "Opération": ["OP", "OP"],
            "Site": ["S", "S"],
            "Adresse": ["d enden", "rue sdjksj denden"],
            "Heure d'arrivée": ["07:00", "07:00"],
            "Taxi": [999, 1000],
        }
    )
    grouped, _warnings = group_agents(df, detect_columns(df), use_ml=False)
    assert grouped["DetectedDestination"].tolist() == ["Danden", "Danden"]
    assert grouped["DestinationZone"].tolist() == ["F", "F"]
    assert grouped["DestinationStatus"].tolist() == ["valid", "valid"]
    assert grouped["Groupe Taxi"].nunique() == 1
    assert grouped["Taxi"].astype(str).str.strip().eq("").all()


def test_validate_cleaned_destinations_counts():
    df = pd.DataFrame(
        {
            "CleanAddress": ["denden", "unknown area"],
            "DestinationStatus": ["valid", "unknown"],
        }
    )
    result = validate_cleaned_destinations(df)
    assert result["total_rows"] == 2
    assert result["valid_destinations"] == 1
    assert result["unknown_destinations"] == 1
