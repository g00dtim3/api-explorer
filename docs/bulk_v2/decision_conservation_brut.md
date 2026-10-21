# Décision — Conservation du brut après validation

> Statut : **validée par l'utilisateur le 21/10/2026** (chantier « gardening », lot 1A,
> `docs/chantier/SPRINT_L1A_conservation_du_brut.md`).
> Remplace la tâche 4 du sprint 6 (« après COMPLETED, supprimer les lignes `raw_mentions` ») et la ligne
> « Rétention » du tableau d'`ADAPTATION_SUPABASE.md` §2.

## 1. Le problème
Jusqu'au 21/10/2026, un export validé perdait tout en deux temps :
1. dès le passage à COMPLETED, `finalize.py` effaçait ses mentions brutes de `bulk_export.raw_mentions` ;
2. à chaque ouverture de la page, `apply_retention()` supprimait de Storage les fichiers des exports terminés
   depuis plus de `retention_days` jours (30 par défaut).

Au bout d'un mois, il ne restait que la fiche de l'export. Or le fichier plat lu par Compass n'est **pas** une copie
complète : `postprocess_reviews()` retire `content origin` (texte en langue d'origine) et ramène la date au 1er du
mois. Le brut est la seule source complète pour les analyses à venir (lot 4 : table de verbatims commune).

## 2. La décision
| Quoi | Avant | Maintenant (défaut) | Pour revenir à l'ancien comportement |
|---|---|---|---|
| Mentions brutes en base après COMPLETED | effacées | **conservées** | `purge_raw_after_validation = true` |
| Fichiers dans Storage | supprimés après 30 jours | **jamais supprimés** (`retention_days = 0`) | `retention_days = 30` (ou autre nombre positif) |

- `retention_days = 0` veut dire « ne jamais supprimer ». Une valeur négative est refusée au démarrage.
  ⚠ Avant ce lot, 0 aurait fait l'inverse (tous les fichiers supprimés) : la protection est double
  (`apply_retention()` et `exports_with_expired_files()` ne font rien quand la valeur vaut 0).
- `purge_raw_mentions()` ne change pas : elle reste utilisable à la main.
- Quand la purge est désactivée, le journal de l'export note « Mentions conservées en base (purge désactivée) ».

## 3. Conséquences
- **Espace** : le brut grossit à chaque export (≈ 1 Go par export de 500 000 mentions selon l'estimation de la
  spec, **à mesurer**). L'onglet Export History affiche la taille de la base et de `raw_mentions`, et avertit
  au-delà de `alerte_taille_base_go` (6 Go par défaut, pour 8 Go inclus dans le plan Pro). La taille de la base
  compte **tous** les schémas (Compass compris), car c'est elle que Supabase limite.
- **Lien avec Compass** : index sur `raw_mentions (compass_id)` (migration 004) pour retrouver vite le brut d'un
  verbatim Compass (lot 4).
- **Archivage** du brut ancien hors de la base : à décider quand l'avertissement de taille se déclenchera.

## 4. Réhydratation des exports déjà purgés
Les exports purgés dont les lots JSONL sont encore dans Storage peuvent retrouver leur brut :
`python -m bulk_export.rehydrate <export_id>` (ou le bouton « Réhydrater le brut » dans Export History).

- Refus si l'export n'est pas COMPLETED, si son brut est déjà en base, ou si ses fichiers ont expiré.
- Chaque lot est relu en flux ; ses **deux** empreintes sont vérifiées (fichier `.gz` et contenu décompressé).
- Les empreintes (`mention_id`, `content_key`, `compass_id`) sont **recalculées** avec les réglages enregistrés de
  l'export : on ne recopie pas d'empreinte, on la refait à partir des données source (règle n°6).
- `raw_json` est réinséré tel quel ; `seq` suit l'ordre des lots, donc l'ordre d'origine.
- **`page_no = 0`** pour les lignes réhydratées : les lots ne gardent pas le numéro de page. Une vraie page commence
  à 1, donc `page_no = 0` signifie « réhydraté depuis les lots ».
- Tout ou rien : une seule transaction ; nombre de lignes = `unique_count` et `mention_id` uniques, sinon rien
  n'est enregistré.
- À la fin : `raw_purged_at` est remis à vide et l'événement « Brut réhydraté depuis les lots (N mentions) » est ajouté.
