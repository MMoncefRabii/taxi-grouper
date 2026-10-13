"""Destination detection and manual alias learning for Grand Tunis addresses."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from rapidfuzz import fuzz, process
from unidecode import unidecode

from ..config import DATA_DIR, UNKNOWN_ZONE
from ..schemas import HISTORIQUE_COLUMNS
from .preprocessing import is_repeated_header_row


ALIASES_PATH = DATA_DIR / "destination_aliases.json"
UNKNOWN_DESTINATIONS_PATH = DATA_DIR / "unknown_destinations.csv"
GENERIC_ADDRESS_WORDS = {
    "rue",
    "avenue",
    "av",
    "route",
    "rt",
    "cite",
    "cité",
    "residence",
    "résidence",
    "res",
    "immeuble",
    "imm",
    "bloc",
    "numero",
    "num",
    "n",
    "lot",
    "lotissement",
}


DESTINATION_ALIASES: dict[str, dict[str, Any]] = {
    "BORJ_CEDRIA": {"official_name": "Borj Cedria", "zone": "A", "aliases": ["borj cedria", "borj cedria", "borj cedria cite riadh"]},
    "HAMMAM_LIF": {"official_name": "Hammam Lif", "zone": "A", "aliases": ["hammam lif", "hammam-lif", "hammem lif", "hamam lif", "hammam linf", "hammem linf", "h lif"]},
    "HAMMAM_CHATT": {"official_name": "Hammam Chatt", "zone": "A", "aliases": ["hammam chatt", "hammam chat", "hammem chatt", "hammem chat", "hamem el chatt"]},
    "EZZAHRA": {"official_name": "Ezzahra", "zone": "A", "aliases": ["ezzahra", "zahra"]},
    "YASMINETTE": {"official_name": "Yasminette", "zone": "A", "aliases": ["yasminette", "yassminet"]},
    "BIR_EL_BEY": {"official_name": "Bir El Bey", "zone": "A", "aliases": ["bir el bey", "bir bay"]},
    "RADES": {"official_name": "Radès", "zone": "B", "aliases": ["rades", "radès", "cite med ali rades", "cité med ali rades", "cite mohamed ali rades"]},
    "MEDINA_JEDIDA": {"official_name": "Medina Jedida", "zone": "B", "aliases": ["medina jedida", "medina jadida", "madina jadida", "madina jdida", "nouvelle medina"]},
    "MEGRINE": {"official_name": "Mégrine", "zone": "B", "aliases": ["megrine", "mégrine", "magrine", "megrine cite chaker", "magrine cite chaker"]},
    "JBEL_JELLOUD": {"official_name": "Jbel Jelloud", "zone": "B", "aliases": ["jbel jelloud", "jbal jloud", "jbal jelloud", "djebel jeloud"]},
    "MORNAG": {"official_name": "Mornag", "zone": "B", "aliases": ["mornag"]},
    "BOUMHAL": {"official_name": "Boumhal", "zone": "B", "aliases": ["boumhal"]},
    "MHAMDIA": {"official_name": "Mhamdia", "zone": "D", "aliases": ["mhamdia"]},
    "FOUCHANA": {"official_name": "Fouchana", "zone": "D", "aliases": ["fouchana", "fouchena", "fuchena"]},
    "EL_MOUROUJ": {"official_name": "El Mourouj", "zone": "D", "aliases": ["mourouj", "el mourouj", "mourouj 1", "mourouj 2", "mourouj 3", "mourouj 4", "mourouj 5", "mourouj 6", "mourouj 7", "mourouj3", "mourouj4", "mourouj5", "mourouj6", "mourouj7"]},
    "NAASEN": {"official_name": "Naasen", "zone": "D", "aliases": ["naasen", "naassen", "nassen", "chbedda"]},
    "IBN_SINA": {"official_name": "Ibn Sina", "zone": "D", "aliases": ["ibn sina", "ibnou sina"]},
    "WARDIA": {"official_name": "Wardia", "zone": "D", "aliases": ["wardia", "ouardia", "wardeia", "elouardia", "diboz ville", "diboz"]},
    "KABARIA": {"official_name": "Kabaria", "zone": "D", "aliases": ["kabaria"]},
    "CITE_HLEL": {"official_name": "Cité Hlel", "zone": "D", "aliases": ["cite hlel", "cité hlel", "mallasine", "malasine", "mallassine"]},
    "CITE_AVICENNE": {"official_name": "Cité Avicenne", "zone": "D", "aliases": ["cite avicenne", "cité avicenne", "avicenne", "avicenne tunis"]},
    "MONTFLEURY": {"official_name": "Montfleury", "zone": "D", "aliases": ["montfleury", "monfleury"]},
    "BELLEVUE": {"official_name": "Bellevue", "zone": "D", "aliases": ["bellevue", "belle vue"]},
    "CITE_OLYMPIQUE": {"official_name": "Cité Olympique", "zone": "D", "aliases": ["cite olympique", "cité olympique", "cita c olympique"]},
    "LAFAYETTE": {"official_name": "Lafayette", "zone": "E", "aliases": ["lafayette"]},
    "PASSAGE": {"official_name": "Passage", "zone": "E", "aliases": ["passage"]},
    "CENTRE_VILLE": {"official_name": "Centre Ville", "zone": "E", "aliases": ["centre ville", "centre-ville", "tunis centre", "rue madrid", "rue de madrid"]},
    "BARCELONE": {"official_name": "Barcelone", "zone": "E", "aliases": ["barcelone", "place barcelone", "barcelone poste"]},
    "CITE_KHADHRA": {"official_name": "Cité Khadhra", "zone": "E", "aliases": ["cite khadhra", "cité khadhra", "cite el khadhra", "cite lkhadhra", "lkhadhra", "cita c el khadhra"]},
    "BAB_KHADHRA": {"official_name": "Bab Khadhra", "zone": "E", "aliases": ["bab khadhra", "beb khadhra"]},
    "BAB_BHAR": {"official_name": "Bab Bhar", "zone": "E", "aliases": ["bab bhar", "beb bhar", "beb bhar tunis"]},
    "SIDI_EL_BACHIR": {"official_name": "Sidi El Bachir", "zone": "E", "aliases": ["sidi el bachir"]},
    "BAB_SOUIKA": {"official_name": "Bab Souika", "zone": "E", "aliases": ["bab souika", "beb souika"]},
    "AVENUE_MADRID": {"official_name": "Avenue Madrid", "zone": "E", "aliases": ["avenue madrid", "rue de madrid", "madrid"]},
    "BAB_DZIRA": {"official_name": "Bab Dzira", "zone": "E", "aliases": ["bab dzira", "beb dzira"]},
    "BAB_JDID": {"official_name": "Bab Jdid", "zone": "E", "aliases": ["bab jdid", "beb jdid"]},
    "CENTRAL_PARK": {"official_name": "Central Park", "zone": "E", "aliases": ["central park"]},
    "RUE_ROYAUME_ARABIE_SAOUDITE": {"official_name": "Rue du Royaume d'Arabie Saoudite", "zone": "E", "aliases": ["rue du royaume d arabie saoudite", "royaume d arabie saoudite"]},
    "EL_HAJJAMIN": {"official_name": "El Hajjamin", "zone": "E", "aliases": ["el hajjamin", "hajjamin"]},
    "MANOUBA": {"official_name": "Manouba", "zone": "F", "aliases": ["manouba", "mannouba", "la manouba"]},
    "DANDEN": {"official_name": "Danden", "zone": "F", "aliases": ["danden", "denden", "dnden", "dandane", "route danden", "rue danden", "den den", "dendn"]},
    "KHAZNADAR": {"official_name": "Khaznadar", "zone": "F", "aliases": ["khaznadar", "khaznadar bardo"]},
    "BARDO": {"official_name": "Bardo", "zone": "F", "aliases": ["bardo"]},
    "RAS_TABIA": {"official_name": "Ras Tabia", "zone": "F", "aliases": ["ras tabia", "rass tabia", "ras etabia"]},
    "SIDI_HSSINE": {"official_name": "Sidi Hssine", "zone": "F", "aliases": ["sidi hssine", "sidi hsin", "sidi hassine"]},
    "ZAHROUNI": {"official_name": "Zahrouni", "zone": "F", "aliases": ["zahrouni", "ezzahrouni"]},
    "ZOUHOUR": {"official_name": "Zouhour", "zone": "F", "aliases": ["zouhour", "cite ezzouhour", "cité ezzouhour", "cite ezzouhour2", "ezzouhour2"]},
    "CITE_BEN_YOUNES": {"official_name": "Cité Ben Younes", "zone": "F", "aliases": ["cite ben younes", "cité ben younes", "ben younes"]},
    "BAB_SAADOUN": {"official_name": "Bab Saadoun", "zone": "F", "aliases": ["bab saadoun", "beb saadoun"]},
    "OMRANE": {"official_name": "Omrane", "zone": "F", "aliases": ["omrane", "omrane superieur", "omrane supérieur", "omrane sup"]},
    "EL_AGBA": {"official_name": "El Agba", "zone": "F", "aliases": ["agba", "el agba", "diar ben mahmoud"]},
    "MORNAGUIA": {"official_name": "Mornaguia", "zone": "F", "aliases": ["mornaguia", "mornageya", "mornagia"]},
    "TEBOURBA": {"official_name": "Tebourba", "zone": "F", "aliases": ["tebourba", "tbourba"]},
    "KSAR_SAID": {"official_name": "Ksar Said", "zone": "F", "aliases": ["ksar said", "ksar said 2", "ksar said 3", "kssar said", "bortal", "bortal bardo", "bortal ksar said"]},
    "IBN_KHALDOUN": {"official_name": "Ibn Khaldoun", "zone": "F", "aliases": ["ibn khaldoun", "ibn khaldou", "ibnou kholdoun", "ibnou khouldoun", "cite ibn kholdoun", "cite ibnou kholdoun", "cite ibnou khouldoun"]},
    "CITE_ERRAFEHA": {"official_name": "Cite Errafeha", "zone": "F", "aliases": ["cite errafeha", "cite errafaha", "errafeha", "errafaha", "rafeha", "rafeha ariana", "cite errafeha ariana"]},
    "ETTADHAMEN": {"official_name": "Ettadhamen", "zone": "G", "aliases": ["ettadhamen", "tadhamen", "thadhamen"]},
    "MNIHLA": {"official_name": "Mnihla", "zone": "G", "aliases": ["mnihla"]},
    "BASSATINE": {"official_name": "Bassatine", "zone": "G", "aliases": ["bassatine", "hay bassatine", "basatin"]},
    "TAHRIR": {"official_name": "Tahrir", "zone": "G", "aliases": ["tahrir", "ettahrir", "etahrir"]},
    "INTILAKA": {"official_name": "Intilaka", "zone": "G", "aliases": ["intilaka", "entileka"]},
    "MANAR": {"official_name": "Manar", "zone": "G", "aliases": ["manar", "manar1", "manar 1", "el manar"]},
    "JARDIN_EL_MENZAH": {"official_name": "Jardin El Menzah", "zone": "G", "aliases": ["jardin el menzah", "jardin del menzah", "jardin d el menzah", "jardin lmenzah", "jardin manzah"]},
    "MENZAH": {"official_name": "Menzah", "zone": "G", "aliases": ["menzah", "manzah", "menzah 1", "menzah 2", "menzah 3", "menzah 4", "menzah 5", "menzah 6", "menzah 7", "menzah 8"]},
    "ENNASR": {"official_name": "Ennasr", "zone": "G", "aliases": ["ennasr", "cite ennasr", "cité ennasr"]},
    "DOUAR_HICHER": {"official_name": "Douar Hicher", "zone": "G", "aliases": ["douar hicher"]},
    "OUED_LIL": {"official_name": "Oued Lil", "zone": "G", "aliases": ["oued lil", "oued lil manouba", "oued elil", "oued ellil", "wed el lill", "wed ellil", "jdaida", "djedaida", "jedaida"]},
    "NOGRA": {"official_name": "Nogra", "zone": "G", "aliases": ["nogra"]},
    "ARIANA": {"official_name": "Ariana", "zone": "H", "aliases": ["ariana", "ariana centre", "ariana centre ville", "ariana nouvelle", "borj baccouch ariana", "borj baccouch"]},
    "CHARGUIA": {"official_name": "Charguia", "zone": "H", "aliases": ["charguia", "charguia 1", "charguia1", "charguia 2", "charguia2"]},
    "ROND_POINT_ESCALE": {"official_name": "Rond Point L'Escale", "zone": "H", "aliases": ["rond point l escale", "rond point escale", "l escale", "lescale"]},
    "CITE_LA_GAZELLE": {"official_name": "Cité La Gazelle", "zone": "H", "aliases": ["cite la gazelle", "cité la gazelle"]},
    "CITE_ETAAMIR": {"official_name": "Cité Etaamir", "zone": "H", "aliases": ["cite etaamir", "cité etaamir", "ettaamir"]},
    "CITE_ENNASIM": {"official_name": "Cité Ennasim", "zone": "H", "aliases": ["cite ennasim", "cité ennasim", "cite nassim"]},
    "BORJ_LOUZIR": {"official_name": "Borj Louzir", "zone": "I", "aliases": ["borj louzir"]},
    "HEDI_NOUIRA": {"official_name": "Hedi Nouira", "zone": "I", "aliases": ["hedi nouira"]},
    "NKHILETTE": {"official_name": "Nkhilette", "zone": "I", "aliases": ["nkhilette", "nkhilet", "enkhilet", "nkilet"]},
    "GHAZELA": {"official_name": "Ghazela", "zone": "H", "aliases": ["ghazela", "ghazala", "gazelle", "cite ghazela", "cite ghazala", "cite gazelle", "cite el ghazala", "cité el ghazala"]},
    "JAAFER": {"official_name": "Jaafer", "zone": "I", "aliases": ["jaafer", "jaafar", "ariana jaafer", "ariana jaafar", "nour jaafer", "nour jaafar", "jaafer nour jaafer"]},
    "ARIANA_SOGHRA": {"official_name": "Ariana Soghra", "zone": "I", "aliases": ["ariana soghra", "ariana sghira", "ariana essoghra", "ariana petite", "petite ariana"]},
    "RAOUED": {"official_name": "Raoued", "zone": "I", "aliases": ["raoued", "route raoued", "sidi amor route raoued", "raoued ariana"]},
    "BORJ_TOUIL": {"official_name": "Borj Touil", "zone": "I", "aliases": ["borj touil"]},
    "KALAAT_EL_ANDALOUS": {"official_name": "Kalaat El Andalous", "zone": "I", "aliases": ["kalaat el andalous", "kalaat landalos"]},
    "LA_MARSA": {"official_name": "La Marsa", "zone": "J", "aliases": ["la marsa", "marsa"]},
    "GAMMARTH": {"official_name": "Gammarth", "zone": "J", "aliases": ["gammarth"]},
    "SIDI_BOU_SAID": {"official_name": "Sidi Bou Said", "zone": "J", "aliases": ["sidi bou said", "sidi bousaid", "sidi boussaid"]},
    "BHAR_LAZREG": {"official_name": "Bhar Lazreg", "zone": "J", "aliases": ["bhar lazreg", "bhar lazrag", "bhar lazrak", "b7ar lazreg"]},
    "SOUKRA": {"official_name": "Soukra", "zone": "J", "aliases": ["soukra", "sokra", "la soukra", "soukra parc"]},
    "CHOTRANA": {"official_name": "Chotrana", "zone": "J", "aliases": ["chotrana"]},
    "DIAR_SOUKRA": {"official_name": "Diar Soukra", "zone": "J", "aliases": ["diar soukra"]},
    "KRAM": {"official_name": "Kram", "zone": "K", "aliases": ["kram", "le kram", "kram ouest"]},
    "CARTHAGE": {"official_name": "Carthage", "zone": "K", "aliases": ["carthage", "carhage", "carthage salambo"]},
    "LA_GOULETTE": {"official_name": "La Goulette", "zone": "K", "aliases": ["la goulette", "goulette"]},
    "AIN_ZAGHOUEN": {"official_name": "Ain Zaghouen", "zone": "K", "aliases": ["ain zaghouen", "ain zaghouan"]},
    "AOUINA": {"official_name": "Aouina", "zone": "K", "aliases": ["aouina", "l aouina", "laaouina", "l aaouina", "wahat aouina"]},
    "DAR_FADHAL": {"official_name": "Dar Fadhal", "zone": "K", "aliases": ["dar fadhal", "dar faadhal"]},
    "LAC_1": {"official_name": "Lac 1", "zone": "K", "aliases": ["lac 1", "lac1"]},
    "LAC_2": {"official_name": "Lac 2", "zone": "K", "aliases": ["lac 2", "lac2"]},
    "LES_BERGES_DU_LAC": {"official_name": "Les Berges du Lac", "zone": "K", "aliases": ["les berges du lac", "berges du lac"]},
    "SIDI_DAOUD": {"official_name": "Sidi Daoud", "zone": "K", "aliases": ["sidi daoud"]},
    "JARDIN_DE_CARTHAGE": {"official_name": "Jardin de Carthage", "zone": "K", "aliases": ["jardin de carthage"]},
}


def normalize_address(text: str) -> str:
    """Normalize a raw Tunisian address."""
    value = "" if text is None else str(text)
    replacements = {"Ă©": "e", "Ă¨": "e", "ĂŞ": "e", "Ă ": "a", "Â": " ", "ŕ": "a", "č": "e"}
    for bad, good in replacements.items():
        value = value.replace(bad, good)
    value = unidecode(value).lower()
    value = value.replace("-", " ")
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\blac\s*(\d)\b", r"lac \1", value)
    return value


def clean_destination_text(text: str) -> str:
    """Normalize text and remove generic address words for destination matching."""
    normalized = normalize_address(text)
    tokens = [token for token in normalized.split() if token not in {normalize_address(word) for word in GENERIC_ADDRESS_WORDS}]
    return re.sub(r"\s+", " ", " ".join(tokens)).strip()


def _load_manual_aliases() -> dict[str, dict[str, Any]]:
    if not ALIASES_PATH.exists():
        ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
        ALIASES_PATH.write_text("{}", encoding="utf-8")
        return {}
    try:
        return json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _merged_aliases() -> dict[str, dict[str, Any]]:
    merged = json.loads(json.dumps(DESTINATION_ALIASES, ensure_ascii=False))
    for key, value in _load_manual_aliases().items():
        if key in merged:
            aliases = set(merged[key].get("aliases", []))
            aliases.update(value.get("aliases", []))
            merged[key]["aliases"] = sorted(aliases)
        else:
            merged[key] = value
    return merged


def _alias_index() -> list[tuple[str, str, str, str]]:
    rows = []
    seen: set[tuple[str, str]] = set()
    for key, payload in _merged_aliases().items():
        for alias in payload.get("aliases", []):
            for candidate in {normalize_address(alias), clean_destination_text(alias), normalize_address(alias).replace(" ", "")}:
                if candidate and (candidate, key) not in seen:
                    seen.add((candidate, key))
                    rows.append((candidate, key, payload["official_name"], payload["zone"]))
    return sorted(rows, key=lambda item: len(item[0]), reverse=True)


def detect_destination(address: str) -> dict:
    """Detect official destination and zone from a raw address."""
    raw = "" if address is None else str(address)
    normalized = normalize_address(raw)
    cleaned = clean_destination_text(raw)
    compact = normalized.replace(" ", "")
    search_texts = [text for text in [normalized, cleaned, compact] if text]
    if not search_texts:
        return _unknown(raw, normalized)

    aliases = _alias_index()
    alias_lookup = {alias: (key, official, zone) for alias, key, official, zone in aliases}
    for search_text in search_texts:
        if search_text in alias_lookup:
            _key, official, zone = alias_lookup[search_text]
            return _result(raw, normalized, cleaned, official, zone, search_text, 100, "exact")

    for alias, _key, official, zone in aliases:
        if alias and any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", search_text) for search_text in search_texts):
            return _result(raw, normalized, cleaned, official, zone, alias, 100, "substring")

    choices = [alias for alias, *_ in aliases]
    match = process.extractOne(cleaned or normalized, choices, scorer=fuzz.WRatio)
    if match:
        alias, score, _ = match
        _key, official, zone = alias_lookup[alias]
        if score >= 80:
            return _result(raw, normalized, cleaned, official, zone, alias, float(score), "fuzzy")
        if score >= 70:
            return _result(raw, normalized, cleaned, official, zone, alias, float(score), "low_confidence")
    return _unknown(raw, normalized)


def load_historical_destinations_from_excel(file_path: str) -> pd.DataFrame:
    """
    Load every unique address from a historical workbook and build a clean
    destination reference list with detection status.
    """
    detected = detect_destinations_from_excel(file_path)
    if detected.empty:
        return detected
    reference = (
        detected[
            [
                "RawAdresse",
                "NormalizedAdresse",
                "CleanedDestination",
                "DetectedDestination",
                "Zone",
                "Confidence",
                "Method",
                "NeedsManualReview",
            ]
        ]
        .drop_duplicates()
        .sort_values(["DetectedDestination", "RawAdresse"], kind="stable")
        .reset_index(drop=True)
    )
    return reference


def detect_destinations_from_excel(file_path: str) -> pd.DataFrame:
    """Read all sheets, extract addresses, and detect destinations."""
    sheets = pd.read_excel(file_path, sheet_name=None, header=None)
    results = []
    for sheet_name, raw in sheets.items():
        header: list[str] | None = None
        address_idx: int | None = None
        for row_number, row in raw.iterrows():
            values = row.tolist()
            if is_repeated_header_row(values):
                header = [str(v) for v in values[: len(HISTORIQUE_COLUMNS)]]
                address_idx = header.index("Adresse")
                continue
            if address_idx is None:
                continue
            address = values[address_idx] if address_idx < len(values) else None
            if pd.isna(address) or str(address).strip() == "":
                continue
            detection = detect_destination(str(address))
            results.append(
                {
                    "SourceSheet": sheet_name,
                    "RowNumber": int(row_number) + 1,
                    "RawAdresse": detection["raw_address"],
                    "NormalizedAdresse": detection["normalized_address"],
                    "CleanedDestination": detection["cleaned_destination"],
                    "DetectedDestination": detection["destination"],
                    "Zone": detection["zone"],
                    "MatchedAlias": detection["matched_alias"],
                    "Confidence": detection["confidence"],
                    "Method": detection["method"],
                    "NeedsManualReview": detection["method"] in {"unknown", "low_confidence"},
                }
            )
    df = pd.DataFrame(results)
    save_unknown_destinations(df)
    return df


def save_unknown_destinations(results_df: pd.DataFrame, output_path: str | Path = UNKNOWN_DESTINATIONS_PATH) -> None:
    if results_df.empty:
        return
    needs_review = results_df[results_df["NeedsManualReview"]].copy()
    if needs_review.empty:
        return
    out = pd.DataFrame(
        {
            "RawAdresse": needs_review["RawAdresse"],
            "NormalizedAdresse": needs_review["NormalizedAdresse"],
            "SuggestedDestination": needs_review["DetectedDestination"],
            "SuggestedZone": needs_review["Zone"],
            "Confidence": needs_review["Confidence"],
            "ManualDestination": "",
            "ManualZone": "",
        }
    ).drop_duplicates()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False, encoding="utf-8-sig")


def import_manual_corrections(corrections_file: str) -> None:
    """Import manually corrected destinations and save them as aliases."""
    corrections = pd.read_csv(corrections_file)
    manual = _load_manual_aliases()
    official_lookup = {payload["official_name"].lower(): (key, payload) for key, payload in DESTINATION_ALIASES.items()}
    for _, row in corrections.iterrows():
        destination = str(row.get("ManualDestination", "")).strip()
        zone = str(row.get("ManualZone", "")).strip().upper()
        normalized = str(row.get("NormalizedAdresse", "")).strip() or normalize_address(row.get("RawAdresse", ""))
        if not destination or not zone or not normalized:
            continue
        key_payload = official_lookup.get(destination.lower())
        key = key_payload[0] if key_payload else re.sub(r"\W+", "_", destination.upper()).strip("_")
        payload = manual.setdefault(key, {"official_name": destination, "zone": zone, "aliases": []})
        payload["official_name"] = destination
        payload["zone"] = zone
        aliases = set(payload.get("aliases", []))
        aliases.add(normalized)
        payload["aliases"] = sorted(aliases)
    ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALIASES_PATH.write_text(json.dumps(manual, indent=2, ensure_ascii=False), encoding="utf-8")


def _result(raw, normalized, cleaned, destination, zone, matched_alias, confidence, method) -> dict:
    return {
        "raw_address": raw,
        "normalized_address": normalized,
        "cleaned_destination": cleaned,
        "destination": destination,
        "zone": zone,
        "matched_alias": matched_alias,
        "confidence": round(float(confidence), 2),
        "method": method,
    }


def _unknown(raw, normalized) -> dict:
    return _result(raw, normalized, clean_destination_text(raw), "UNKNOWN", UNKNOWN_ZONE, None, 0, "unknown")
