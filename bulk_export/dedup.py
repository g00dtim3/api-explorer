"""
bulk_export/dedup.py
──────────────────────────────────────────────────────────────
Tri des mentions d'une page (decision_identifiant.md §3) :

- ``raw_hash`` jamais vu (ni en base, ni plus haut dans la page) → NOUVELLE ;
- ``raw_hash`` déjà vu                                          → DOUBLON (non réécrit, compté) ;
- ``raw_hash`` nouveau mais ``content_key`` déjà vu             → JUMELLE (enregistrée + collision notée) ;
- date absente ou illisible                                     → REJETÉE (gardée telle quelle, à part).

Fonctions pures : la base est interrogée par le moteur AVANT (une requête par page), et le
résultat est passé ici sous forme d'ensembles. Les mentions ne sont jamais modifiées.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from bulk_export import fingerprints
from bulk_export.state_store import ConflictRow, MentionRow, RejectedRow


def to_raw_json(record: Mapping[str, Any]) -> str:
    """Texte JSON enregistré : ordre des champs tel que reçu, caractères non ASCII gardés tels quels.
    Relu avec ``json.loads``, il redonne exactement le dictionnaire reçu."""
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _api_id(record: Mapping[str, Any]) -> str | None:
    value = record.get("id")
    return None if value is None else str(value)


@dataclass(frozen=True)
class PreparedRecord:
    """Une mention de la page avec ses empreintes (ou la raison de son rejet)."""
    record: Mapping[str, Any]
    fp: fingerprints.Fingerprints | None
    reject_reason: str | None = None


@dataclass
class ClassifiedPage:
    new_mentions: list[MentionRow] = field(default_factory=list)
    conflicts: list[ConflictRow] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)
    # Nombre d'`id` API portés par plusieurs mentions DIFFÉRENTES de la page (constat à journaliser).
    repeated_api_ids: int = 0


def prepare(records: Sequence[Mapping[str, Any]],
            settings: Mapping[str, Any] | None = None) -> list[PreparedRecord]:
    out = []
    for record in records:
        try:
            out.append(PreparedRecord(record, fingerprints.compute(record, settings)))
        except fingerprints.MissingDateError as exc:
            out.append(PreparedRecord(record, None, str(exc)))
    return out


def classify(prepared: Sequence[PreparedRecord], *, known_raw: set[str],
             known_content: Mapping[str, str]) -> ClassifiedPage:
    """``known_raw`` : raw_hash déjà en base parmi ceux de la page.
    ``known_content`` : content_key → raw_hash d'une mention déjà en base."""
    page = ClassifiedPage()
    seen_raw = set(known_raw)
    seen_content = dict(known_content)
    distinct_ids: Counter[str] = Counter()

    for p in prepared:
        api_id = _api_id(p.record)
        if p.fp is None:
            page.rejected.append(RejectedRow(reason=p.reject_reason or "Mention rejetée.",
                                             raw_json=to_raw_json(p.record), api_id=api_id))
            continue

        fp = p.fp
        if fp.raw_hash in seen_raw:
            page.conflicts.append(ConflictRow(kind="duplicate", mention_id=fp.raw_hash, api_id=api_id,
                                              content_key=fp.content_key))
            continue

        seen_raw.add(fp.raw_hash)
        if api_id is not None:
            distinct_ids[api_id] += 1
        if fp.content_key in seen_content:
            page.conflicts.append(ConflictRow(kind="collision", mention_id=fp.raw_hash,
                                              other_mention_id=seen_content[fp.content_key],
                                              content_key=fp.content_key))
        else:
            seen_content[fp.content_key] = fp.raw_hash
        page.new_mentions.append(MentionRow(mention_id=fp.raw_hash, raw_json=to_raw_json(p.record),
                                            content_key=fp.content_key, compass_id=fp.compass_id,
                                            api_id=api_id))

    page.repeated_api_ids = sum(1 for n in distinct_ids.values() if n > 1)
    return page
