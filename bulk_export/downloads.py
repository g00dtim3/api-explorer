"""
bulk_export/downloads.py
──────────────────────────────────────────────────────────────
Fabrication des fichiers finaux À PARTIR DE LA BASE, en flux (paquets lus par ``seq``), puis envoi dans Storage.

- ``batches/batch_0001.jsonl.gz`` … : la référence brute. Chaque ligne = le texte JSON reçu, tel quel.
  Deux empreintes SHA-256 : sur le contenu non compressé et sur le fichier .gz envoyé.
- ``export_complete.csv`` : UTF-8 avec BOM (Excel), une colonne par champ de premier niveau (union, dans l'ordre
  d'apparition). Les textes ne sont pas modifiés ; les listes / objets / nombres sont écrits en texte JSON ;
  la valeur ``null`` devient une cellule vide.
- ``manifest.json`` : de quoi auditer l'export (sans secret).
- ``export_batches.zip`` : les lots (décompressés, .jsonl), le manifeste, et le CSV si demandé.

Jamais 500 000 lignes en mémoire : un seul paquet de la base à la fois, fichiers temporaires supprimés après envoi.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from bulk_export import state_store as ss
from bulk_export.logging_utils import mask
from bulk_export.models import ExportConfig
from bulk_export.storage import Storage

CSV_ENCODING = "utf-8-sig"  # BOM : Excel reconnaît l'UTF-8
PARTIAL_LABEL = "DONNÉES PARTIELLES"


def batch_path(export_id: str, index: int) -> str:
    return f"{export_id}/batches/batch_{index:04d}.jsonl.gz"


def csv_path(export_id: str) -> str:
    return f"{export_id}/output/export_complete.csv"


def manifest_path(export_id: str) -> str:
    return f"{export_id}/output/manifest.json"


def zip_path(export_id: str) -> str:
    return f"{export_id}/output/export_batches.zip"


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def csv_cell(value: Any) -> str:
    """Valeur d'une cellule : texte tel quel ; null → vide ; le reste en texte JSON (sans échappement ASCII)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# ─── Lots JSONL ───────────────────────────────────────────────────────────────

@dataclass
class _BatchWriter:
    path: Path
    index: int
    rows: int = 0
    content: Any = field(default_factory=hashlib.sha256)
    content_bytes: int = 0

    def __post_init__(self):
        self._fh = gzip.open(self.path, "wb", compresslevel=6)

    def write(self, raw_json: str) -> None:
        line = raw_json.encode("utf-8") + b"\n"
        self._fh.write(line)
        self.content.update(line)
        self.content_bytes += len(line)
        self.rows += 1

    def close(self) -> None:
        self._fh.close()


def write_batches(mentions: Iterator[tuple], batch_size: int, workdir: Path) -> list[tuple[Path, _BatchWriter]]:
    """Découpe les mentions (dans l'ordre) en lots .jsonl.gz locaux. Renvoie les lots écrits."""
    done: list[tuple[Path, _BatchWriter]] = []
    current: _BatchWriter | None = None
    for _, _, raw_json in mentions:
        if current is None or current.rows >= batch_size:
            if current is not None:
                current.close()
                done.append((current.path, current))
            index = len(done) + 1
            current = _BatchWriter(workdir / f"batch_{index:04d}.jsonl.gz", index)
        current.write(raw_json)
    if current is not None:
        current.close()
        done.append((current.path, current))
    return done


# ─── CSV ──────────────────────────────────────────────────────────────────────

def write_csv(mentions_factory: Callable[[], Iterator[tuple]], dest: Path, header_note: str | None = None) -> tuple[int, list[str]]:
    """Deux passages en flux : 1) colonnes = union des champs dans l'ordre d'apparition ; 2) lignes.
    ``header_note`` (ex. DONNÉES PARTIELLES) est écrit sur une première ligne à part."""
    columns: dict[str, None] = {}
    for _, _, raw_json in mentions_factory():
        for key in json.loads(raw_json):
            columns.setdefault(key, None)
    header = list(columns)
    rows = 0
    with open(dest, "w", encoding=CSV_ENCODING, newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        if header_note:
            writer.writerow([header_note])
        writer.writerow(header)
        for _, _, raw_json in mentions_factory():
            record = json.loads(raw_json)
            writer.writerow([csv_cell(record.get(col)) for col in header])
            rows += 1
    return rows, header


# ─── Manifeste et ZIP ─────────────────────────────────────────────────────────

def build_manifest(row: dict, config: ExportConfig, files: list[ss.FileRecord], duplicates: list[dict],
                   collisions: int, validation: dict | None, final_status: str, *, partial: bool = False) -> dict:
    manifest = {
        "manifest_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "export_id": row["export_id"],
        "name": row["name"],
        "status": final_status,
        "partial": partial,
        "configuration": config.to_dict(),          # filtres et réglages, jamais de secret
        "config_hash": row["config_hash"],
        "volumes": {
            "expected_metrics": row["expected_count"], "retrieved": row["retrieved_count"],
            "unique": row["unique_count"], "duplicates": row["duplicate_count"],
            "collisions": collisions, "rejected": row["error_count"], "pages": row["pages_count"],
        },
        "duplicates": [{k: d[k] for k in ("page_no", "mention_id", "kept_api_id", "dropped_api_id")}
                       for d in duplicates],
        "files": [{"path": f.path, "kind": f.kind, "rows": f.rows_count, "sha256": f.sha256,
                   "size_bytes": f.size_bytes, "content_sha256": f.content_sha256,
                   "content_bytes": f.content_bytes} for f in files],
        "csv_format": {"encoding": "UTF-8 avec BOM", "separator": ",", "null": "cellule vide",
                       "nested_values": "texte JSON"},
        "timestamps": {"created_at": str(row["created_at"]), "last_updated_at": str(row["last_updated_at"])},
        "validation": validation,
    }
    if partial:
        manifest["warning"] = f"{PARTIAL_LABEL} : export non validé, le contenu peut être incomplet."
    return json.loads(mask(json.dumps(manifest, ensure_ascii=False, default=str)))


def write_zip(dest: Path, batches: list[tuple[Path, Any]], manifest_file: Path, csv_file: Path | None) -> None:
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for path, batch in batches:
            with gzip.open(path, "rb") as src, zf.open(f"batches/batch_{batch.index:04d}.jsonl", "w",
                                                      force_zip64=True) as dst:
                while block := src.read(1024 * 1024):
                    dst.write(block)
        zf.write(manifest_file, "manifest.json")
        if csv_file is not None:
            zf.write(csv_file, "export_complete.csv")


# ─── Orchestration : fabriquer + envoyer ──────────────────────────────────────

@dataclass
class BuiltOutputs:
    files: list[ss.FileRecord]
    batches: list[tuple[Path, Any]]
    csv_file: Path | None
    csv_header: list[str]


def build_and_upload_data_files(conn, export_id: str, config: ExportConfig, storage: Storage,
                                workdir: Path) -> BuiltOutputs:
    """Lots (toujours : c'est la référence brute) et CSV (si demandé), envoyés dans Storage."""
    records: list[ss.FileRecord] = []
    batches = write_batches(ss.iter_mentions(conn, export_id), config.batch_size, workdir)
    for path, batch in batches:
        remote = batch_path(export_id, batch.index)
        size = storage.upload_file(path, remote, "application/gzip")
        records.append(ss.FileRecord(remote, "batch_jsonl", batch.rows, sha256_file(path), size,
                                     batch.content.hexdigest(), batch.content_bytes))
    csv_file, header = None, []
    if "csv" in config.output_formats:
        csv_file = workdir / "export_complete.csv"
        rows, header = write_csv(lambda: ss.iter_mentions(conn, export_id), csv_file)
        remote = csv_path(export_id)
        size = storage.upload_file(csv_file, remote, "text/csv; charset=utf-8")
        records.append(ss.FileRecord(remote, "csv_complete", rows, sha256_file(csv_file), size))
    return BuiltOutputs(records, batches, csv_file, header)


def upload_manifest_and_zip(export_id: str, config: ExportConfig, storage: Storage, workdir: Path,
                            manifest: dict, built: BuiltOutputs) -> list[ss.FileRecord]:
    manifest_file = workdir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    remote = manifest_path(export_id)
    records = [ss.FileRecord(remote, "manifest", None, sha256_file(manifest_file),
                             storage.upload_file(manifest_file, remote, "application/json"))]
    if "zip" in config.output_formats:
        zip_file = workdir / "export_batches.zip"
        write_zip(zip_file, built.batches, manifest_file, built.csv_file if "csv" in config.output_formats else None)
        remote = zip_path(export_id)
        records.append(ss.FileRecord(remote, "zip", None, sha256_file(zip_file),
                                     storage.upload_file(zip_file, remote, "application/zip")))
    return records


def build_partial_csv(conn, export_id: str, storage: Storage, workdir: Path) -> ss.FileRecord:
    """Fichier à la demande pour un export NON validé, étiqueté « DONNÉES PARTIELLES » (nom et 1re ligne)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = workdir / "partiel.csv"
    rows, _ = write_csv(lambda: ss.iter_mentions(conn, export_id), dest,
                        header_note=f"{PARTIAL_LABEL} — export {export_id} non validé — {stamp}")
    remote = f"{export_id}/partiel/DONNEES_PARTIELLES_{stamp}.csv"
    digest = sha256_file(dest)
    size = storage.upload_file(dest, remote, "text/csv; charset=utf-8")
    os.remove(dest)
    return ss.FileRecord(remote, "csv_partial", rows, digest, size)
