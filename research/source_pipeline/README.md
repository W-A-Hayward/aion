# RIPPLE — acquisition locale des 52 sources

Workspace isolé, bibliothèque standard Python, curl système et PDFKit macOS déjà présents. Aucun SDK AWS, aucune installation et aucun import du pipeline de production. Les fichiers externes et sorties volumineuses sont ignorés par Git via `artifacts/`.

## Exécution

```sh
python3 -B research/source_pipeline/pipeline.py \
  --register /chemin/RIPPLE_Official_Research_Register_2026-11-15.xlsx \
  --holdings /chemin/xiu_holdings.csv \
  --original-inventory /chemin/RIPPLE_research_inventory_2026-11-15.json

python3 -B -m unittest discover -s research/source_pipeline -p 'test_*.py' -v
python3 -B research/source_pipeline/audit.py
```

`--offline` interdit tout accès réseau : reconstruction depuis les checkpoints. `--refresh` demande explicitement de nouvelles lectures publiques et crée une nouvelle version ; il ne remplace aucune donnée antérieure. `--discover-pending` revisite les pages déjà en cache pour les liens complémentaires revus SPY/Cenovus/Brookfield/Shopify. Les sources nouvelles ne sont jamais des commandes à exécuter.

Les chemins des entrées sont explicites. Les sept anciens PDF et reçus sont lus dans `research/source_documents/runs/20261115T131702Z_d4fbb4fa/`. Les paramètres de recherche existants ne sont pas modifiés. L’original XLSX et l’inventaire fourni restent intacts ; **l’inventaire actualisé est une nouvelle version locale**, sous `artifacts/runs/<run>/inventory.json`.

## Fichiers créés

| Fichier | Fonction |
|---|---|
| `register.py` | Lecture des 52 lignes exactes OFFICIAL SOURCES, contrôles de schéma, refus des formules et relations externes. |
| `network.py` | HTTPS public, robots, limite de redirects/hôtes, blocages enregistrés, cache par URL, mode hors ligne. |
| `extract.py` | PDF par page physique ; HTML avec liens/tableaux ; CSV holdings/FRED/StatCan ; JSON Valet ; ZIP et cellules XLSX bornés. |
| `pipeline.py` | Acquisition incrémentale, réutilisation des reçus, inventaires et préparation KB/données. |
| `test_pipeline.py` | Tests locaux avec interfaces HTTP simulées et fichiers temporaires. |
| `audit.py` | Vérification de tous les hashes et de chaque segment préparé ; inventaire détaillé des artefacts en CSV. |
| `.gitignore` | Exclut documents, extractions, sorties et caches Python de Git. |
| `ACQUISITION_AUDIT.md` | Résultats concrets, limites et suivi des 52 entrées. |

## Stockage et reprise

`artifacts/objects/<sha256>` conserve les octets originaux. `extracted/<sha>_<adapter>_v3.json` contient une extraction versionnée. Chaque lancement crée `runs/<run>/` avec un reçu par source. Un arrêt au milieu d’un lot n’efface ni les téléchargements ni les sources terminées ; le prochain lancement réutilise ces checkpoints. Un même hash est stocké une seule fois. Une tentative de remplacer des octets sous un hash existant échoue.

Un rafraîchissement en échec conserve l’ancien objet et son hash. Les anciens inventaires, textes et documents ne sont pas supprimés. La date de consultation ne devient jamais une date officielle de publication ou de holdings. Les objets S3 ne sont ni consultés ni confirmés.

## Acquisition raisonnable

- Maximum par lancement : 180 requêtes HTTP, 25 MiB par fichier, 300 MiB au total ; 8 s connexion, 30 s requête, une seconde minimum entre appels au même hôte. Les robots peuvent imposer un délai plus long.
- Pas de retry automatique après 401/403/429, challenge, refus robots ou politique robots inaccessible. `robots_unavailable_manual_review` signifie **politique non vérifiable**, pas preuve que tout le site est interdit ou indisponible.
- Identité `RIPPLEResearch`, sans imitation de navigateur, cookie, login, token, CAPTCHA ou contournement. Les redirects non HTTPS, privés ou hors des hôtes revus s’arrêtent.
- Découverte limitée à des liens exacts des pages officielles, avec période cible et trois fichiers maximum par entrée. Les CDN supplémentaires sont explicitement restreints et le lien parent/hash est conservé. La provenance n’est pas validée uniquement parce qu’un PDF s’ouvre.
- Les archives sont bornées ; aucune macro ou formule XLSX n’est exécutée. Un export vide ou sans date officielle n’est pas un dataset valide.

## Sens des statuts

`usable` = au moins un rapport, jeu daté correctement parsé ou article officiel pertinent est lisible localement et non en quarantaine. Ce n’est **ni une validation intégrale de toutes les demandes d’une entrée**, ni une preuve financière vérifiée. `context_only` = page de navigation/documentation ou données dont le mapping est incomplet. `needs_attention` = rien de qualifié, accès bloqué ou seulement matériel en quarantaine.

La vérification des octets, le domaine, l’identité textuelle, la période et les citations sont séparés. Les rapprochements automatiques d’émetteur/période sont des indices, pas une validation humaine. Les dates de publication non établies restent nulles. Les pages imprimées ne sont pas déduites d’un décalage arbitraire. Les interprétations et directions boursières ne sont pas produites automatiquement.

## Préparation Bedrock et données structurées

`kb_preparation/review_required/` et `quarantine/` contiennent le texte exact extrait, segmenté **à l’intérieur de chaque page PDF**, avec offsets et fichiers `.txt.metadata.json`. Métadonnées : SHA, source, émetteur, titre, période déclarée, page physique, vérifications séparées et `citation_approved=false`. Les pages HTML ont des offsets, pas de faux numéros PDF. Les portails/API sont identifiés comme documentation, pas comme mécanismes économiques. Les PDF originaux restent dans le magasin d’objets.

`structured_preparation/` conserve dimensions, dates, unités et valeurs manquantes. StatCan garde géographie, vecteur, type de carburant, facteur d’échelle, statuts de suppression et fréquence mensuelle. Valet conserve les descriptions de séries. Les poids manquants IVV restent nulls, les lignes sont conservées et les poids ne sont pas renormalisés. SPY XLSX garde ses cellules originales ; son mapping de poids/unité reste à valider.

`raw_compatible/` prépare les CSV compatibles avec les lecteurs existants, **sans écrire dans data/ ou S3**. Les mappings proposés se trouvent dans `ingestion_preparation.json`. L’inverse FX est explicitement calculé comme `1/usdcad`, sans interpolation. Le fichier macro canadien est partiel : il ne doit pas remplacer le panel contenant aussi les taux américains. Les nouvelles séries exigent un accord de contrat et d’unités.

Avant AWS : revue de contenu/droits/provenance, sélection des sources utiles à la KB, contrat versionné et mapping des datasets, approbation du responsable backend, publication non destructive dans de nouveaux préfixes, puis ingestion et tests de récupération. **Ne pas appeler `compute/evidence.py` pour ce lot** : le chemin de publication existant peut supprimer les anciens documents lors d’un lot partiel.

Limites : pages dynamiques et politique robots inaccessible restent manuelles ; pas d’OCR automatique ; pas de vérification complète des tableaux PDF ou de citations produites automatiquement ; dépendance PDFKit macOS. Les endpoints publics documentés FRED, Valet et StatCan sont préparés, mais un refus d’accès reste un refus. L’API EIA nécessite clé et sélection de séries ; SEC companyfacts nécessite CIK et identité de requérant appropriés. Aucun de ces prérequis n’est inventé.
