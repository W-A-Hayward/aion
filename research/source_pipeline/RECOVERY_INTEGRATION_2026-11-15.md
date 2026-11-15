# RIPPLE — intégration et validation du lot de récupération

## Résultat

Les **21 entrées** du manifeste fourni sont rattachées aux **18 références existantes** concernées.
Le registre conserve ses **52 références** : les trois publications trimestrielles supplémentaires
ne deviennent pas artificiellement trois nouvelles références indépendantes.

- **2 documents acquis**, extraits et contrôlés pour leur identité, leur date et leur période.
- **15 candidats au téléchargement bloqués** au contrôle d'accès automatique.
- **2 références liées**, sans téléchargement en double.
- **1 guide facultatif non téléchargé** ; son accessibilité reste UNVERIFIED.
- **1 chantier API différé**.
- **0 citation financière automatiquement approuvée**. Aucune mesure d'exposition ou de rendement recalculée.

Inventaire actif :
`artifacts/runs/2026-11-15T171032535399+0000_8ccfcb/inventory.json`.
Il contient **66 objets uniques / 64 extractions lisibles**, dont les 64 objets de la collecte précédente.
Disponibilité des références : **24 utilisables pour leur recherche prévue, 12 de contexte, 16 à traiter**.
Une référence de contexte peut encore demander un rapport annuel ou une validation financière.

Archive fournie : `RIPPLE_Official_Sources_Recovery_2026-11-15.zip`.
SHA-256 : `01a063509f01ea416cde1193e4927b8e36e7246a48816d9a5e2d787711125f72`.
Seul le JSON du manifeste a été lu ; le script et les instructions de l'archive n'ont pas été exécutés.
Le manifeste original est conservé sous
`artifacts/recovery_manifests/01a063509f01ea416cde1193e4927b8e36e7246a48816d9a5e2d787711125f72/source_manifest.json`.

## Documents contrôlés

| Champ | BMO | Fortis |
|---|---|---|
| Candidat | SRC-021-Q3 | SRC-027 |
| Émetteur | Bank of Montreal / BMO Financial Group | Fortis Inc. |
| Titre observé | BMO Financial Group Reports Third Quarter 2026 Results - Aug 25, 2026 | FORTIS INC. REPORTS FOURTH QUARTER & ANNUAL 2025 RESULTS |
| Publication observée | 2026-08-25 | 2026-02-12 |
| Période | T3 exercice 2026, trimestre clos le 2026-07-31 | T4 et exercice 2025, année close le 2025-12-31 |
| Format | HTML | PDF, 89 pages physiques |
| Repères d'identité | Titre HTML, introduction du communiqué et dateline ; offsets exacts conservés | PDF p. 1, imprimée i : titre et publication ; PDF p. 2, imprimée ii : clôture de l'exercice |
| Provenance | Réponse HTTP 200 du sous-domaine `newsroom.bmo.com` | Réponse HTTP 200 ; lien exact retrouvé sur la page officielle des rapports Fortis |
| Réserve | Rapport annuel 2025 toujours absent de cette collecte ; pas de validation des chiffres/prêts pétroliers | Pas de validation des mécanismes de récupération du coût du combustible ni des chiffres ; T3 2026 toujours manquant |

URLs originales et finales identiques pour les deux acquisitions :

- [Communiqué BMO](https://newsroom.bmo.com/2026-08-25-BMO-Financial-Group-Reports-Third-Quarter-2026-Results)
- [PDF Fortis](https://fortisinc.com/docs/default-source/investor-presentations/q4-2025---pr-mda-fs---final.pdf?sfvrsn=5239ccca_1)
- [Page Fortis contenant le lien exact](https://fortisinc.com/investors/financial-and-regulatory-reports)

Fichiers originaux, sous `research/source_pipeline/` :

| Document | Objet local / SHA-256 | Récupéré le (UTC) |
|---|---|---|
| BMO | `artifacts/objects/5738a5db93a41d5ff563406fdc782ae2ba1aa8ccc2f14d1ffc08b0572934d4e2` | 2026-11-15T17:05:00.925755+00:00 |
| Fortis | `artifacts/objects/7b7e42718ba1dec8f0504e704eedf0bccc02bd2688da3dbbf638323230d056e4` | 2026-11-15T17:08:39.195194+00:00 |

Les revues d'identité sont dans `recovery_identity_reviews_2026-11-15.json`, liées aux hashes et aux
passages de métadonnées par offsets exacts. Il s'agit d'une lecture par l'assistant du texte extrait
et des reçus HTTP, **pas d'une approbation humaine, d'un audit financier ou d'une validation visuelle
exhaustive des tableaux PDF**. `stock_return_direction` demeure `unknown`.

## État des 21 candidats

| ID | Objet | Résultat constaté |
|---|---|---|
| SRC-005 | S&P/TSX 60 | Bloqué : robots.txt HTTP 403 ; document cible non testé |
| SRC-006 | Méthodologie S&P/TSX | Même blocage ; contradictions septembre/novembre du manifeste restent UNVERIFIED |
| SRC-008 | ATD T1 2027 | robots.txt redirige vers une page HTML ; règles non vérifiables, cible non téléchargée |
| SRC-014 | Suncor annuel 2025 | Bloqué : robots.txt HTTP 403 |
| SRC-014-Q3 | Suncor T3 2026 | Même blocage |
| SRC-021 | BMO annuel 2025 | Vérification robots.txt échouée : erreur HTTP/2 puis délai dépassé en HTTP/1.1 |
| SRC-021-Q3 | BMO T3 2026 | Acquis, texte extrait, identité/date/période contrôlées ; données financières non approuvées |
| SRC-025 | Manuvie annuel 2025 | Bloqué : robots.txt HTTP 403 |
| SRC-025-Q3 | Manuvie T3 2026 | Même blocage |
| SRC-026 | CPKC SEC 10-K | Bloqué : robots.txt SEC HTTP 403 ; le PDF CDN antérieur reste en quarantaine |
| SRC-027 | Fortis T4/exercice 2025 | Acquis, 89 pages extraites, identité et lien officiel contrôlés |
| SRC-030 | Brent FRED | Vérification robots.txt échouée : erreur HTTP/2 puis délai dépassé en HTTP/1.1 |
| SRC-031 | WTI FRED | Même résultat pour les règles d'accès du domaine |
| SRC-043 | T10YIE FRED | Même résultat |
| SRC-044 | DGS10 FRED | Même résultat |
| SRC-045 | DGS2 FRED | Même résultat |
| SRC-047 | Guide SEDAR+ | Référence facultative intégrée ; non téléchargée, lien UNVERIFIED |
| SRC-048 | Portail EDGAR | Lien vers SRC-026 conservé comme référence liée, sans réaffecter le document CPKC au portail |
| SRC-049 | SEC Companyfacts | Chantier API différé ; aucun appel API effectué |
| SRC-051 | ATD résultats annuels 2026 | Même problème de règles d'accès que SRC-008 |
| SRC-052 | S&P / GICS | Référence liée à SRC-005 ; aucune seconde preuve indépendante |

Les blocages concernent le contrôle préalable du collecteur : **ils ne prouvent pas que les documents
cibles sont absents ou inaccessibles dans un navigateur humain**. Aucune rotation d'identité,
contournement de CAPTCHA, authentification ou reprise d'un refus HTTP 403 n'a été utilisée.
La reprise HTTP/1.1 ne concerne que l'erreur de transport curl 92 avant toute réponse HTTP.
Les redirections robots restent bornées à HTTPS et au même hôte éditeur, avec variante `www` autorisée.

## Intégration et préservation

Dans le frontend : **Explore all 52 sources → sélectionner une source → Recovery links & validation**.
Les nouveaux fichiers BMO et Fortis se lisent dans le lecteur et sont recherchables dans le texte local.
Le lecteur conserve les URL, hashes, publication, période, vérifications et limites. Les autres candidats
affichent les blocages réels ; aucune URL proposée n'est présentée comme un fichier validé.

Les trois quarantaines préexistantes (CPKC, Enbridge, circulaire BNS) sont conservées. Les 35 passages
de l'Evidence Desk, les deux dates de holdings XIU et les statistiques existantes sont inchangés.
Les nouvelles sources restent des documents de recherche ; elles ne créent pas de nouvelles preuves
associées à XIU, de citations approuvées ou de contributions au bêta.

Chaque essai crée un répertoire distinct. Les anciens objets, reçus et catalogues ne sont pas supprimés.
Un contrôle partiel conserve les autres candidats et l'historique des vérifications. Les 52 reçus
d'entrée du dernier inventaire sont aussi enregistrés pour les prochaines reprises incrémentales.
Les extractions et préparations KB restent locales et ignorées par Git. Rien n'a été envoyé à AWS.

## Fichiers nouveaux ou modifiés

| Fichier | Rôle du changement |
|---|---|
| `research/source_pipeline/recovery.py` — nouveau | Import sûr du manifeste ZIP sans exécution, collecte via le client existant, validations de série/format, merge des 52 entrées, reçus et audit |
| `research/source_pipeline/review_recovery.py` — nouveau | Application hors ligne des revues explicites d'identité dans un nouvel inventaire ; hashes et offsets obligatoires |
| `research/source_pipeline/recovery_identity_reviews_2026-11-15.json` — nouveau | Métadonnées et repères exacts contrôlés pour BMO et Fortis |
| `research/source_pipeline/test_recovery.py` — nouveau | Tests des archives, formats, périodes, hash/offsets, transports, revues et préservation lors d'un lot partiel |
| `research/source_pipeline/network.py` | Redirections HTTPS robots bornées et reprise limitée d'une erreur HTTP/2 avant réponse ; les refus restent bloqués |
| `research/source_pipeline/pipeline.py` | Conservation d'une date de publication explicitement revue et liée au hash lors d'une réextraction |
| `research/source_pipeline/build_frontend_catalog.py` | Export des candidats, résultats de récupération et revues d'identité |
| `frontend/library-catalog.json` | Activation du nouvel inventaire audité ; anciennes versions conservées |
| `frontend/library-render.js` | Panneau de récupération, résultats de validation, historique et revues d'identité échappés |
| `frontend/library.js` | Résumé de la récupération dans l'état de la bibliothèque |
| `frontend/library.css` | Mise en forme limitée au panneau de récupération |
| `frontend/library.test.mjs` | Préservation des 64 objets antérieurs, 21 candidats, nouveaux statuts et contrôles d'intégrité |
| `frontend/evidence-browser-check.mjs` | Ouverture effective des deux nouveaux documents et affichage des limites dans Chrome |
| `frontend/RESEARCH_LIBRARY.md` | Inventaire et nombres actualisés |
| Ce rapport | Résultats, limites et historique des modifications |

Fichiers générés : trois nouveaux runs sous `artifacts/runs/`, manifeste original sous
`artifacts/recovery_manifests/`, nouveaux objets/extractions et version du bundle sous
`frontend/research-data/`. Les scripts et configurations de production n'ont pas été modifiés.

## Vérifications effectuées

- **33 tests Python réussis** : pipeline local, export et récupération, avec transports simulés pour les tests.
- **40 tests JavaScript réussis** : frontend, preuves, recherche et intégrité du corpus.
- **Parcours Chrome réussi** : BMO HTML, Fortis PDF de 89 pages, dates, avertissements de récupération,
  anciens passages, datasets, chat de recherche locale, mobile et reprise après erreur de chargement.
  Aucune requête externe du frontend pendant ce test.
- Audit hors ligne : **66 hashes source**, **3 759 segments de texte** identiques à leurs offsets
  d'extraction ; **481 segments restent en quarantaine** ; 7 préparations structurées ; 0 approbation de citation.

## Suite minimale

1. Pour les sources bloquées, fournir un téléchargement public obtenu normalement, avec sa page
   d'origine et son URL directe, ou réessayer lorsque les règles d'accès/réseau peuvent être vérifiées.
2. Examiner les passages financiers BMO/Fortis, leurs unités et notes avant de créer des candidats
   evidence_v2. Confirmer les liens aux holdings datés avant toute exposition dans une investigation XIU.
3. Réserver à une étape distincte l'intégration des séries au calcul, la publication versionnée S3,
   la synchronisation de la Knowledge Base et la configuration des API. Aucun de ces travaux n'a été lancé.
