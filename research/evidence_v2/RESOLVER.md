# Résolveur local de preuves des constituants XIU

Ce composant utilise uniquement les fichiers locaux déjà fournis. Il ne modifie ni le catalogue du POC précédent, ni les sources de production, ni les reçus d'acquisition. Il ne publie rien et ne contacte ni AWS ni les émetteurs.

## Résultat de la démonstration

[xiu_resolution.json](xiu_resolution.json) contient le résultat complet : snapshot officiel au **2026-11-12**, 65 lignes, poids affiché total **100,02 %** conservé sans renormalisation ; **ATD.TO : 1,46 %, 5 passages ; CNR.TO : 2,39 %, 7 passages**. Deux PDF sources, douze passages au total. Les 3,85 points de poids concernent ces deux positions ; ils ne sont pas une couverture statistique ni une attribution du beta.

Les cinq IDs de preuves ATD restent identiques à ceux du premier POC. Les sept candidats CNR sont lus dans la feuille `EVIDENCE CANDIDATES` du registre fourni, sans réécriture de leurs citations. Chaque passage garde son sujet ATD/CNR ; le contexte de détention, séparé, porte le ticker XIU, la date et la clé de ligne du CSV.

## Nouveaux fichiers

| Fichier | Fonction |
|---|---|
| `xiu_holdings.py` | Lit le préambule iShares et le tableau ; vérifie hash/date ; conserve poids décimaux, classe, secteur, place et devise ; mapping explicite ATD→ATD.TO et CNR→CNR.TO. |
| `research_register.py` | Lit le XLSX local avec la bibliothèque standard, refuse les formules, conserve les douze citations/pages/IDs et rattache les reçus d'acquisition aux deux documents. |
| `constituent_resolver.py` | Vérifie présence et unicité des actions, relit et hache les PDF, construit les contextes et l'enveloppe documentaire ; aucun calcul de beta. |
| `resolve_xiu.py` | Démonstration locale ; JSON sur stdout, ou création exclusive d'un nouveau fichier à l'intérieur de ce répertoire. |
| `test_constituent_resolver.py` | Dix-neuf tests supplémentaires, dont un test utilisant les vrais fichiers fournis. |
| `xiu_resolution.json` | Résultat local de la démonstration contenant les douze passages, deux documents et leurs contextes. |
| `RESOLVER.md` | Périmètre, commandes, statuts, contrat de sortie et limites. |

Tous les anciens fichiers du POC sont conservés intacts. Le nouveau résultat est une **vue de résolution**, pas un catalogue à passer à `Catalog.from_bytes`, au publisher ou à `compute/evidence.py`. Aucune fusion ou mise à jour des vérifications déjà stockées n'est effectuée.

## Entrées et garde-fous

- `~/Downloads/xiu_holdings.csv` : SHA-256 attendu `9caae3aa6b3aa4ad4faf2b37c9f96fd604f2a10c8cb60831f388ad0a28947527`. La date officielle est lue dans le contenu et doit être le 12 novembre, indépendamment du chemin ou du snapshot S3. Le CSV n'identifie pas le fonds dans son préambule : la liaison à XIU repose sur cette empreinte du fichier fourni et identifié par l'équipe, pas sur son seul nom.
- `~/Downloads/RIPPLE_Official_Research_Register_2026-11-15.xlsx` : SHA-256 attendu `d12abd3a0da045977ec78f232b986721992c87f884c703fd86a6245b14287214`. La feuille est recherchée par son nom, sans exécution de formule ou d'instruction contenue dans les cellules.
- `../source_documents/runs/20261115T131702Z_d4fbb4fa/manifest.json` : lu uniquement pour les observations historiques ATD/CNR. Le hash du manifeste utilisé figure dans la sortie ; aucune nouvelle disponibilité en ligne n'est inférée.
- Les deux PDF déjà présents sont relus. Leurs SHA-256 doivent correspondre aux valeurs du registre et des reçus ; signature PDF requise. Leur contenu n'est pas réextrait par ce résolveur. Une altération ou substitution de PDF fait échouer toute la réponse.

Un alias `.TO` n'est pas ajouté arbitrairement : seules les deux correspondances revues sont autorisées, avec classe Equity, place Toronto Stock Exchange et devise CAD. Une position manquante, dupliquée, mal datée, ambiguë ou non action provoque un échec. Les autres positions sont explicitement hors périmètre ; elles ne sont ni transformées en preuves absentes globalement ni supposées à beta nul.

## Exécuter localement

Depuis la racine du dépôt, sans installation :

```sh
python3 -B research/evidence_v2/resolve_xiu.py
python3 -B -m unittest discover -s research/evidence_v2 -p 'test_*.py' -v
```

La première commande écrit le résultat sur stdout, sans fichier. Les options `--holdings` et `--register` peuvent indiquer une autre copie des mêmes octets ; elles ne désactivent pas les contrôles d'empreinte. Les entrées absentes ne sont jamais téléchargées ou remplacées.

L'option `--output research/evidence_v2/<nouveau-nom>.json` crée exclusivement un fichier nouveau dans ce dossier. Un chemin hors périmètre ou un fichier déjà présent est refusé. `xiu_resolution.json` existe déjà : ne pas demander son remplacement. Les tests utilisent des fichiers temporaires uniquement dans `evidence_v2`, nettoyés à la fin. Le test d'intégration est signalé comme ignoré si les entrées autorisées manquent sur une autre machine ; sur cette machine il a été exécuté avec succès.

## Champs prêts pour un futur frontend

| Besoin | Champs disponibles |
|---|---|
| Identifier l'enquête et le mode local | `investigation_ticker`, `mode`, `catalog_kind`, `resolved_at` |
| Afficher date et provenance des holdings | `holdings_snapshot.as_of`, `sha256`, `source_id`, `row_count`, `total_displayed_weight_pct`, `weights_renormalized` |
| Afficher les positions | `holdings[].ticker`, `ticker_original`, `company_name`, `sector`, `asset_class`, `weight_pct`, `weight_pct_original`, `row_id`, `source_row` |
| Afficher chaque citation et ses pages | `passages[].excerpt_original`, `pdf_page`, `printed_page`, `section`, `research_id`, `evidence_id` |
| Conserver le sujet original et le poids | `passages[].ticker`, `subject_ticker`, `holding_ticker_original`, `holding_weight_pct` et version décimale originale |
| Relier passage, document et position | `passages[].document_id`, `document_sha256`, `context.holding_row_id`, `context.holdings_source_id`, `context.holdings_as_of`, `context.association_type` |
| Inspecter le document | `documents[].issuer`, `document_title`, `language`, `fiscal_year_end`, `publication_date`, `source_url`, `acquisition.original_url`, `acquisition.final_url`, `sha256` |
| Présenter les validations séparément | `passages[].verification`, `documents[].local_file_verification`, `issuer_verification`, `source_verification`, `publication_date_verification` |
| Distinguer opérations et statistiques | `evidence_kind="operational"`, `operational_channel`, `stock_return_direction="unknown"` ; `statistical_relationships.status="not_computed"`, `beta=null` |

Ne pas envoyer les chemins locaux absolus (`inputs`, `documents[].local_file`) à une future interface publique : un adaptateur devra conserver les IDs/hash/URL officiels et retirer ces diagnostics de workstation. Ce JSON n'est pas automatiquement accepté par le frontend/API v1 existant.

## Sens précis des validations

- `holding_membership="verified_in_local_snapshot"` : présence et poids tirés de la ligne contrôlée dans le CSV identifié. Ce n'est pas une nouvelle validation S3.
- `document_bytes="verified"` et `documents[].local_file_verification` : hash recalculé sur les octets du PDF au moment de l'appel. Ce contrôle n'atteste ni les affirmations de l'émetteur ni une causalité.
- `official_provenance`, `issuer` et `quote` restent `reported_verified` avec le hash de leur artefact justificatif : acquisition historique ou registre de recherche. Ils ne sont pas promus en vérification indépendante actuelle. Le champ documentaire `hash_verification` conserve également l'assertion d'origine ; le contrôle actuel distinct est dans `local_file_verification`.
- `page_reference="reported_in_research_register_not_reextracted"` : les pages déclarées sont conservées et bornées par le nombre de pages du reçu. L'audit précédent a retrouvé les douze textes à ces pages avec normalisation des espaces ; ce résolveur ne reproduit pas une extraction ou une revue visuelle.
- Les dates de publication restent `null` et non vérifiées ; la disponibilité actuelle des URL est `not_checked`. `source_url_verified_claim=false` n'est pas changé en `true` sur la base d'un téléchargement historique.
- Les canaux opérationnels sont des annotations candidates. L'intitulé CNR « Revenues (millions) » exige son contexte de tableau ; les notes ATD et les interprétations doivent encore être revues. La feuille XLSX ne contient pas de champ d'interprétation : il reste vide, sans texte inventé ni modification de l'ancien CSV.

## Tests et suite d'intégration

Les 49 tests locaux passent : 30 tests du POC précédent, 18 nouveaux tests de garde-fous et 1 test d'intégration avec les entrées réelles. Ils couvrent notamment les holdings absents, dates incorrectes, aliases inconnus, doublons, confusion cash/action, valeurs non finies, documents absents/inversés/altérés et la conservation exacte des citations/pages/IDs.

Avant une intégration, convenir avec le responsable backend de l'enveloppe documentaire, de la gestion des vérifications et des révisions, puis adapter séparément l'API pour résoudre les preuves via les holdings. Ce résolveur n'autorise pas la publication par le pipeline actuel et ne corrige pas son comportement destructif sur les lots partiels.
