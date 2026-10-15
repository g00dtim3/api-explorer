# Comment un export s'exécute, s'arrête et reprend

> Pour les utilisateurs de la page « Bulk Export V2 ». Version 1 (hébergement Streamlit Community Cloud + Supabase).

## En une phrase
L'export avance **tant que l'application Streamlit est en marche**. S'il est interrompu, **aucune donnée déjà
enregistrée n'est perdue** : il reprend exactement là où il s'était arrêté.

## Où vit l'export ?
- **Le travail** (appeler l'API, trier, enregistrer) se fait dans une tâche de fond **de l'application**, pas dans
  votre navigateur.
- **La mémoire de l'export** (où il en est, les mentions déjà reçues, le point de reprise) est dans **Supabase**.
  Elle survit à tout : fermeture de l'onglet, rechargement, redémarrage de l'application.

## Ce qui N'arrête PAS forcément un export
| Situation | Effet |
|---|---|
| Fermer l'onglet ou le navigateur | L'export continue tant que l'application tourne. En rouvrant la page, vous retrouvez son avancement. |
| Recharger la page | Aucun effet sur l'export. L'affichage est relu depuis Supabase. |
| Une erreur passagère de l'API (coupure, surcharge) | Jusqu'à 5 nouveaux essais automatiques, avec des attentes croissantes |

## Ce qui ARRÊTE un export
| Situation | Ce qui se passe | Que faire ? |
|---|---|---|
| **Redémarrage, redéploiement ou mise en veille** de l'application (Streamlit Cloud endort une application inutilisée) | La tâche de fond meurt. Au bout de **2 minutes au plus**, l'export est reconnu comme « interrompu » et passe en **PAUSED** dès que quelqu'un ouvre la page. | Cliquer sur **Reprendre**. Si l'option de reprise automatique est activée, c'est fait tout seul. |
| Vous cliquez sur **Arrêter après la page en cours** | La page en cours est terminée et enregistrée, puis l'export passe en **PAUSED**. | **Reprendre** quand vous voulez |
| Erreur persistante de l'API ou réponse anormale | L'export passe en **FAILED**, avec le diagnostic dans le journal. | Lire le journal, puis **Reprendre** |
| Fin de la pagination | La **validation s'enchaîne automatiquement** (VALIDATING) : fabrication des fichiers, envoi dans Storage, relecture, contrôles. | Rien : **COMPLETED** si tout est prouvé ; sinon INCOMPLETE ou FAILED, avec la raison dans le Monitor, et le bouton **Valider** pour relancer |
| Redémarrage pendant la validation | L'export revient à **INCOMPLETE** (aucune donnée perdue : les mentions restent en base jusqu'à COMPLETED) | **Valider** |

## Pourquoi rien n'est perdu à la reprise
Chaque page de l'API est enregistrée **d'un seul bloc** avec son point de reprise : soit tout est écrit, soit rien.
Après un arrêt, même brutal, l'export repart du dernier point enregistré. Une page à moitié traitée est simplement
relue. Ce mécanisme a été vérifié en tuant volontairement le programme en pleine collecte : le résultat après reprise
est **identique** à celui d'un export sans interruption (mêmes mentions, même ordre, aucun doublon).

## Un seul export à la fois
La version 1 n'exécute qu'**un export à la fois**. Le verrou est en base, donc il vaut aussi entre deux onglets ou
deux personnes. Un second lancement est refusé avec un message clair.

## Le « bail » et le « battement de cœur », en clair
- Pendant qu'il travaille, l'export tient un **bail** dans Supabase : « je m'en occupe jusqu'à telle heure ».
- Une petite tâche **prolonge ce bail toutes les 30 secondes**. C'est le battement de cœur, et il continue même
  quand l'API fait attendre.
- Si l'application meurt, plus personne ne prolonge le bail : il expire au bout de **2 minutes**, et l'export est
  alors reconnu comme interrompu et reprenable.

## Reprise automatique (option)
Désactivée par défaut. Pour l'activer, ajoutez `auto_resume = true` dans la section `[bulk_export]` des secrets.
Un export interrompu est alors relancé dès que quelqu'un ouvre la page.

## Ligne de commande (optionnel, pour un ordinateur avec Python)
Même moteur, mêmes règles. Les paramètres sont donnés **uniquement** par variables d'environnement :
```bash
export BULK_EXPORT_API_TOKEN="…"          # le token de l'API
export BULK_EXPORT_DATABASE_URL="…"       # la chaîne « Session pooler » de Supabase
python -m bulk_export.run --create ma_config.json   # crée et lance
python -m bulk_export.run --status exp_…            # état et derniers événements
python -m bulk_export.run --export-id exp_…         # reprendre
python -m bulk_export.run --recover                 # exports interrompus → PAUSED
```
Ctrl+C arrête proprement, après la page en cours. Exemple de `ma_config.json` :
```json
{"name": "Essai FAKE_BRAND 2024", "filters": {"brand": "FAKE_BRAND", "start-date": "2024-01-01", "end-date": "2024-01-31"}}
```
