"""
bulk_export/validation.py
──────────────────────────────────────────────────────────────
Contrôles qualité avant COMPLETED (spec §7, règle A validée le 15/10/2026).

Règle A : l'export est complet si TOUTES les mentions annoncées ont été reçues, et si chaque écart entre
« uniques » et « annoncées » est expliqué et tracé (doublons listés avec leurs deux `id`). Aucune rejetée.

| Contrôle                | Échec       |
|-------------------------|-------------|
| Pagination terminée     | INCOMPLETE  |
| Complétude (règle A)    | INCOMPLETE  |
| Aucune mention rejetée  | INCOMPLETE  |
| Données stables (/metrics redemandé) | INCOMPLETE |
| Doublons tracés         | FAILED      |
| Intégrité (empreintes relues dans Storage) | FAILED |
| Conservation + unicité (chaque ligne relue == base, même ordre, même empreinte) | FAILED |
| Cohérence (lignes des lots == uniques ; CSV == base) | FAILED |
| Jumelles                | signalées, non bloquantes |

Tout est relu EN FLUX : jamais un fichier entier en mémoire.
"""

from __future__ import annotations

import csv
import hashlib
import json
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from bulk_export import fingerprints, state_store as ss
from bulk_export.downloads import CSV_ENCODING, csv_cell
from bulk_export.models import ExportConfig
from bulk_export.storage import Storage, StorageError

FAILED, INCOMPLETE = "FAILED", "INCOMPLETE"


@dataclass
class Check:
    name: str
    ok: bool | None          # None = information (non bloquant)
    detail: str
    on_fail: str | None = None


def _gz_lines(chunks: Iterator[bytes], digest) -> Iterator[bytes]:
    """Décompresse un flux .gz en lignes (sans le \\n), en calculant l'empreinte du fichier compressé."""
    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
    pending = b""
    for chunk in chunks:
        digest.update(chunk)
        data = decomp.decompress(chunk)
        while decomp.unused_data:  # plusieurs membres gzip concaténés
            rest = decomp.unused_data
            data += decomp.flush()
            decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
            data += decomp.decompress(rest)
        pending += data
        *lines, pending = pending.split(b"\n")
        yield from lines
    pending += decomp.flush()
    if pending:
        yield pending  # dernière ligne sans \n : signalée par le contrôle de conservation


def check_batches(conn, export_id: str, storage: Storage, files: list[ss.FileRecord],
                  config: ExportConfig) -> tuple[list[Check], int]:
    """Relit chaque lot depuis Storage, ligne par ligne, en parallèle des mentions en base (ordre ``seq``)."""
    exclude = tuple(config.fingerprint.get("raw_hash_exclude", ("id",)))
    db_rows = ss.iter_mentions(conn, export_id)
    integrity, conservation = [], []
    total = 0
    for f in sorted((f for f in files if f.kind == "batch_jsonl"), key=lambda f: f.path):
        file_digest, content_digest = hashlib.sha256(), hashlib.sha256()
        lines = 0
        try:
            for line in _gz_lines(storage.iter_bytes(f.path), file_digest):
                content_digest.update(line + b"\n")
                lines += 1
                if conservation:
                    continue  # premier écart déjà trouvé : on finit seulement les empreintes
                expected = next(db_rows, None)
                if expected is None:
                    conservation.append(f"{f.path} ligne {lines} : ligne en trop (absente de la base).")
                    continue
                seq, mention_id, raw_json = expected
                if line != raw_json.encode("utf-8"):
                    conservation.append(f"{f.path} ligne {lines} : contenu différent de la mention n°{seq} en base.")
                elif fingerprints.raw_hash(json.loads(line), exclude) != mention_id:
                    conservation.append(f"{f.path} ligne {lines} : empreinte différente de la mention n°{seq}.")
        except (StorageError, zlib.error, ValueError) as exc:
            integrity.append(f"{f.path} : illisible ({exc}).")
            continue
        total += lines
        if file_digest.hexdigest() != f.sha256:
            integrity.append(f"{f.path} : empreinte du fichier différente de celle enregistrée.")
        if f.content_sha256 and content_digest.hexdigest() != f.content_sha256:
            integrity.append(f"{f.path} : empreinte du contenu différente de celle enregistrée.")
        if f.rows_count is not None and lines != f.rows_count:
            integrity.append(f"{f.path} : {lines} lignes relues, {f.rows_count} enregistrées.")
    if not conservation and next(db_rows, None) is not None:
        conservation.append("Des mentions en base n'apparaissent dans aucun lot.")
    checks = [
        Check("Intégrité des lots", not integrity, "; ".join(integrity) or "Empreintes relues identiques.", FAILED),
        Check("Conservation et unicité", not conservation,
              "; ".join(conservation) or "Chaque ligne relue est identique à la mention en base, dans le même ordre.",
              FAILED),
    ]
    return checks, total


def check_csv(conn, export_id: str, storage: Storage, f: ss.FileRecord, local_csv: Path | None) -> list[Check]:
    """Intégrité : le CSV relu dans Storage a l'empreinte enregistrée. Conservation : le CSV local (identique,
    par l'empreinte) est relu et comparé cellule par cellule aux mentions en base."""
    digest = hashlib.sha256()
    try:
        for block in storage.iter_bytes(f.path):
            digest.update(block)
    except StorageError as exc:
        return [Check("Intégrité du CSV", False, f"Illisible : {exc}", FAILED)]
    checks = [Check("Intégrité du CSV", digest.hexdigest() == f.sha256,
                    "Empreinte relue identique." if digest.hexdigest() == f.sha256
                    else "Empreinte relue différente de celle enregistrée.", FAILED)]
    if local_csv is None or not local_csv.exists():
        return checks
    problem, rows = None, 0
    with open(local_csv, encoding=CSV_ENCODING, newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        db_rows = ss.iter_mentions(conn, export_id)
        for cells in reader:
            rows += 1
            expected = next(db_rows, None)
            if expected is None:
                problem = f"ligne {rows} en trop"
                break
            record = json.loads(expected[2])
            if cells != [csv_cell(record.get(col)) for col in header] or set(record) - set(header):
                problem = f"ligne {rows} différente de la mention n°{expected[0]}"
                break
        if problem is None and next(db_rows, None) is not None:
            problem = "des mentions manquent dans le CSV"
    checks.append(Check("Conservation dans le CSV", problem is None,
                        problem or f"{rows} lignes relues, identiques aux mentions en base.", FAILED))
    return checks


def run_checks(conn, row: dict[str, Any], config: ExportConfig, storage: Storage, files: list[ss.FileRecord],
               *, expected_now: int | None, metrics_error: str | None, local_csv: Path | None) -> tuple[list[Check], str]:
    export_id = row["export_id"]
    expected, unique = row["expected_count"], row["unique_count"]
    dup, rej, retrieved = row["duplicate_count"], row["error_count"], row["retrieved_count"]
    traced = ss.count_conflicts(conn, export_id, "duplicate")
    collisions = ss.count_conflicts(conn, export_id, "collision")

    checks = [
        Check("Pagination terminée", bool(row["pagination_finished"]),
              "Fin de pagination atteinte." if row["pagination_finished"] else "La pagination n'est pas terminée.",
              INCOMPLETE),
        Check("Complétude (règle A)",
              expected is not None and retrieved == expected and unique + dup + rej == expected,
              f"Annoncées {expected} · reçues {retrieved} · uniques {unique} + doublons tracés {dup} "
              f"+ rejetées {rej}.", INCOMPLETE),
        Check("Aucune mention rejetée", rej == 0,
              "Aucune." if rej == 0 else f"{rej} mention(s) rejetée(s), gardées à part.", INCOMPLETE),
        Check("Doublons tracés", traced == dup,
              f"{dup} doublon(s), {traced} tracé(s) avec leurs deux `id` (liste dans le manifeste).", FAILED),
    ]
    if metrics_error is not None:
        checks.append(Check("Données stables pendant l'export", False,
                            f"Vérification impossible (/metrics) : {metrics_error}", INCOMPLETE))
    else:
        checks.append(Check("Données stables pendant l'export", expected_now == expected,
                            f"/metrics au début : {expected} · à la fin : {expected_now}."
                            + ("" if expected_now == expected else
                               " Jeu de données modifié pendant l'export : complétude non démontrable."),
                            INCOMPLETE))

    batch_checks, lines = check_batches(conn, export_id, storage, files, config)
    checks += batch_checks
    recorded = sum(f.rows_count or 0 for f in files if f.kind == "batch_jsonl")
    checks.append(Check("Cohérence des lots", lines == unique == recorded,
                        f"Lignes relues {lines} · uniques {unique} · lignes enregistrées {recorded}.", FAILED))
    for f in files:
        if f.kind == "csv_complete":
            checks += check_csv(conn, export_id, storage, f, local_csv)
            checks.append(Check("Cohérence du CSV", f.rows_count == unique,
                                f"Lignes du CSV {f.rows_count} · uniques {unique}.", FAILED))
    checks.append(Check("Avis jumeaux", None,
                        f"{collisions} collision(s) : tous les avis gardés, signalés (non bloquant).", None))

    failed = [c for c in checks if c.ok is False]
    if any(c.on_fail == FAILED for c in failed):
        final = FAILED
    elif failed:
        final = INCOMPLETE
    else:
        final = "COMPLETED"
    return checks, final


def checks_to_json(checks: list[Check]) -> list[dict]:
    return [asdict(c) for c in checks]
