"""Journal des exports : « Nettoyer le journal » n'affiche que le résultat du nettoyage.

Avant correction, un bloc copié de log_export_activity suivait le nettoyage et affichait à tort
« Export non enregistré dans le journal ».
"""

import datetime

import pandas as pd
import pytest

pytest.importorskip("streamlit")
import utils  # noqa: E402


def test_nettoyage_sans_faux_avertissement(tmp_path, monkeypatch):
    log_path = tmp_path / "fake_journal.csv"
    recent = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pd.DataFrame([{"brand": "FAKE", "nb_reviews": 3, "export_timestamp": recent, "export_type": "BULK"}]).to_csv(
        log_path, index=False)
    shown = []
    for kind in ("success", "info", "warning", "error"):
        monkeypatch.setattr(utils.st, kind, lambda body, _kind=kind, **kw: shown.append((_kind, str(body))))

    utils.clean_old_exports(log_path)

    assert shown == [("info", "Aucun ancien export à supprimer.")], shown
    assert len(pd.read_csv(log_path)) == 1
