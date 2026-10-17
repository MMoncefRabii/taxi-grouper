from dataclasses import dataclass
from typing import Any

UNASSIGNED_STATUS_BY_REASON = {
    "MISSING_DATE": "A CORRIGER: date manquante",
    "MISSING_DISPATCH_ID": "A CORRIGER: identifiant de dispatch manquant",
}

HISTORIQUE_COLUMNS = [
    "Date",
    "Matricule",
    "Nom - Prénom",
    "Opération",
    "Site",
    "Adresse",
    "Heure d'arrivée",
    "Taxi",
]

HISTORIQUE_COLUMNS_WITH_NUMERO = [
    "Date",
    "Matricule",
    "Nom - Prenom",
    "Operation",
    "Site",
    "Numero",
    "Adresse",
    "Heure d'arrivee",
    "Taxi",
    "PRIX",
]


@dataclass(frozen=True)
class RideRequest:
    row_index: int
    data: dict[str, Any]


@dataclass(frozen=True)
class TaxiGroup:
    taxi_number: int
    row_indices: list[int]
    reason: str
    rule: str


@dataclass(frozen=True)
class DetectionResult:
    cleaned_address: str
    detected_destination: str
    zone: str
    matched_alias: str | None = None
    confidence: float | None = None
    needs_manual_review: bool | None = None
    needs_manual_validation: bool | None = None
