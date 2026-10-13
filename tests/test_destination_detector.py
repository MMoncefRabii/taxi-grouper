from src.core.destination_detector import detect_destination, normalize_address


def assert_destination(address, destination, zone):
    result = detect_destination(address)
    assert result["destination"] == destination
    assert result["zone"] == zone
    assert result["confidence"] >= 85


def test_normalize_address_examples():
    assert normalize_address("Rue *** Déndèn") == "rue denden"
    assert normalize_address("Hammam-Lif") == "hammam lif"
    assert normalize_address("Cité La Gazelle") == "cite la gazelle"
    assert normalize_address("Nkhilétté") == "nkhilette"


def test_destination_examples():
    assert_destination("Danden", "Danden", "F")
    assert_destination("Denden", "Danden", "F")
    assert_destination("dnden", "Danden", "F")
    assert_destination("rue mohamed ali denden", "Danden", "F")
    assert_destination("Hammam-Lif", "Hammam Lif", "A")
    assert_destination("hamem lif", "Hammam Lif", "A")
    assert_destination("nkhilet", "Nkhilette", "I")
    assert_destination("Ariana soghra", "Ariana Soghra", "I")
    assert_destination("la marsa", "La Marsa", "J")
    assert_destination("lac2", "Lac 2", "K")
    assert_destination("cite la gazelle", "Cité La Gazelle", "H")


def test_unknown_destination():
    result = detect_destination("destination totalement imaginaire")
    assert result["destination"] == "UNKNOWN"
    assert result["zone"] == "UNKNOWN"
    assert result["method"] == "unknown"
