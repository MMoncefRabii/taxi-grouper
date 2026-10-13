"""Grand Tunis zones, address normalization, and zone detection."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process
from unidecode import unidecode

from ..config import UNKNOWN_ZONE, ZONE_COMPATIBILITY


@dataclass(frozen=True)
class ZoneMatch:
    zone_code: str
    zone_name: str
    matched_alias: str
    confidence: float
    normalized_address: str


ZONE_NAMES: dict[str, str] = {
    "A": "Sud-Est cotier",
    "B": "Sud interieur",
    "D": "Sud-Ouest",
    "E": "Centre-Ville",
    "F": "Bardo / Ouest",
    "G": "Nord-Ouest / Ettadhamen",
    "H": "Ariana",
    "I": "Ariana Nord",
    "J": "Cote Nord",
    "K": "Lac / Carthage",
    UNKNOWN_ZONE: "Unknown",
}

ZONE_ALIASES: dict[str, list[str]] = {
    "A": ["Borj Cedria", "Hammam Chat", "Hammam Chatt", "Hamem el Chatt", "Hammem Chatt", "Hammam Lif", "Hammam-Lif", "Hammem Lif", "Hammam Linf", "Hammem Linf", "Hammam Lenf", "Hammem Lenf", "Ezzahra", "Zahra", "Yasminette", "Bir Bay", "Bir El Bey"],
    "B": ["Rades", "Radès", "Cite Med Ali Rades", "Cité Med Ali Rades", "Cite Mohamed Ali Rades", "Medina Jedida", "Madina Jadida", "Mégrine", "Megrine", "Mornag", "Boumhal"],
    "D": ["Mhamdia", "Fouchana", "Fouchena", "Mourouj 1", "Mourouj 2", "Mourouj 3", "Mourouj 4", "Mourouj 5", "Mourouj 6", "El Mourouj", "Naasen", "Ibn Sina", "Ibnou Sina", "Wardia", "Ouardia", "Wardeia", "Diboz Ville", "Diboz", "Kabaria", "Cité Hlel", "Cite Hlel", "Saida", "Montfleury", "Belle Vue", "Bellevue", "Cité Elfath", "Cite Elfath", "Cité Olympique", "Cite Olympique", "Olympique"],
    "E": ["Lafayette", "Passage", "Centre Ville", "Centre-Ville", "Tunis Centre", "Cité Khadhra", "Cite Khadhra", "Avenue Madrid", "Rue Madrid", "Rue de Madrid", "Beb Khadhra", "Bab Khadhra", "Attaoufik", "Sidi El Bachir", "Beb Souika", "Bab Souika", "Nouvelle Medina", "Beb Dzira", "Bab Dzira"],
    "F": ["Manouba", "Kobbet Ennhass", "Danden", "Denden", "Den Den", "Dendn", "Dendne", "Dandenne", "Khaznadar", "Bardo", "Sidi Hsin", "Sidi Hssine", "Zahrouni", "Zouhour", "Cité Ezzouhour", "Cite Ezzouhour", "Beb Saadoun", "Bab Saadoun", "Omrane", "Omrane Supérieur", "Omrane Superieur", "Agba", "Diar Ben Mahmoud", "Mornageya", "10 Décembre", "10 Decembre", "Monoprix 10", "Tebourba", "Ksar Said"],
    "G": ["Ettadhamen", "Tadhamen", "Thadhamen", "Mnihla", "Bassatine", "Hay Bassatine", "Tahrir", "Ettahrir", "Intilaka", "Entileka", "Manar", "Menzah 1", "Menzah 2", "Menzah 3", "Menzah 4", "Menzah 5", "Menzah 6", "Menzah 7", "Manzah", "Ennasr", "Zayatine", "Zayetin", "Douar Hicher", "Jdaida", "Djedaida", "Jedaida", "Bjeoua", "Oued Lil", "Oued Lil Manouba", "Nogra", "Beb Menara", "Bab Menara", "Jardin Lmanzah", "Nasseer"],
    "H": ["Ariana Centre", "Ariana Nouvelle", "Ariana Beb Lahdid", "Ariana Supérieur", "Ariana Superieur", "Ariana", "Cité La Gazelle", "Cite La Gazelle", "Ghazela", "Jaafer", "Jaafar", "Nour Jaafer", "Nour Jaafar", "Cité Etaamir", "Cite Etaamir", "Ettaamir", "Cité Ennasim", "Cite Ennasim", "Cité Mostakbel", "Cite Mostakbel", "Cité Chaker", "Cite Chaker"],
    "I": ["Borj Louzir", "Hedi Nouira", "Nkhilette", "Nkhilet", "Enkhilet", "Ariana Soghra", "Raoued", "Cité Sahha", "Cite Sahha", "Borj Touil", "Kalaat El Andalous", "Kalaat Landalos", "Slimene", "Souk El Khorda"],
    "J": ["La Marsa", "Marsa", "Gammarth", "Sidi Bou Said", "Bhar Lazreg", "Soukra", "Soukra Parc", "Sidi Salah", "Chotrana", "Diar Soukra"],
    "K": ["Kram", "Le Kram", "Carthage", "La Goulette", "Ain Zaghouen", "Aouina", "Dar Fadhal", "Lac 1", "Lac 2", "Les Berges du Lac", "Sidi Daoud", "Jardin de Carthage"],
}

ZONE_ALIASES["E"].extend([
    "Cite El Khadhra",
    "Cité El Khadhra",
    "Rue de Madrid",
    "Madrid",
    "Beb Jdid",
    "Bab Jdid",
    "El Hajjamin",
    "Central Park",
    "Rue du Royaume d Arabie Saoudite",
    "Barcelone",
    "Place Barcelone",
    "Barcelone Poste",
    "Bab Bhar",
    "Beb Bhar",
])
ZONE_ALIASES["B"].extend([
    "Magrine",
    "Magrine Cite Chaker",
    "Magrine Cité Chaker",
    "Megrine Cite Chaker",
    "Jbel Jelloud",
    "Jbal Jloud",
    "Jbal Jelloud",
    "Megrine Cité Chaker",
])
ZONE_ALIASES["F"].extend([
    "Cite Ben Younes",
    "Cité Ben Younes",
    "Ibn Khaldoun",
    "Ibn Khaldou",
    "Ibnou Kholdoun",
    "Ibnou Khouldoun",
    "Ras Tabia",
    "Rass Tabia",
    "Ras ETabia",
])
ZONE_ALIASES["D"].extend([
    "Cite Avicenne",
    "Avicenne",
    "Avicenne Tunis",
    "Cité Avicenne",
    "La Khlideya",
    "Khlideya",
    "Mallasine",
    "Malasine",
    "Mallassine",
])
ZONE_ALIASES["H"].extend([
    "Beb Lahdid",
    "Bab Lahdid",
    "Cité El Ghazala",
    "Cite El Ghazala",
    "Cité Ghazala",
    "Cite Ghazala",
    "El Ghazala",
    "Charguia",
    "Charguia 1",
    "Charguia 2",
    "Rond Point L Escale",
    "Rond Point Escale",
    "L Escale",
])
ZONE_ALIASES["I"].extend([
    "Sidi Amor Route Raoued",
    "Route Raoued",
    "Raoued Ariana",
])

ALIAS_CANONICAL: dict[str, str] = {
    "thadhamen": "ettadhamen",
    "tadhamen": "ettadhamen",
    "hammam chat": "hammam chatt",
    "hammem chat": "hammam chatt",
    "hammem chatt": "hammam chatt",
    "hamem el chatt": "hammam chatt",
    "hammam lif": "hammam lif",
    "hammem lif": "hammam lif",
    "hamem lif": "hammam lif",
    "hammam linf": "hammam lif",
    "hammem linf": "hammam lif",
    "hamem linf": "hammam lif",
    "hammam lenf": "hammam lif",
    "hammem lenf": "hammam lif",
    "h lif": "hammam lif",
    "h lif": "hammam lif",
    "h linf": "hammam lif",
    "denden": "danden",
    "den den": "danden",
    "dendn": "danden",
    "dendne": "danden",
    "dandenne": "danden",
    "nkhilet": "nkhilette",
    "enkhilet": "nkhilette",
    "madina jadida": "medina jedida",
    "madina jedida": "medina jedida",
    "magrine": "megrine",
    "magrine cite chaker": "megrine",
    "megrine cite chaker": "megrine",
    "marsa": "la marsa",
    "zahra": "ezzahra",
    "beb khadhra": "bab khadhra",
    "beb souika": "bab souika",
    "beb dzira": "bab dzira",
    "cite khadhra": "cite khadhra",
    "cite el khadhra": "cite khadhra",
    "cite lkhadhra": "cite khadhra",
    "cita c el khadhra": "cite khadhra",
    "cita c khadhra": "cite khadhra",
    "cita c lkhadhra": "cite khadhra",
    "lkhadhra": "cite khadhra",
    "rue de madrid": "avenue madrid",
    "madrid": "avenue madrid",
    "beb jdid": "beb jdid",
    "bab jdid": "beb jdid",
    "ras tabia": "ras tabia",
    "el hajjamin": "el hajjamin",
    "mallasine": "mallasine",
    "central park": "central park",
    "rue du royaume d arabie saoudite": "rue du royaume d arabie saoudite",
    "cite ben younes": "cite ben younes",
    "ibn khaldoun": "ibn khaldoun",
    "ibnou kholdoun": "ibn khaldoun",
    "ibnou khouldoun": "ibn khaldoun",
    "cite avicenne": "cite avicenne",
    "la khlideya": "khlideya",
    "beb lahdid": "beb lahdid",
    "bab lahdid": "beb lahdid",
    "cite el ghazala": "cite la gazelle",
    "cite ghazala": "cite la gazelle",
    "el ghazala": "cite la gazelle",
    "cite la gazelle": "cite la gazelle",
    "ghazela": "cite la gazelle",
    "sidi amor route raoued": "raoued",
    "route raoued": "raoued",
    "raoued ariana": "raoued",
}


def normalize_text(value: object) -> str:
    text = "" if value is None else str(value)
    replacements = {
        "Ă©": "e",
        "Ă¨": "e",
        "ĂŞ": "e",
        "Ă ": "a",
        "Â": " ",
        "ŕ": "a",
        "č": "e",
        "ď": "i",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    text = unidecode(text).lower()
    text = text.replace("-", " ")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_address(address: object) -> str:
    text = normalize_text(address)
    for alias, canonical in sorted(ALIAS_CANONICAL.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(rf"\b{re.escape(alias)}\b", canonical, text)
    return re.sub(r"\s+", " ", text).strip()


def _alias_records() -> list[tuple[str, str, str]]:
    records = []
    for zone, aliases in ZONE_ALIASES.items():
        for alias in aliases:
            records.append((zone, alias, normalize_address(alias)))
    return sorted(records, key=lambda item: len(item[2]), reverse=True)


ALIAS_RECORDS = _alias_records()
NORMALIZED_ALIAS_TO_ZONE = {alias_norm: zone for zone, _alias, alias_norm in ALIAS_RECORDS}


def detect_zone(address: object, fuzzy_threshold: int = 84) -> ZoneMatch:
    normalized = normalize_address(address)
    if not normalized:
        return ZoneMatch(UNKNOWN_ZONE, ZONE_NAMES[UNKNOWN_ZONE], "", 0.0, normalized)

    for zone, alias, alias_norm in ALIAS_RECORDS:
        if re.search(rf"(?<!\w){re.escape(alias_norm)}(?!\w)", normalized):
            return ZoneMatch(zone, ZONE_NAMES[zone], alias, 1.0, normalized)

    choices = [record[2] for record in ALIAS_RECORDS]
    match = process.extractOne(normalized, choices, scorer=fuzz.partial_ratio)
    if match and match[1] >= fuzzy_threshold:
        alias_norm = match[0]
        zone = NORMALIZED_ALIAS_TO_ZONE[alias_norm]
        original_alias = next(alias for z, alias, norm in ALIAS_RECORDS if z == zone and norm == alias_norm)
        return ZoneMatch(zone, ZONE_NAMES[zone], original_alias, round(match[1] / 100, 3), normalized)

    return ZoneMatch(UNKNOWN_ZONE, ZONE_NAMES[UNKNOWN_ZONE], "", 0.0, normalized)


def zones_are_compatible(zone_a: str, zone_b: str) -> bool:
    if zone_a == UNKNOWN_ZONE or zone_b == UNKNOWN_ZONE:
        return zone_a == zone_b
    return zone_a == zone_b or zone_b in ZONE_COMPATIBILITY.get(zone_a, [])
