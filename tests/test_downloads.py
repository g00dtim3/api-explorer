"""Fabrication des fichiers (sans base) : CSV fidèle, lots JSONL, ZIP, manifeste sans secret."""

import csv
import gzip
import json
import zipfile

from bulk_export import downloads
from bulk_export.downloads import CSV_ENCODING, csv_cell
from bulk_export.logging_utils import register_secret
from bulk_export.models import ExportConfig

fake_records = [
    {"id": "1", "brand": "FAKE, avec virgule", "content trad": "Guillemets \"doubles\" et 'simples'\nretour ligne\r\nCRLF",
     "rating": 5, "attributes": ["Scent", "Texture"], "attributes positive": None},
    {"id": "2", "brand": "FAKE 🙂", "content trad": "  espaces gardés  ; point-virgule", "rating": 4.5,
     "nouveau champ": {"imbriqué": True}},
    {"id": "3", "brand": "", "content trad": "", "rating": None},
]


def mentions():
    return iter([(i + 1, f"h{i}", json.dumps(r, ensure_ascii=False, separators=(",", ":")))
                 for i, r in enumerate(fake_records)])


def test_csv_relu_identique(tmp_path):
    dest = tmp_path / "c.csv"
    rows, header = downloads.write_csv(mentions, dest)
    assert rows == 3
    assert header == ["id", "brand", "content trad", "rating", "attributes", "attributes positive", "nouveau champ"]
    with open(dest, encoding=CSV_ENCODING, newline="") as fh:
        lines = list(csv.reader(fh))
    assert lines[0] == header
    for record, cells in zip(fake_records, lines[1:]):
        assert cells == [csv_cell(record.get(c)) for c in header]
    assert lines[1][2] == fake_records[0]["content trad"]  # texte inchangé, retours ligne compris
    assert lines[1][4] == '["Scent","Texture"]' and lines[2][3] == "4.5" and lines[3][3] == ""
    assert dest.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM pour Excel


def test_csv_partiel_etiquete(tmp_path):
    dest = tmp_path / "p.csv"
    downloads.write_csv(mentions, dest, header_note="DONNÉES PARTIELLES — test")
    with open(dest, encoding=CSV_ENCODING, newline="") as fh:
        assert next(csv.reader(fh)) == ["DONNÉES PARTIELLES — test"]


def test_lots_jsonl_lignes_identiques_et_decoupage(tmp_path):
    batches = downloads.write_batches(mentions(), batch_size=2, workdir=tmp_path)
    assert [b.rows for _, b in batches] == [2, 1]
    lines = []
    for path, batch in batches:
        content = gzip.open(path, "rb").read()
        assert len(content) == batch.content_bytes
        lines += content.decode("utf-8").splitlines()
    assert [json.loads(line) for line in lines] == fake_records
    assert lines == [raw for _, _, raw in mentions()]


def test_zip_et_manifeste_sans_secret(tmp_path):
    register_secret("FAKE_secret_value_zip_123")
    batches = downloads.write_batches(mentions(), batch_size=2, workdir=tmp_path)
    config = ExportConfig(name="fake FAKE_secret_value_zip_123", filters={"brand": "FAKE"})
    row = {"export_id": "exp_20261015T000000Z_00000000", "name": config.name, "config_hash": config.config_hash,
           "expected_count": 3, "retrieved_count": 3, "unique_count": 3, "duplicate_count": 0, "error_count": 0,
           "pages_count": 2, "created_at": "x", "last_updated_at": "y"}
    manifest = downloads.build_manifest(row, config, [], [], 0, {"passed": True}, "COMPLETED")
    text = json.dumps(manifest, ensure_ascii=False)
    assert "FAKE_secret_value_zip_123" not in text and manifest["volumes"]["unique"] == 3
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(text, encoding="utf-8")
    zip_file = tmp_path / "e.zip"
    downloads.write_zip(zip_file, batches, manifest_file, None)
    with zipfile.ZipFile(zip_file) as zf:
        assert sorted(zf.namelist()) == ["batches/batch_0001.jsonl", "batches/batch_0002.jsonl", "manifest.json"]
        lines = (zf.read("batches/batch_0001.jsonl") + zf.read("batches/batch_0002.jsonl")).decode().splitlines()
    assert [json.loads(line) for line in lines] == fake_records


def test_manifeste_partiel_signale():
    config = ExportConfig(name="fake", filters={"brand": "FAKE"})
    row = {"export_id": "e", "name": "fake", "config_hash": "h", "expected_count": 3, "retrieved_count": 1,
           "unique_count": 1, "duplicate_count": 0, "error_count": 0, "pages_count": 1, "created_at": "x",
           "last_updated_at": "y"}
    manifest = downloads.build_manifest(row, config, [], [], 0, None, "PAUSED", partial=True)
    assert manifest["partial"] is True and "DONNÉES PARTIELLES" in manifest["warning"]
