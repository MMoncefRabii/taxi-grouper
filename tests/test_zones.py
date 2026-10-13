from src.core.zones import detect_zone, normalize_address


def test_zone_variants():
    assert detect_zone("Rue 18 janvier Ettadhamen").zone_code == "G"
    assert detect_zone("Hammem Lif").zone_code == "A"
    assert detect_zone("Madina Jadida").zone_code == "B"
    assert detect_zone("Nkhilet").zone_code == "I"


def test_hammam_and_denden_variants():
    for value in ["Hammam Chat", "hammam chatt", "Hamem el Chatt", "Hammem Linf", "HAMMAM LINF"]:
        assert detect_zone(value).zone_code == "A"
    for value in ["denden", "Denden", "DENDEN", "den den", "dendn"]:
        match = detect_zone(value)
        assert match.zone_code == "F"
        assert match.normalized_address == "danden"


def test_raoued_beats_generic_ariana():
    match = detect_zone("Sidi Amor route Raoued, Ariana")
    assert match.zone_code == "I"
    assert match.normalized_address == "raoued"


def test_megrine_beats_cite_chaker_when_address_is_megrine():
    match = detect_zone("10 rue al Amal Magrine cité Chaker Megrine 2024 Ben Arous, Megrine")
    assert match.zone_code == "B"


def test_unknown_zone():
    match = detect_zone("Adresse totalement inconnue")
    assert match.zone_code == "UNKNOWN"
    assert match.confidence == 0


def test_normalize_address():
    assert normalize_address("Hammam-Lif!!") == "hammam lif"
