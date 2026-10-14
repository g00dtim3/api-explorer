Spécifications fonctionnelles et techniques — Bulk Export V2
API Explorer · Streamlit · Version 1.0 · 14 octobre 2026
1. Objectif
Développer une nouvelle page Bulk Export V2 dans l'application Streamlit api-explorer, permettant d'exporter jusqu'à 500 000 mentions par opération, de manière fiable, contrôlée et réutilisable.
L'utilisateur doit pouvoir demander un export complet depuis une seule interface, sans avoir à gérer manuellement les lots techniques.
Le système doit prendre en charge :
- La récupération paginée des mentions via l'API.
- Le découpage automatique en lots.
- Le stockage progressif des résultats, sans conserver l'intégralité des données en mémoire.
- Le suivi de progression et la journalisation.
- La reprise d'un export interrompu.
- La détection des doublons et le contrôle de complétude.
- Le téléchargement d'un fichier consolidé ou d'une archive ZIP contenant les lots.
- La conservation des configurations d'export.
Principe directeur : un export doit être traçable, reprenable et vérifiable avant d'être déclaré terminé.
2. Périmètre et intégration
Application cible
Streamlit / Python


Dépôt
g00dtim3/api-explorer

Module existant
module3_bulk_export.py


Nouveau module
module4_bulk_export_v2.py


API initiale
Ratings & Reviews


La nouvelle page est ajoutée au menu principal sans modifier ni supprimer les fonctionnalités existantes.
La V1 cible l'API Ratings & Reviews utilisée par le dépôt actuel. Le moteur sera conçu pour permettre une future adaptation à d'autres API, notamment Brandwatch, sans supposer que leurs mécanismes de pagination sont identiques.
Inclus dans la V1
Configuration, estimation, export, sauvegarde des lots, reprise, contrôle qualité, téléchargement et historique.
Hors périmètre initial
Orchestration distribuée, hébergement cloud, traitements analytiques avancés, synchronisation permanente et écriture obligatoire en base PostgreSQL.
Ces extensions doivent rester possibles architecturalement, mais ne constituent pas des prérequis au fonctionnement de la page.
3. Parcours utilisateur
1. Configurer
   Définir les filtres, la période, les marques et le format d'export, ou importer une configuration JSON existante.
2. Estimer
   Afficher le volume retourné par l'API, le nombre de lots et les quotas disponibles.
3. Lancer
   Créer un identifiant d'export unique et démarrer la récupération paginée.
4. Suivre
   Afficher le nombre de mentions récupérées, les lots terminés, la progression, les erreurs et l'état de l'export.
5. Reprendre
   Reprendre après un arrêt ou une erreur à partir du dernier checkpoint validé.
6. Contrôler et télécharger
   Vérifier les résultats, puis télécharger les données complètes ou les lots archivés.

4. Spécifications de l'interface Streamlit
4.1. Organisation de la page
Créer une page intitulée Bulk Export V2, composée de quatre onglets.
Onglet	Fonction
New Export	Préparer et lancer un nouvel export
Export Monitor	Consulter l'avancement et piloter une opération
Downloads	Accéder aux exports finalisés et validés
Export History	Retrouver les opérations passées et leurs journaux
4.2. Onglet New Export
Le formulaire reprend les filtres déjà disponibles dans API Explorer, via les fonctions existantes de construction des paramètres API.
Bulk Export V2
Maquette fonctionnelle

Configuration d'export

 Import JSON

Mode d'export
Complet

Aperçu (100 mentions)



Format de sortie
CSV UTF-8

JSONL

Archive ZIP




Taille des lots enregistrés
10 000 mentions

25 000 mentions — recommandé initialement

50 000 mentions


Estimation du volume
API /metrics

À calculer à partir des filtres réels, sans estimation fictive.
 Estimate volume Start export

Maquette illustrative des contrôles. La version fonctionnelle utilisera les filtres et les données renvoyés par l'API existante.
Règles fonctionnelles :
- Le volume attendu provient de l'endpoint /metrics, à paramètres de filtrage équivalents.
- Un bouton permet de consulter les quotas API avant le lancement.
- L'application empêche le lancement lorsqu'une configuration est invalide.
- Un contrôle préalable avertit lorsque le volume dépasse le seuil de 500 000 mentions.
- Le paramètre rows de pagination API reste indépendant de la taille des lots stockés : valeur initiale 1 000, sous réserve de validation des limites de l'API.
- La configuration est figée au démarrage de l'export. Toute modification des filtres nécessite une nouvelle opération.
- L'option random est désactivée pour les exports exhaustifs afin de garantir un parcours reproductible, sauf garantie explicite de stabilité fournie par l'API.
4.3. Onglet Export Monitor
Afficher les indicateurs suivants :
Indicateur	Description
Export ID	Identifiant unique
Status	État courant de l'opération
Expected records	Volume estimé par l'API
Retrieved records	Mentions effectivement reçues
Unique records	Mentions uniques validées
API pages	Nombre de pages parcourues
Completed batches	Lots enregistrés et validés
Elapsed time	Durée écoulée
Current checkpoint	Dernier curseur de reprise validé
API quota	Quota disponible, si exposé par l'API
Afficher une barre de progression, un journal des événements récents et les erreurs bloquantes.
Les contrôles utilisateur doivent permettre d'interrompre proprement l'opération et de la reprendre.
Une action Stop after current batch est préférable à une interruption immédiate, car elle garantit la finalisation du checkpoint courant.
La progression visible est recalculée depuis les métadonnées persistées, et non exclusivement depuis st.session_state.
4.4. Statuts normalisés
Statut	Définition
PENDING	Opération créée, non démarrée
RUNNING	Récupération en cours
STOPPING	Arrêt demandé, lot en cours de finalisation
PAUSED	Opération arrêtée proprement, reprenable
FAILED	Erreur ayant interrompu le traitement
INCOMPLETE	Fin atteinte mais complétude non validée
VALIDATING	Contrôles de qualité en cours
COMPLETED	Export complet et validé
L'état COMPLETED ne doit jamais être attribué uniquement parce que la boucle de pagination s'est arrêtée.
4.5. Onglets Downloads et Export History
Les exports finalisés doivent être disponibles sans relancer la collecte.
Chaque entrée indique le nom de la configuration, les dates de création et de fin, les filtres, le statut, le nombre de mentions et les fichiers disponibles.
Pour un export interrompu, proposer la reprise et l'accès au journal. Le téléchargement éventuel de données partielles doit être explicitement identifié comme tel.
Prévoir une politique de rétention configurable et un nettoyage manuel ou automatique des anciennes opérations.
5. Spécifications du moteur d'export
5.1. Pagination API
Réutiliser le client API existant avec le mécanisme actuellement présent :
cursor_mark = "*"current_params["nextCursorMark"] = cursor_markresult = api_client.get_reviews(**current_params)next_cursor = result.get("nextCursorMark")



Le moteur devra :
1. Commencer avec le curseur initial.
2. Récupérer une page API.
3. Valider la réponse et son schéma.
4. Contrôler et enregistrer les nouveaux identifiants.
5. Écrire progressivement les données vers le stockage.
6. Persister un checkpoint une fois les données sécurisées.
7. Continuer avec le curseur suivant, jusqu'à confirmation de fin.
La limite actuelle de 1 000 itérations doit être remplacée par une protection configurable, proportionnée au nombre de pages attendu et à une marge de sécurité.
La répétition d'un curseur, une réponse vide ou une défaillance API ne doivent pas être interprétées indistinctement comme une fin normale. Il faut appliquer le contrat de pagination de l'API.
5.2. Gestion des lots
Valeur initiale recommandée : 25 000 mentions par lot.
Cette valeur représente un seuil de découpage à l'écriture, et non une contrainte de l'API.
Exigences :
- Chaque lot est enregistré dans un fichier distinct.
- Les données sont écrites de manière incrémentale.
- Aucun DataFrame global de 500 000 lignes ne doit être nécessaire.
- Un lot ne devient valide qu'une fois son écriture terminée et contrôlée.
- Le programme conserve la correspondance entre les pages API, les lots et les checkpoints.
- Le découpage en lots ne doit entraîner ni perte, ni modification des contenus originaux.
Pour faciliter la reprise, les pages API doivent être traitées comme unités transactionnelles : une page n'est considérée comme validée que lorsque ses données et son checkpoint sont persistés de façon cohérente.
5.3. Déduplication
Remplacer l'approche actuelle, qui reconstruit l'ensemble des IDs depuis all_docs à chaque page.
Approche V1 :
Utiliser un index d'identifiants uniques maintenu au fil de l'exécution, éventuellement adossé à SQLite pour limiter la mémoire et permettre la reprise.
La déduplication s'appuie sur l'identifiant natif de la mention fourni par l'API.
Règles :
- Une mention déjà enregistrée n'est jamais écrite une seconde fois.
- Le nombre de doublons est comptabilisé et journalisé.
- Une mention sans identifiant exploitable provoque un traitement d'erreur explicite, sans création d'identifiant artificiel.
- Le contenu original de la mention est conservé exactement.
En cas de doublon présentant un contenu différent, conserver la trace du conflit et signaler une anomalie : ne pas fusionner silencieusement les contenus.
5.4. Reprise après interruption
Chaque opération dispose d'un état persistant comprenant au minimum :
Champ	Rôle
export_id	Identification de l'opération
config_hash	Empreinte des paramètres figés
status	Statut
expected_count	Volume initialement annoncé
retrieved_count	Nombre de lignes reçues
unique_count	Nombre de mentions uniques
duplicate_count	Nombre de doublons rencontrés
last_committed_cursor	Curseur de reprise sécurisé
batch_index	Dernier lot validé
last_updated_at	Dernière mise à jour
error_details	Diagnostic en cas d'échec
Il faut distinguer le curseur utilisé pour lire la dernière page validée du curseur renvoyé pour lire la suivante.
Critère essentiel : le système ne doit jamais enregistrer un curseur comme validé avant la persistance durable des données correspondantes.
Au redémarrage, une opération doit pouvoir recharger ses métadonnées, identifier les fichiers valides, réconcilier l'index des IDs et reprendre au dernier point sûr.
5.5. Gestion des erreurs API
Prévoir :
- Des timeouts explicites de connexion et de lecture.
- Des tentatives automatiques limitées pour les erreurs transitoires.
- Un backoff exponentiel avec jitter.
- Le respect de Retry-After en cas de réponse 429.
- L'arrêt sur erreur persistante, schéma inattendu ou échec d'authentification.
- La conservation du journal et des checkpoints.
- L'absence de nouvelle consommation API lors d'un simple téléchargement d'un export déjà terminé.
Les erreurs et leurs éventuelles tentatives de reprise doivent être enregistrées sans exposer les tokens dans les journaux.
5.6. Exécution indépendante du navigateur
Pour atteindre l'objectif de reprise après fermeture ou rechargement de la page, le traitement ne doit pas dépendre uniquement de la durée de vie du script Streamlit.
Prévoir un moteur d'export distinct, exécuté par un worker Python supervisé ou un mécanisme de tâches persistant.
Streamlit doit piloter et consulter ce moteur, pas constituer son unique environnement d'exécution.
Un worker unique est suffisant pour la V1. Plusieurs exports simultanés ne sont pas requis initialement : prévoir une file d'attente ou un verrou persistant pour empêcher les conflits.
6. Stockage et formats de sortie
6.1. Stockage intermédiaire
Utiliser initialement un répertoire local persistant, configurable via une variable d'environnement.
Structure proposée :
exports/
└── {export_id}/
    ├── config.json
    ├── manifest.json
    ├── checkpoints.sqlite
    ├── export.log
    ├── batches/
    │   ├── batch_0001.jsonl
    │   ├── batch_0002.jsonl
    │   └── ...
    └── output/
        ├── export_complete.csv
        └── export_batches.zip


Les fichiers intermédiaires sont conservés tant que l'opération est reprenable, puis selon une durée de rétention paramétrable.
La V1 ne nécessite pas PostgreSQL. SQLite est suffisant pour les métadonnées, les checkpoints et les identifiants uniques, sous réserve d'un stockage persistant fiable.
6.2. Formats d'export
Format	Spécification	Priorité
JSONL	Un objet JSON original par ligne	P0
CSV	Fichier unique en UTF-8, avec en-têtes	P0
ZIP	Archive contenant les lots et le manifeste	P0
CSV plat	Format analytique existant	P1
Excel	Optionnel, génération séparée	P2
Conservation des données source :
Les verbatims et tous les champs source doivent être conservés sans paraphrase ni altération. Les fichiers JSONL constituent la référence pour les données brutes. Les conversions CSV doivent préserver exactement les valeurs textuelles après décodage.
Les règles existantes de postprocess_reviews() doivent être auditées avant réutilisation. Les enrichissements, renommages, suppressions ou transformations de colonnes doivent être réservés au format analytique dérivé.
Le téléchargement d'un export complet doit s'appuyer sur un fichier déjà généré, sans reconstruire systématiquement un DataFrame global.
6.3. Manifeste
Chaque export doit posséder un manifeste permettant de contrôler :
- Le périmètre et les filtres utilisés.
- Le volume attendu et le volume obtenu.
- Les lots, leurs tailles et leurs empreintes SHA-256.
- Le nombre de doublons et d'erreurs.
- Les horodatages.
- Les résultats de validation.
- Le statut final de l'opération.
Une archive ZIP doit intégrer ce manifeste.
7. Contrôle qualité et validation
La validation intervient après la collecte et avant l'attribution du statut COMPLETED.
Contrôle	Règle	Échec
Complétude	Volume unique cohérent avec l'API /metrics	INCOMPLETE
Pagination	Fin conforme au contrat API	INCOMPLETE ou FAILED
Unicité	Aucun ID en doublon dans les sorties	FAILED
Intégrité	Tous les lots lisibles et empreintes valides	FAILED
Conservation	Champs et verbatims originaux préservés	FAILED
Cohérence	Somme des lignes des lots = total annoncé dans le manifeste	FAILED
Reprise	Aucune donnée perdue ou dupliquée après redémarrage	Test d'acceptation échoué
L'égalité stricte avec le volume annoncé par /metrics constitue la règle initiale. Si le jeu de données change pendant l'export, ou si l'API ne fournit pas de snapshot stable, l'application doit signaler cette limite et ne pas annoncer une complétude non démontrée.
Il faut vérifier auprès du fournisseur les garanties de pagination et de stabilité du décompte. Aucun seuil de tolérance arbitraire ne doit masquer des mentions manquantes.
8. Architecture de développement
Structure cible :
api-explorer/
├── main_app.py
├── api_client.py
├── module3_bulk_export.py       # Existant, conservé
├── module4_bulk_export_v2.py    # Nouvelle interface
├── bulk_export/
│   ├── __init__.py
│   ├── engine.py                 # Orchestration
│   ├── api_adapter.py            # Pagination API
│   ├── batches.py                # Écriture des lots
│   ├── state_store.py            # SQLite/checkpoints
│   ├── validation.py             # Contrôles
│   ├── downloads.py              # CSV/ZIP
│   └── worker.py                 # Exécution supervisée
└── tests/
    └── test_bulk_export.py


Réutilisation du code existant
Composant	Action
APIClient	Réutiliser, ajouter timeout et gestion structurée des erreurs
build_filter_params()	Réutiliser en assurant la cohérence avec /metrics
module3_bulk_export.py	Conserver inchangé pour la compatibilité
postprocess_reviews()	Auditer avant intégration au format dérivé
display_download_buttons()	Remplacer pour les gros volumes par des téléchargements de fichiers persistés
Journal d'export	Étendre avec le manifeste et les statuts
L'adaptateur API doit exposer un contrat clair de pagination, permettant ultérieurement de remplacer nextCursorMark par un autre mécanisme sans réécrire tout le moteur.
Sécurité
Les tokens API restent dans les secrets Streamlit ou les variables d'environnement sécurisées. Ils ne doivent jamais apparaître dans les fichiers de configuration exportés, les logs ou les manifests.
Les répertoires contenant des verbatims doivent être protégés contre un accès non autorisé. Un export_id ne doit pas, à lui seul, donner accès aux fichiers d'un autre utilisateur.
9. Critères d'acceptation
Checklist de recette fonctionnelle et technique
Validation de la recette
0/12



[ ] La nouvelle page fonctionne sans régression sur les modules existants
[ ] Un export de 500 000 mentions réelles peut être exécuté
[ ] L'application ne charge jamais les 500k mentions dans un DataFrame global
[ ] Les lots sont persistés et contrôlés individuellement
[ ] Un export interrompu peut reprendre au dernier checkpoint validé
[ ] Un rechargement du navigateur ne fait pas perdre l'état de l'opération
[ ] Aucune mention n'est perdue ou dupliquée à la reprise
[ ] Les verbatims et champs source restent inchangés
[ ] Un export incomplet ne peut pas être déclaré COMPLETED
[ ] Un CSV complet et une archive ZIP peuvent être téléchargés
[ ] Le manifeste et les logs permettent d'auditer l'export
[ ] Les secrets API sont absents des fichiers produits
 Copier la checklist
Les tests de volumétrie doivent s'appuyer sur des exports réels autorisés ou sur des données de test validées par le projet. Aucune donnée de mentions ne doit être fabriquée pour démontrer artificiellement une réussite.
10. Plan d'implémentation
Phase	Priorité	Livrable
1. Audit et validation API	P0	Pagination, limites, schémas et volumes vérifiés
2. Moteur Bulk V2	P0	Extraction, déduplication, lots et checkpoints
3. Interface Streamlit	P0	Configuration et suivi d'export
4. Résilience	P0	Worker, reprise, retries et gestion d'erreurs
5. Validation et downloads	P0	Manifeste, contrôles, CSV, ZIP
6. Optimisation	P1	Mesures RAM, temps, quotas et amélioration UX
7. Intégration Data Hub	P2	Extension éventuelle vers PostgreSQL
Points techniques restant à confirmer
1. API : nextCursorMark est-il bien garanti sur l'intégralité du résultat, avec quel ordre stable et quelles limites de taille de page ?
2. Hébergement : où le worker et les fichiers persistants seront-ils exécutés ? Un hébergement Streamlit avec stockage éphémère ne suffit pas aux garanties de reprise demandées.
3. Volumétrie : quelle est la taille moyenne réelle d'une mention complète ?
4. Quotas : les tentatives répétées et les reprises consomment-elles le quota de volume API ?
5. Données : les mentions peuvent-elles changer pendant la collecte, et l'API expose-t-elle un mécanisme de snapshot ?
11. Synthèse des décisions de conception
Sujet	Décision V1
Framework	Streamlit conservé
Page	Nouveau module indépendant Bulk Export V2
Capacité cible	500 000 mentions par opération
Pagination	Curseur API natif
Taille de lot	25 000 par défaut, configurable
Traitement	Worker Python indépendant de la session navigateur
Persistance	Fichiers locaux + SQLite
Déduplication	Identifiant natif unique
Reprise	Checkpoints persistants
Formats prioritaires	JSONL, CSV, ZIP
Validation	Obligatoire avant statut COMPLETED
Compatibilité	Modules existants préservés
Évolution	Adaptateur API et PostgreSQL possibles
Résultat attendu : API Explorer V2 doit se comporter comme un véritable gestionnaire d'extractions, et non comme une simple page de téléchargement.
L'utilisateur configure une extraction de 500 000 mentions, suit son traitement, peut retrouver et reprendre l'opération, puis récupère un résultat complet et auditable. Les contraintes techniques de pagination, de mémoire et de reprise restent gérées par le moteur, indépendamment de l'interface Streamlit.