# CASCADE / RIPPLE AI — Audit des données, des preuves et de l’intégration

Date de l’audit : **15 novembre 2026**. Référence Git locale examinée : `a65e330`. L’audit inclut aussi les fichiers frontend présents dans l’espace de travail, y compris les modifications et fichiers non suivis par Git. Il ne certifie pas le contenu actuellement déployé.

**Périmètre : lecture locale uniquement, sauf création de ce rapport.** Aucun script du projet, notebook, test, serveur, installation, appel AWS ou déploiement n’a été exécuté pendant cet audit. Aucun commit ni push. Les URLs ci-dessous proviennent du code ou de la documentation ; elles n’ont pas été ouvertes ni vérifiées. Aucun identifiant de compte, secret ou jeton n’est reproduit.

## Résultat principal

Le projet contient une véritable chaîne de calcul statistique, une chaîne d’extraction documentaire, des outils Athena, un agent et une orchestration asynchrone. Il contient également une interface interactive et des résultats enregistrés. **Il ne contient pas encore une investigation complète reliant les constituants datés de XIU à leurs contributions et à des documents vérifiables.**

Les trois messages de l’interface ont des causes différentes :

1. **« Holdings breakdown unavailable »** : le téléchargement d’un CSV XIU est prévu, mais le calcul ne le lit pas, aucun contrat d’attribution ETF n’existe et le rendu des ETF affiche toujours cet état. Ajouter un CSV seul ne suffit pas. Sources : `ingest/fetch_to_s3.py`, `compute/stats.py::load_raw`, `docs/data_contract.md`, `frontend/render.js::renderDecomposition`.
2. **« Transmission chain not supplied »** : aucune chaîne XIU n’est définie dans les calculs. Les chaînes existantes concernent surtout les taux et le change d’autres actifs. Source : `compute/stats.py::CHAINS`.
3. **« 0 documents supplied »** : le fichier de prévisualisation contient `evidence: []` et le panneau filtre les preuves sur le ticker exact. Ce message ne prouve pas l’absence de documents dans S3. Sources : `frontend/preview-data.json`, `frontend/render.js::renderEvidence`.

Le beta XIU enregistré est **0,010571**, avec un intervalle à 95 % **[−0,032437 ; 0,053579]**, sur **261 observations hebdomadaires**. Ce sont des valeurs présentes localement, issues d’une ancienne exécution enregistrée ; leur reproductibilité avec le code actuel et les données sources est **UNVERIFIED**. L’intervalle contient zéro : ce résultat n’établit pas une sensibilité nette différente de zéro. Il ne démontre ni l’absence de mécanismes économiques ni l’existence de contributions qui se compensent. Sources : `compute/run_stats.ipynb`, `frontend/preview-data.json`.

### Comment lire les statuts

| Statut | Signification dans ce rapport |
|---|---|
| PRÉSENT — CODE | Une implémentation est lisible dans le dépôt. Ce n’est pas une preuve d’exécution. |
| PRÉSENT — ARTEFACT LOCAL | Un fichier ou une sortie enregistrée existe dans le checkout. Sa provenance peut rester non vérifiée. |
| RÉFÉRENCÉ | Un chemin, une URL, une ressource ou un document est mentionné, sans fichier source local. |
| ABSENT DU CHECKOUT | Aucun fichier correspondant n’a été trouvé dans l’inventaire local examiné. Cela ne permet pas de conclure pour AWS. |
| UNVERIFIED | Disponibilité, fraîcheur, source originale, exécution ou fonctionnement non établis par les éléments examinés. |

**Toutes les ressources AWS et toutes les disponibilités de données dans AWS sont UNVERIFIED dans cet audit.** Les sorties sauvegardées de notebooks constituent des traces historiques, pas un contrôle de l’état actuel du cloud.

## A. Repository et architecture

### A1. Inventaire des composants

| Fichiers | Rôle et état réel | Dépendances et limites |
|---|---|---|
| `README.md` | Présentation et architecture initiales. Plusieurs descriptions de « stubs » et de frontend statique sont dépassées. | Ne pas utiliser seul pour juger l’avancement. |
| `.kiro/steering/project.md` | Conventions : Python 3.12, noms AWS, région, déploiement manuel et garde-fous. | Intention de configuration ; aucune attestation de déploiement. |
| `docs/data_contract.md` | Contrat des entrées, tables, modèles et noms AWS. Substantiel et plus à jour que le README. | Ne définit ni attribution des constituants d’un ETF ni métadonnées documentaires complètes. |
| `requirements.txt`, `.gitignore` | Dépendances de calcul et ingestion ; exclusion de données locales, Parquet et environnements. | Pandas, NumPy, PyArrow, requests, yfinance, boto3, statsmodels, pypdf et fonttools ; pas de verrouillage complet. `pytest` n’est pas déclaré dans le manifeste racine. |
| `ingest/fetch_to_s3.py` | Implémenté : copie du starter, téléchargements Yahoo/FRED/iShares, manifeste de provenance, écriture locale et upload S3. | Réseau, starter fourni séparément, boto3 et bibliothèques de données. Pas d’acquisition de filings ou de relations fournisseurs. |
| `compute/stats.py` | Implémenté : retours CAD, régressions, diagnostics, liens macro, chaînes, portefeuilles fictifs, scénarios, alternatives et exports Parquet. | Lit S3. Ignore les CSV de holdings. Ne produit pas de contributions des constituants de XIU. |
| `compute/run_stats.ipynb` | Orchestration du calcul ; sorties numériques et traces de lecture/écriture sauvegardées. | Sorties antérieures à plusieurs changements du modèle : ne pas les considérer comme une exécution du code actuel. |
| `compute/evidence.py` | Implémenté : lecture du manifeste, extraction PDF/HTML, passages, classement Bedrock, contrôle des extraits, cache, exports evidence/confidence/edges et fichiers pour KB. | Nécessite de vrais documents et Bedrock. Les métadonnées persistées sont incomplètes. |
| `compute/run_evidence.ipynb` | Orchestration d’extraction et de vérification écrite. | Cellules de code sans compteurs d’exécution ni sorties enregistrées. Exécution effective : UNVERIFIED. |
| `compute/test_stats.py`, `compute/test_evidence.py` | Tests unitaires substantiels avec séries synthétiques, documents factices, FakeS3 et clients simulés. | Non exécutés pendant l’audit ; ne vérifient pas les données publiques ni AWS. Une contradiction statique est décrite en A3. |
| `lambdas/tools/app.py`, `lambdas/tools/test_app.py` | Six outils financiers ; SQL Athena limité aux fonctions et tickers autorisés ; tests simulés. | Requiert tables Glue/Athena existantes et Parquet cohérents. Pas de lecture directe des holdings bruts. |
| `lambdas/submit/app.py`, `lambdas/submit/test_app.py` | Valide la question, écrit un job DynamoDB et l’envoie dans SQS. | Table, file, permissions et route HTTP nécessaires. |
| `lambdas/worker/app.py`, `lambdas/worker/test_app.py` | Consomme SQS, invoque AgentCore, écrit une trace S3 et le résultat DynamoDB. | Runtime AgentCore déployé, mapping SQS/Lambda et permissions nécessaires. |
| `lambdas/status/app.py`, `lambdas/status/test_app.py` | Lit un job par UUID et renvoie son état/résultat. | Route HTTP et DynamoDB. Pas de contrôle d’appartenance du job dans ce handler. |
| `agent/agent.py`, `agent/requirements.txt`, `agent/test_agent.py` | Agent Strands hébergé via Bedrock AgentCore ; wrappers Lambda, recherche KB, collecte d’appels/citations et garde-fou optionnel. | `strands-agents`, `bedrock-agentcore`, boto3, modèle Bedrock, instructions S3 ; versions agent non figées. |
| `prompts/agent_instructions.md` | Instructions d’analyse, prudence statistique, outils obligatoires, citations et niveaux de présentation. | Politique déclarative ; ne garantit pas mécaniquement une réponse correcte. |
| `prompts/action_group_functions.md` | Documentation des fonctions utilisables par l’agent. | Les wrappers maintiennent une enveloppe de type action group ; ce n’est pas la preuve d’un Bedrock Agent classique déployé. |
| `iam/README.md`, `iam/*.json` | Politiques et relations de confiance à appliquer manuellement. | Mélange de documentation ancienne et de code AgentCore plus récent ; voir E. |
| `frontend/index.html`, `frontend/styles.css` | Interface de recherche et espace personnel, chat visible tôt, réseau SVG, sélection de ticker et Beginner/Expert. | HTML/CSS/JS natifs ; pas de framework nécessaire. Le branding visible reste Cascade dans ce checkout. |
| `frontend/app.js`, `frontend/render.js`, `frontend/graph.js`, `frontend/formatters.js` | État de recherche, affichage des chiffres, scénarios, diagnostics, preuves, réseau et formats. | Interface réelle, mais principalement alimentée par une prévisualisation locale. Pas de réseau de constituants arbitraires. |
| `frontend/api.js`, `frontend/config.js` | Adaptateur des tables de recherche ; validation de l’enveloppe ; configuration des URLs. | Les trois URLs d’API sont `null`. Une API de tables correspondant au frontend n’est pas implémentée dans les Lambdas examinées. |
| `frontend/agent-api.js`, `frontend/agent-render.js` | Client submit/polling et rendu du chat, des citations et des outils. | Compatible avec l’orchestration asynchrone prévue, mais non configuré. Ne transforme pas les réponses en tables de recherche. |
| `frontend/workspace.js`, `frontend/workspace-store.js`, `frontend/workspace-render.js` | Profil local, watchlist, portefeuille fictif, notes et comparaison. | `localStorage`, données de preview et calculs de démonstration ; pas de compte utilisateur backend ni de positions de courtier. |
| `frontend/preview-data.json`, `frontend/README.md`, `frontend/frontend.test.mjs` | Snapshot local, documentation et 21 tests déclarés dans le fichier de tests. | Chiffres partiellement anciens/illustratifs ; aucune exécution des tests effectuée pendant cet audit. |
| `eval/questions.json` | Contient exactement `[]`. | L’évaluation métier de l’agent reste à construire. |
| `compute/__init__.py`, `lambdas/*/__init__.py`, `.gitkeep` | Marqueurs de paquet ou maintien de dossiers. | Pas de logique métier. |

### A2. Flux réellement prévu par le code

```text
Starter + Yahoo + FRED + CSV iShares
  -> ingest/fetch_to_s3.py -> fichiers locaux data/out/ -> S3 raw/
       prix/FX/macro/Brent -> compute/stats.py -> S3 processed/*/part-0.parquet
       holdings XIU/XESG   -> AUCUN consommateur statistique actuel

Documents fournis manuellement + manifest_docs.csv dans S3
  -> compute/evidence.py -> evidence/confidence/edges Parquet
                         -> S3 evidence/*.txt + métadonnées pour KB
                         -> synchronisation KB externe nécessaire

Parquet + tables Glue configurées -> Athena -> Lambda tools
Frontend chat -> submit -> DynamoDB + SQS -> worker -> AgentCore/Strands
  -> Lambda tools/Athena + recherche Bedrock KB -> trace S3 + résultat DynamoDB
Frontend polling -> status -> réponse textuelle et citations

Frontend recherche -> preview-data.json, OU future API GET de tables
  -> graphiques / réseau / scénarios / inspecteur de preuves
```

Les deux dernières voies frontend sont **séparées**. Une réponse réussie du chat ne remplit pas automatiquement le réseau ou le compteur documentaire. Sources : `frontend/api.js`, `frontend/agent-api.js`, `frontend/app.js`, `frontend/agent-render.js`.

### A3. Divergences et vérification locale

- `README.md` sous-estime l’implémentation ; `iam/README.md` décrit encore une intégration par alias Bedrock Agent alors que `lambdas/worker/app.py` appelle AgentCore.
- `compute/run_stats.ipynb` conserve notamment **12 liens et 8 chaînes**, dont l’ancien chemin ZST par le taux canadien à 10 ans et une chaîne XRB. `compute/stats.py` utilise désormais le taux à **2 ans** pour ZST et exclut XRB des chaînes. Les sorties sont donc décalées par rapport à l’implémentation actuelle.
- Le calcul de `portfolio_beta` a également changé : somme des rendements simples pondérés, puis logarithme. Les sorties anciennes des portefeuilles ne prouvent pas le résultat de cette version.
- Le diagnostic FX existe dans `compute/stats.py::fx_diagnostic`, mais l’appel sauvegardé du notebook à `write_outputs(tables, BUCKET)` ne transmet pas `data=data`, nécessaire à son inclusion dans le résumé. La promesse de `docs/data_contract.md` n’est donc pas automatiquement satisfaite par ce notebook.
- `compute/test_evidence.py::test_classify_retries_once_then_skips` attend un `toolChoice` forcé vers `record_evidence` ; `compute/evidence.py::TOOL_CONFIG` utilise `{"auto": {}}`. C’est une contradiction lisible dans les sources, **pas un échec de test observé pendant l’audit**.
- Les tests backend utilisent des doubles de clients AWS. Certaines fixtures worker utilisent des citations `source`/`excerpt`, différentes des champs `source_url`/`text` émis par l’agent actuel. Leur présence ne prouve pas un contrat intégré bout en bout.
- Aucun manifeste de déploiement complet, définition Glue, route API Gateway, pipeline CI ou verrou de dépendances complet n’a été trouvé. Le notebook contient des traces d’un environnement Python 3.10 ; `.kiro/steering/project.md` cible Python 3.12. Compatibilité de l’environnement réellement déployé : **UNVERIFIED**.

## B. Inventaire des datasets et sources

### B1. Règles de localisation et de preuve

Dans les tableaux suivants, **B = `s3://cascade-s3-bucket/`**, valeur par défaut remplaçable par `BUCKET`. Chaque chemin `B` + clé est le chemin S3 attendu, pas un objet confirmé. `YYYY-MM-DD` désigne une date de snapshot inconnue : aucune valeur réelle ne peut être affirmée sans inventaire des objets.

La recherche de fichiers de données dans le checkout n’a trouvé **aucun CSV, PDF ou Parquet**, ni manifeste documentaire réel. Le seul fichier HTML applicatif trouvé est `frontend/index.html` ; ce n’est pas une source financière. Les données originales locales sont donc **ABSENTES DU CHECKOUT**. Les sorties JSON du frontend et les sorties intégrées aux notebooks, elles, sont présentes.

L’ingestion écrit normalement sous `data/out/<clé raw>`. Le starter attendu est fourni séparément, par exemple `data/alphaforge_starter/`. Des replis manuels sont prévus dans `data/manual/`. Ces fichiers ne sont pas présents. `.gitignore` exclut notamment `data/` et les Parquet ; l’absence dans le checkout ne prouve pas une absence sur d’autres machines ou dans AWS.

### B2. Données brutes : inventaire complet

| Fichier / emplacement S3 attendu | Source et URL connue | Format / schéma | Couverture et dates | Usage réel dans le code ; statut |
|---|---|---|---|---|
| `Braw/starter/prices_daily.csv` | Starter PolyFinances/organisateurs ; URL originale et fournisseur amont non fournis. | CSV : `date,ticker,open,high,low,close,adj_close,volume,currency` | Contrat : 31 tickers, 2021-11-12 à 2026-11-12, USD/CAD. Couverture effective et mise à jour : UNVERIFIED. | Lu par `stats.load_raw`; prix ajustés utilisés. Référencé, absent localement ; AWS UNVERIFIED. |
| `Braw/starter/fx_usdcad_daily.csv` | Banque du Canada, série FXUSDCAD selon le contrat ; URL originale absente. | CSV : `date,usdcad,cadusd` | Dates effectives et mise à jour : UNVERIFIED. | `usdcad` sert à convertir les rendements USD en CAD ; `cadusd` n’est pas utilisé dans ce calcul. Référencé ; AWS UNVERIFIED. |
| `Braw/starter/macro_rates.csv` | Sources identifiées par les séries et le champ `source`, non consultable sans fichier. Séries US DGS10/DGS2 et Banque du Canada BD.CDN.10YR.DQ.YLD / BD.CDN.2YR.DQ.YLD. URLs absentes. | CSV long : `date,series_id,value,unit,frequency,label,source` ; taux en pourcentage. | Dates effectives et mise à jour : UNVERIFIED. | Chargé par le calcul ; taux hebdomadaires et variations pour les liens. Toutes les séries chargées ne deviennent pas des contrôles du modèle XIU. Référencé ; AWS UNVERIFIED. |
| `Braw/prices/snapshot=YYYY-MM-DD/prices_daily_extra.csv` | Yahoo Finance via `yfinance` ; manifeste indique `yfinance`, pas une URL d’origine reproductible. | Même schéma que les prix starter. | VFV.TO, XSP.TO, XESG.TO, XRB.TO, XLB.TO, XEG.TO ; CAD. Fenêtre demandée : 2021-11-12 à 2026-11-13, fin exclusive chez yfinance. | `auto_adjust=False`, utilisation de `adj_close`. Chargé par le calcul. Aucun fichier local ; AWS UNVERIFIED. |
| `Braw/fred/snapshot=YYYY-MM-DD/DCOILBRENTEU.csv` | Brent : U.S. EIA, distribué via FRED. [URL CSV configurée](https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU&cosd=2021-11-12&coed=2026-11-13). | CSV : date (`observation_date` ou `DATE`), `DCOILBRENTEU` ; USD/baril ; `.` ou vide = manquant. | Fenêtre demandée : 2021-11-12 à 2026-11-13. Dates effectivement reçues et mise à jour : UNVERIFIED. | Facteur pétrolier de toutes les sensibilités. Référencé ; AWS UNVERIFIED. |
| `Braw/fred/snapshot=YYYY-MM-DD/T10YIE.csv` | Federal Reserve Bank of St. Louis/FRED. [URL CSV configurée](https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10YIE&cosd=2021-11-12&coed=2026-11-13). | CSV date, `T10YIE` ; breakeven américain à 10 ans en pourcentage. | Même fenêtre demandée ; disponibilité effective et mise à jour UNVERIFIED. | Lien macro `oil>breakeven`, pas un contrôle de la régression XIU. Référencé ; AWS UNVERIFIED. |
| `Braw/holdings/snapshot=YYYY-MM-DD/xiu_holdings.csv` | BlackRock/iShares Canada. [URL CSV XIU configurée](https://www.blackrock.com/ca/investors/en/products/239832/ishares-sptsx-60-index-etf/1464253357814.ajax?fileType=csv&fileName=XIU_holdings&dataType=fund). | CSV avec préambule puis en-tête commençant par `Ticker`. Aucun schéma normalisé de poids/secteurs/date n’est défini. | XIU ; date de composition, nombre de lignes, poids et date de publication UNVERIFIED. Le dossier snapshot indique une récupération, pas la date de composition. | Téléchargement prévu ; **jamais lu par `stats.load_raw`**. Pas de fichier local ni de jointure. AWS UNVERIFIED. |
| `Braw/holdings/snapshot=YYYY-MM-DD/xesg_holdings.csv` | BlackRock/iShares Canada. [URL CSV XESG configurée](https://www.blackrock.com/ca/investors/en/products/307298/ishares-esg-aware-msci-canada-index-etf/1464253357814.ajax?fileType=csv&fileName=XESG_holdings&dataType=fund). | Même limite : seul le début de table `Ticker` est attendu. | XESG ; dates, poids et composition UNVERIFIED. | Téléchargement prévu, aucun consommateur statistique. AWS UNVERIFIED. |
| `Braw/manual_docs/manifest_docs.csv` | Manifeste manuel, éditeur variable selon document. Aucune ligne réelle disponible. | CSV obligatoire : `file,ticker,doc_type,source_url`. | Aucun inventaire réel de sociétés ou de dates. | Lu par `compute/evidence.py`; absent localement, AWS UNVERIFIED. |
| `Braw/manual_docs/<file>` | PDF, HTML ou HTM référencé par le manifeste ; titres/éditeurs/URLs réels inconnus. | PDF/HTML source, texte extrait par pypdf/HTMLParser. | Aucun fichier réel vérifiable dans le checkout. | Extraction implémentée, exécution UNVERIFIED. L’ingestion générale ne fournit pas de collecte automatisée de ces documents. |
| `Braw/manifest.csv` | Produit par `ingest/fetch_to_s3.py`, pas une source externe. | `path,source,url,note,retrieved_at,bytes,sha256` | Date de récupération par fichier ; aucune ligne locale consultable. | Provenance écrite mais **non consommée** par les calculs. Référencé ; AWS UNVERIFIED. |

Références principales : `docs/data_contract.md`, `ingest/fetch_to_s3.py`, `compute/stats.py::load_raw`, `compute/evidence.py::_read_manifest`.

Les replis manuels attendus sont `data/manual/DCOILBRENTEU.csv`, `data/manual/T10YIE.csv`, `data/manual/xiu_holdings.csv` et `data/manual/xesg_holdings.csv`. Ils ne constituent pas des fichiers observés.

**Univers exact défini** dans `compute/stats.py` et `docs/data_contract.md` :

- Core, 14 tickers : `XIU.TO ENB.TO XOM TLT XBB.TO ZST.TO QQQ SHOP.TO SPY VFV.TO XSP.TO XESG.TO ATD.TO RY.TO`.
- Extra, 21 tickers : `CNQ.TO CNR.TO FTS.TO TD.TO MFC.TO CSU.TO NVDA AAPL MSFT GOOGL AMZN TSLA JPM JNJ PG GLD AGG ESGV XRB.TO XLB.TO XEG.TO`.
- `BTC-USD` et `ETH-USD` sont annoncés dans le starter mais exclus des calculs.
- Aucun dataset WTI, historique complet de composition XIU, référentiel de titres, historique de secteurs ou relation fournisseur/client n’est défini. Leur disponibilité extérieure est UNVERIFIED.

### B3. Qualité et limites de l’ingestion

`ingest/fetch_to_s3.py` apporte des retries, des empreintes SHA-256 et des dates de récupération. Cependant :

- Le contrôle des CSV de holdings cherche essentiellement `Ticker` dans les premiers octets ; il ne valide ni date de composition, ni poids, ni total, ni identité des titres.
- Certains échecs FRED/holdings sont accumulés dans `MISSING` sans arrêt final bloquant de l’ingestion. Un lot peut donc être incomplet.
- Le chargement sélectionne le dernier snapshot par préfixe. Il n’existe pas de manifeste de lot garantissant que prix, macro, holdings et documents appartiennent à une même version cohérente.
- L’upload parcourt les fichiers présents dans le dossier de sortie, susceptible de contenir d’anciens snapshots ; le manifeste courant ne suffit pas à attester la provenance de tous ces objets.
- La fenêtre de prix est fixée dans le code ; aucun ordonnanceur ou mécanisme d’actualisation continue n’est défini dans le dépôt.

### B4. Tables calculées : emplacement, schéma et présence

Chaque table ci-dessous a pour destination exacte **`s3://cascade-s3-bucket/processed/<table>/part-0.parquet`**. Aucun de ces Parquet n’est présent localement. Leur présence actuelle dans AWS est **UNVERIFIED**. Les colonnes sont celles du contrat et des producteurs ; dates de création et version de calcul ne sont pas incluses dans ces schémas.

| Table | Colonnes | Couverture / consommation |
|---|---|---|
| `sensitivities` | `ticker,beta_simple,lo_simple,hi_simple,p_simple,beta_mkt,lo_mkt,hi_mkt,p_mkt,market_ticker,r2_incremental,exxon_equiv,beta_ex2022,lo_ex2022,hi_ex2022,p_ex2022,beta_up,beta_down,oos_hit_rate,oos_n,n_weeks,q_simple,universe` | Jusqu’à 35 tickers après filtre d’historique ; Athena, confiance, scénarios et frontend. |
| `rolling` | `ticker,week,beta_52w,universe` | Séries glissantes par ticker ; frontend et outils de validation. |
| `links` | `link_id,from_node,to_node,beta,lo,hi,p,unit` | Régressions entre facteurs et actifs prédéfinis ; graphe, chaînes. |
| `chain_reconciliation` | `ticker,chain,beta_direct,beta_chain,share_explained` | Sept chaînes définies dans le code actuel, aucune pour XIU ; outils et frontend. |
| `duration_check` | `ticker,duration_years,yield_move_per_10pct_oil_bp,implied_move_pct,measured_move_pct` | TLT, XBB.TO, ZST.TO ; contrôle de cohérence taux/duration. |
| `persona_holdings` | `persona,ticker,weight` | Neuf positions fictives pour trois personas ; **pas les constituants de XIU**. |
| `portfolio_exposure` | `persona,ticker,weight,beta,lo,hi,contribution` | `weight * beta` par position des personas ; outils portfolio. Les `lo/hi` sont ceux du beta du titre, pas des intervalles de contribution. |
| `portfolio_beta` | `persona,beta,lo,hi,p,r2,n_weeks` | Régression du rendement du portefeuille fictif reconstruit ; scénarios persona. |
| `scenarios` | `subject,subject_type,shock_pct,impact_pct,lo_pct,hi_pct` | Tickers et personas ; seulement −30, −15, +15, +30 %. |
| `alternatives` | `persona,holding,alternative,beta_holding,beta_alternative,impact30_before_pct,impact30_after_pct` | Cinq substitutions prédéfinies ; calcul de comparaison fondé sur des betas pondérés. |
| `evidence` | `evidence_id,ticker,doc_type,channel,direction,source_url,section,excerpt,s3_key` | Passages documentaires par ticker/canal ; confidence, edges, outils et frontend. |
| `confidence` | `ticker,channel,label,reason_code,reason_text` | Règle heuristique vert/jaune/gris, pas une probabilité de vérité. |
| `edges` | `from_node,to_node,edge_type,beta,lo,hi,evidence_id` | Liens mesurés et cités produits par l’étape evidence ; pas de relations de chaîne d’approvisionnement. |

Références : `docs/data_contract.md`, `compute/stats.py::write_outputs`, `compute/evidence.py::write_evidence`, `compute/evidence.py::run_part_b`.

Autres artefacts référencés :

| Emplacement | Contenu / statut |
|---|---|
| `Bprocessed/_summary/summary.md` | Résumé texte des résultats ; contenu d’une ancienne lecture visible dans `compute/run_stats.ipynb`, objet actuel UNVERIFIED. |
| `Bprocessed/_evidence_cache/<file>.json` | Candidats documentaires, passages et informations de pages en cache ; aucun cache réel local. |
| `Bevidence/<evidence_id>.txt` et `.txt.metadata.json` | Documents dérivés pour indexation KB ; métadonnées ticker/type/canal/direction/URL/section. Présence et indexation UNVERIFIED. |
| `Bprompts/agent_instructions.md` | Instructions lues par l’agent ; version locale présente dans `prompts/agent_instructions.md`, copie S3 UNVERIFIED. |
| `Btraces/<jobId>.json` | Réponse détaillée écrite par le worker, pas une source financière primaire. Aucun exemple réel local. |
| `Bathena-results/` | Destination configurée des résultats de requête Athena ; fichiers concrets UNVERIFIED. |
| DynamoDB `cascade-jobs` | Jobs, questions, états, réponse, citations, durées et expiration ; aucun enregistrement réel inspecté. |
| `frontend/preview-data.json` | Snapshot local effectivement présent ; détails ci-dessous. |
| `localStorage["cascade.workspace.v1"]` | Profil/portefeuille/notes locaux définis par `frontend/workspace-store.js` ; contenu réel du navigateur non inspecté pendant l’audit. |

### B5. Sorties enregistrées disponibles

`compute/run_stats.ipynb` contient des sorties sauvegardées indiquant :

- Entrées : prix starter **40 049 × 9**, prix supplémentaires **7 530 × 9**, FX **1 245 × 3**, macro **8 281 × 7**, Brent **1 304 × 2**, T10YIE **1 306 × 2**.
- Matrice hebdomadaire **261 × 35**, du **2021-11-19 au 2026-11-13**.
- Tables : sensitivities 35, rolling 7 350, links 12, chain_reconciliation 8, duration_check 3, persona_holdings 9, portfolio_exposure 9, portfolio_beta 3, scenarios 152, alternatives 5.
- Des listes de clés écrites et une lecture de résumé depuis S3 sont enregistrées. Leur date d’exécution exacte, la version des données et leur validité actuelle restent **UNVERIFIED**.

`frontend/preview-data.json` contient réellement : sensitivities **14**, links **11**, chain_reconciliation **6**, duration_check **2**, persona_holdings **9**, portfolio_beta **3**, alternatives **5**, scenarios **68** ; rolling, evidence, confidence et edges sont **vides**. La clé `portfolio_exposure` n’y figure pas ; l’adaptateur la normalise à `[]`.

Les 68 scénarios locaux se composent de 56 scénarios de tickers calculés à partir des betas arrondis du notebook et de 12 scénarios persona anciens. Ce n’est pas un téléchargement attesté du Parquet actuel. Le frontend a retiré les anciens chemins ZST/10 ans et XRB plutôt que de réutiliser leurs coefficients sous de nouveaux noms. Sources : `frontend/README.md`, `frontend/api.js::PREVIEW_PROVENANCE`, `frontend/preview-data.json`.

## C. Investigation XIU : calcul, résultats et attribution

### C1. Trajet exact du prix au graphique

1. `compute/stats.py::load_raw` lit prix starter/supplémentaires, FX, taux et séries FRED depuis S3. Les fichiers de holdings ne sont pas lus.
2. `build_weekly` utilise `adj_close`, la dernière observation disponible de chaque semaine `W-FRI`, puis les différences de logarithmes. Les séries USD sont converties en CAD par ajout du rendement logarithmique USD/CAD. XIU est déjà coté en CAD.
3. Le facteur pétrole est le rendement logarithmique hebdomadaire de **Brent en USD**, pas WTI ni Brent converti en CAD.
4. L’échantillon commence au 19 novembre 2021 ; moins de 150 rendements hebdomadaires entraîne l’exclusion du ticker. Les régressions utilisent les observations communes disponibles ; le helper exige au moins 20 paires.
5. `sensitivities` estime le modèle, les diagnostics et les variantes. `write_outputs` écrit les Parquet. Athena fournit ensuite les lignes aux outils Lambda.
6. Aujourd’hui, `frontend/api.js::loadInvestigation` lit par défaut `frontend/preview-data.json`. `frontend/app.js` sélectionne `XIU.TO`, puis `render.js` affiche la ligne `sensitivities` et `graph.js` construit une arête Brent→XIU.

Modèle principal :

```text
rendement_log_XIU_CAD[t] = constante + beta * rendement_log_Brent_USD[t] + résidu[t]
OLS ; erreurs standards Newey–West/HAC à 4 retards
intervalle à 95 % = beta ± 1,96 × erreur standard
```

**Contrôles XIU : aucun.** Pour XIU, `market_ticker_for` renvoie `none` et les champs `beta_mkt/lo_mkt/hi_mkt/p_mkt` recopient le modèle simple. Ce ne sont pas les résultats d’une seconde régression contrôlée. Pour certaines actions, SPY ou XIU sert de contrôle de marché ; les taux, FX et breakeven ont des régressions séparées, pas des contrôles simultanés dans le modèle XIU. Sources : `compute/stats.py::_fit_hac`, `regress`, `regress_with_control`, `market_ticker_for`, `sensitivities`.

### C2. Chiffres disponibles et limites

| Mesure XIU | Valeur enregistrée | Interprétation / preuve |
|---|---|---|
| Beta simple | `0.010571` | Présent notebook et preview ; modèle ancien enregistré, reproduction actuelle UNVERIFIED. |
| Intervalle 95 % | `[-0.032437, 0.053579]` | Contient zéro ; incertitude importante relativement au coefficient. |
| p-value | `0.6299906` | Pas de signal net significatif au seuil de 5 % dans cette sortie. |
| q-value BH | `0.7112797` | Correction des comparaisons multiples sur l’univers calculé. |
| Taille | `261` semaines | Observations du modèle enregistré, pas durée de déploiement. |
| Fenêtre enregistrée | `2021-11-19` → `2026-11-13` | Dates de semaines ; un label vendredi peut représenter un dernier cours disponible jeudi. Pas une date de vérification. |
| Beta hors 2022 | Environ `-0.011` | Visible arrondi à trois décimales dans le résumé enregistré du notebook ; champ absent du snapshot frontend. Ne pas inventer des décimales supplémentaires. |
| Intervalle hors 2022 | `[-0.057657, 0.035834]` | Présent dans le snapshot ; contient zéro. |
| p-value hors 2022 | `0.6473019` | Pas de confirmation d’un effet net significatif. |
| Beta semaines de hausse / baisse du pétrole | `-0.065858` / `0.022323` | Sous-échantillons ; pas d’intervalles fournis pour ces deux valeurs. |
| Test hors échantillon | `oos_hit_rate=0.1`, `oos_n=10` | 1 signe correct sur 10 semaines sélectionnées ; ce n’est pas une précision générale de 10 % sur tous les rendements. |
| Série rolling XIU | Absente du preview | Code de calcul présent ; aucune série XIU complète visible dans les sorties locales inspectées. |
| `r2_incremental`, `exxon_equiv` | Non fournis dans la ligne frontend | Colonnes du calcul, valeurs XIU non récupérables des affichages tronqués examinés : UNVERIFIED. |

Sources : `frontend/preview-data.json`, `compute/run_stats.ipynb` — sortie de sensibilités et résumé enregistré, `compute/stats.py::out_of_sample`, `rolling_betas`.

Le test hors échantillon entraîne le modèle jusqu’au 31 décembre 2024, puis examine à partir du 1er janvier 2025 les semaines du décile supérieur de variation absolue du pétrole. Le signe prédit utilise constante et beta. Le rolling est calculé sur 52 observations disponibles ; après suppression des manquants, cela ne garantit pas exactement 52 semaines calendaires. Les prix manquants et leur fraîcheur dans une semaine ne font pas l’objet d’un audit de qualité exhaustif.

**Lecture simple :** un beta de 0,010571 décrit une association historique très faible à l’échelle des rendements logarithmiques. Il ne signifie pas « 1,0571 % du fonds est pétrolier ». Une variation du pétrole n’entraîne pas mécaniquement une variation de XIU. Les hypothèses de compensation entre entreprises restent à tester.

### C3. Scénarios XIU disponibles localement

| Choc Brent | Impact conditionnel local, % | Intervalle transformé, % |
|---|---:|---|
| −30 % | −0,376331 | [−1,892884 ; 1,163665] |
| −15 % | −0,171651 | [−0,866980 ; 0,528555] |
| +15 % | 0,147852 | [−0,452320 ; 0,751641] |
| +30 % | 0,277730 | [−0,847420 ; 1,415648] |

Source : `frontend/preview-data.json`. Formule de `compute/stats.py::shock_impact_pct` : `100 * (exp(beta * log(1 + choc/100)) - 1)`. Les bornes du coefficient sont transformées puis remises dans l’ordre. Il s’agit de **scénarios statistiques conditionnels**, sans trajectoire temporelle ni intervalle de prédiction des futurs cours. Les lignes locales sont illustratives ; résultats AWS correspondants **UNVERIFIED**.

### C4. Ce qui existe pour les constituants

| Question | Réponse étayée |
|---|---|
| Holdings XIU disponibles ? | URL et chemin prévus dans `ingest/fetch_to_s3.py` ; aucun CSV local. Présence AWS UNVERIFIED. |
| Poids datés disponibles ? | Aucun tableau normalisé, aucune ligne ni date de composition consultable. Un nom de snapshot ne remplace pas la date officielle du fonds. |
| Betas de sociétés disponibles ? | Oui, pour plusieurs tickers de l’univers dans les sorties sauvegardées ; **leur appartenance à XIU à une date donnée n’est pas établie**. |
| Exemples enregistrés | ENB.TO `0.091709`, CNQ.TO `0.444992`, RY.TO `-0.020245`, ATD.TO `-0.074101`, SHOP.TO `-0.164236`. `compute/run_stats.ipynb` contient également CNR.TO, FTS.TO, TD.TO, MFC.TO et CSU.TO. Ce ne sont pas des contributions. |
| Contributions calculables immédiatement ? | Non : poids datés, identité des titres, couverture des prix, fenêtre commune et méthode d’attribution manquent. Aucune fonction n’effectue la jointure holdings/betas. |
| Secteurs / non-énergie ? | Aucun tableau normalisé de classification et poids sectoriels relié au modèle. Aucun résidu « non-énergie » défendable calculé. |
| XEG utilisé comme sleeve XIU ? | Non dans l’attribution actuelle. XEG.TO a sa propre sensibilité, enregistrée à `0.441621`, mais aucune identité avec la poche énergie de XIU n’est démontrée. |
| Autre proxy ? | `exxon_equiv` divise le beta par celui de XOM : comparaison de sensibilité, pas poids pétrolier. Les contributions des personas sont des betas pondérés, pas l’intérieur d’un ETF. |

Les neuf positions de `persona_holdings` sont des hypothèses de démonstration : Robert détient TLT/XBB/ENB/RY ; Amira QQQ/SHOP/XIU ; Mateo XIU/VFV. Elles répondent à « que contient le portefeuille fictif de cet investisseur ? », jamais à « que contient XIU ? ». Sources : `compute/stats.py::PERSONAS`, `persona_holdings`, `portfolio_exposure`, `docs/data_contract.md`.

Attention à deux différences méthodologiques dans `compute/stats.py` :

- `portfolio_exposure` calcule `weight * beta_simple`, tandis que `portfolio_beta` régresse le logarithme d’une somme de rendements simples pondérés. Ces contributions ne s’additionnent pas exactement au beta actuel du portefeuille. Le commentaire ancien qui suggère l’égalité est dépassé.
- `alternatives` utilise encore la somme des betas pondérés. Ses résultats sont des approximations de comparaison, pas nécessairement le résultat d’une nouvelle régression du portefeuille substitué.

## D. Documents et preuves

### D1. Inventaire documentaire vérifiable

**Aucun PDF, filing HTML, factsheet ou manifeste documentaire réel n’est présent localement.** Aucun titre original, passage de société, numéro de page ou URL de filing ne peut donc être certifié à partir du checkout.

| Document ou référence | Émetteur / date mentionnés | Titre, URL et fichier | Statut et usage |
|---|---|---|---|
| `raw/manual_docs/manifest_docs.csv` | Non connus | Aucun manifeste réel disponible | RÉFÉRENCÉ ; doit identifier les fichiers, tickers, types et URLs. AWS UNVERIFIED. |
| Documents `raw/manual_docs/<file>` | Non connus | Aucun nom individuel connu | PDF/HTML/HTM attendus ; sociétés couvertes et disponibilité UNVERIFIED. |
| Factsheet TLT | iShares, 2026-09-30 selon code/contrat | Titre exact, URL et nom de fichier non fournis | Valeur de duration `14.63` codée en dur ; source documentaire UNVERIFIED. |
| Page produit XBB.TO | iShares, 2026-10-23 selon code/contrat | Titre exact, URL et nom de fichier non fournis | Duration `6.72` codée en dur ; source UNVERIFIED. |
| Factsheet ZST.TO | BMO, 2026-10-30 selon code/contrat | Titre exact, URL et nom de fichier non fournis | Duration `0.40` codée en dur ; source UNVERIFIED. |
| Extraits Banque du Canada demandés dans le prompt | Banque du Canada ; date inconnue | Aucun document précis identifié | Instruction de recherche dans `prompts/agent_instructions.md`, pas un document fourni. |
| Exemples documentaires des tests | Entités/URLs factices | Chaînes HTML, noms tels que `a.html`, types tels que `10-K` | Fixtures de `compute/test_evidence.py` et tests agent/outils ; ne doivent jamais devenir des citations officielles. |

Sources : `docs/data_contract.md`, `compute/stats.py::DURATION_YEARS`, `compute/evidence.py`, `compute/test_evidence.py`, `prompts/agent_instructions.md`.

### D2. Ce que l’extraction fait réellement

`compute/evidence.py` implémente le parcours suivant :

1. Lire les quatre colonnes du manifeste dans S3 et récupérer le fichier.
2. Extraire les pages PDF avec pypdf, ou le texte HTML en excluant scripts et styles. Aucun OCR pour PDF scanné n’est implémenté.
3. Segmenter en passages d’environ 1 500 caractères, avec chevauchement de 200 ; sélectionner jusqu’à 25 passages par document selon des mots-clés.
4. Demander à Bedrock un canal, une direction et un extrait. Modèle configuré par défaut : `global.anthropic.claude-sonnet-5-5` ; disponibilité effective **UNVERIFIED**.
5. Accepter un extrait uniquement s’il contient au plus 40 mots et correspond à une sous-chaîne du passage après normalisation des espaces. Une réponse invalide peut être réessayée.
6. Dédupliquer et conserver au plus trois extraits par couple ticker/canal, puis écrire la table evidence et les textes/métadonnées destinés à la KB.
7. Produire les labels de confiance et les arêtes, puis effectuer des contrôles de sortie si la fonction correspondante est appelée.

**Exécution : UNVERIFIED.** `compute/run_evidence.ipynb` n’a aucune sortie d’exécution enregistrée. Cela n’exclut pas une exécution ailleurs, mais le dépôt ne l’atteste pas.

### D3. Ce que les preuves ne garantissent pas encore

- Le contrôle de sous-chaîne prouve seulement que le texte retenu existe dans le texte extrait. Il ne vérifie ni l’authenticité de l’émetteur, ni la validité de l’URL, ni une relation causale.
- `source_url` est copié du manifeste. La chaîne ne l’ouvre pas pour vérifier qu’il mène au document correspondant.
- Le numéro de page existe pendant l’extraction et dans les candidats/cache, mais disparaît de `EVIDENCE_COLUMNS`, des documents KB et des métadonnées KB persistées. `section` est fourni par le modèle et n’est pas validé comme véritable titre de section.
- Le contrat ne contient ni `document_title`, ni `issuer`, ni `publication_date`, ni date de vérification, ni empreinte du document dans la table evidence.
- Le cache dépend du nom de fichier et de certaines métadonnées du manifeste, sans empreinte du contenu ni version de modèle. Un fichier remplacé sous le même nom peut réutiliser une extraction ancienne.
- Les identifiants d’extraits dépendent du rang retenu ; leur stabilité entre versions n’est pas garantie. `run_part_b` privilégie les candidats en cache lorsqu’ils existent, ce qui impose de contrôler la cohérence avec la table publiée et la KB.
- `write_evidence` supprime les objets du préfixe qui ne correspondent plus aux identifiants retenus avant publication des nouveaux textes. Une exécution sur corpus vide peut supprimer tous les textes précédents de ce préfixe et publier une table vide. Aucun démarrage de synchronisation KB n’est implémenté.
- Les contrôles d’extraits et de nombre de fichiers peuvent réussir avec zéro extrait ; aucun seuil de couverture documentaire XIU n’est imposé.
- Les catégories de `MAIN_CHANNEL` sont codées en dur. Elles ne démontrent pas les mécanismes d’une société. La règle de confiance cherche une direction documentaire compatible par ticker, sans exiger systématiquement le même canal que la ligne de confiance.

Références : `compute/evidence.py::extract_pages`, `split_passages`, `passages_for_pages`, `validate_answer`, `select_evidence`, `write_evidence`, `build_confidence`, `run_part_b`, `check_outputs`, `EVIDENCE_COLUMNS`, `MAIN_CHANNEL`.

La règle de label est explicite dans `compute/evidence.py::label_row` : vert si p-value simple < 0,05, résultat hors 2022 significatif de même signe, et ratio chaîne/direct ≥ 0,5 ou document de même direction ; jaune si le signal simple est significatif mais les autres conditions échouent ; gris sinon. Pour les tickers extra, vert/jaune exigent aussi q-value < 0,10. Avec la p-value XIU enregistrée, cette règle conduirait au gris ; **ce n’est pas une ligne confidence observée**, puisque cette table est vide localement. Les formulations de type « la chaîne explique X % » dans les raisons produites devraient être ramenées à un contrôle de cohérence, sans interprétation causale.

### D4. Pourquoi le compteur reste à zéro

`frontend/render.js::renderEvidence` utilise exactement : `tables.evidence.filter(row => row.ticker === ticker)`. Dans le snapshot, cette table est vide. Même avec des documents ENB ou des preuves taguées `macro`, le panneau XIU resterait vide tant qu’aucune relation explicite ne les relie à l’investigation.

Avec des données, le compteur compte des **passages**, pas des documents distincts. Les citations reçues par le chat sont affichées séparément dans `frontend/agent-render.js` et ne sont pas injectées dans `tables.evidence`. Ces limites sont des questions de contrat et de raccordement, pas seulement d’apparence visuelle.

## E. Intégration AWS : code, configuration, preuve

### E1. Matrice des services

| Service | Code implémenté | Configuration trouvée | Intégration active vérifiée ? |
|---|---|---|---|
| S3 | Ingestion, lecture raw, écriture Parquet, documents/cache/KB, prompts et traces. | Bucket par défaut `cascade-s3-bucket`, préfixes documentés, politiques IAM. | **UNVERIFIED** ; uniquement anciennes traces notebook pour une partie des sorties. |
| Athena | `lambdas/tools/app.py` lance, surveille et pagine les requêtes. | Base/workgroup `cascade`, sortie `s3://cascade-s3-bucket/athena-results/`, surcharge par variables d’environnement. | **UNVERIFIED** ; FakeAthena dans les tests, aucun résultat live contrôlé. |
| Glue | Utilisé indirectement comme catalogue Athena ; autorisations GetDatabase/GetTable/GetTables/GetPartitions. | Nom de base dans le contrat et IAM. | **UNVERIFIED** ; pas de DDL, crawler ou script de création des tables. |
| Bedrock modèles | Converse pour l’extraction ; modèle Strands pour l’agent. | Modèle par défaut et variables d’environnement. | **UNVERIFIED** ; accès, région/profil et version effectivement déployée inconnus. |
| Bedrock AgentCore | Worker appelle `invoke_agent_runtime`; `agent/agent.py` expose un agent Strands. | `AGENT_RUNTIME_ARN` requis ; politique worker contient un ARN de runtime spécifique, non reproduit ici. | **UNVERIFIED** ; un ARN dans un fichier ne prouve pas l’existence ou le fonctionnement du runtime. |
| Bedrock Agents classiques | Documentation d’action group, noms `cascade-agent` / alias `live`, enveloppe compatible dans les outils. | Documentation et ancien rôle d’agent. | **UNVERIFIED** ; ce n’est pas le chemin d’appel du worker actuel. |
| Bedrock Knowledge Bases | `agent/agent.py::search_evidence` appelle `retrieve`, avec filtre ticker optionnel et trois résultats. | `KB_ID` optionnel ; nom attendu `cascade-evidence` ; exports S3 prêts à indexer. | **UNVERIFIED** ; aucun manifeste de KB/vector store/data source ou reçu de synchronisation. |
| Bedrock Guardrails | Paramètres optionnels, collecte d’informations de garde-fou dans l’agent/worker. | `GUARDRAIL_ID`, `GUARDRAIL_VERSION` optionnels ; nom documentaire. | **UNVERIFIED** ; pas obligatoirement activé. |
| Lambda | Handlers tools, submit, worker, status et tests unitaires. | Noms `cascade-tools`, `cascade-submit`, `cascade-worker`, `cascade-status`, politiques et trusts. | **UNVERIFIED** ; aucune version déployée ni invocation réelle contrôlée. |
| SQS | submit envoie ; worker traite les records, gère certains throttles avec échec partiel. | `QUEUE_URL`; noms `agent-jobs`, `agent-jobs-dlq`. | **UNVERIFIED** ; mapping, visibilité, redrive et DLQ non définis dans le dépôt. |
| DynamoDB | Création/lecture/mise à jour des jobs et transitions conditionnelles. | `JOBS_TABLE`, nom `cascade-jobs`, clé `jobId`, champ TTL `expiresAt`. | **UNVERIFIED** ; écrire un champ TTL ne prouve pas que le TTL est activé sur la table. |
| API HTTP / hébergement | Handlers avec réponses de type API Gateway et adaptateurs fetch côté navigateur. | Aucun endpoint frontend configuré ; pas de routes/CORS/authentification définis ici. | **UNVERIFIED** ; aucune URL de service opérationnel disponible dans la configuration frontend. |

Références : `docs/data_contract.md`, `ingest/fetch_to_s3.py`, `compute/*.py`, `agent/agent.py`, `lambdas/*/app.py`, `iam/*.json`, `frontend/config.js`.

### E2. Parcours d’une question

1. `submit` valide question (1 à 1 000 caractères), persona, niveau et session éventuelle ; crée un UUID et un job `PENDING` avec expiration prévue à 24 h ; envoie le job dans SQS.
2. `worker` tente la transition conditionnelle `PENDING → RUNNING`, invoque AgentCore et transmet question/persona/niveau.
3. `agent/agent.py` charge les instructions S3, construit un nouvel agent Strands, puis peut appeler les six outils Lambda et la recherche KB.
4. Les outils Lambda interrogent Athena. Ils ne téléchargent ni ne calculent les holdings XIU. L’agent récupère des passages KB, et non les PDF originaux par défaut.
5. `worker` écrit `traces/<jobId>.json`, puis le résultat `DONE` ou `FAILED` dans DynamoDB ; `status` renvoie au navigateur les champs autorisés.

`sessionId` est transmis à AgentCore, mais aucun historique conversationnel persistant n’est explicitement rechargé dans le code de l’agent. Une conversation multi-tour avec mémoire est donc **UNVERIFIED**, même si le frontend conserve les messages de la page.

### E3. Points de raccordement à vérifier avant une démonstration live

- **Rôles et modèle :** `iam/cascade-agent-role.json` mentionne un profil Opus tandis que le code sélectionne un profil Sonnet par défaut. Le trust du rôle existant vise `bedrock.amazonaws.com`. Aucun rôle d’exécution AgentCore complet n’est identifié ; les permissions de lecture du prompt S3 et d’invocation Lambda requises par l’agent actuel ne sont pas établies par ce rôle. Ce sont des écarts dans le dépôt, pas une preuve que la configuration externe est incorrecte.
- **Placeholders :** les politiques contiennent des identifiants KB/garde-fou à remplacer. Les politiques et leur présence ne prouvent pas leur attachement aux ressources. Les permissions de logs sont décrites séparément dans `iam/README.md`.
- **Jobs :** PutItem puis SendMessage ne forment pas une transaction. Un échec entre les deux peut laisser un job `PENDING`. Un arrêt après passage à `RUNNING` peut laisser un job bloqué. Le traitement d’exceptions et la configuration de retries/DLQ nécessitent une vérification opérationnelle ultérieure.
- **Fraîcheur :** les outils Athena gardent des résultats en cache dans le processus sans TTL ni identifiant de version. Leur `as_of` vient essentiellement du maximum de `rolling.week`, pas d’une date de vérification des sources.
- **Précision :** les réponses d’outils arrondissent les flottants à trois décimales. Cela peut écraser de petits coefficients ou afficher une p-value arrondie à zéro. Les traces d’outils de l’agent limitent le texte de sortie à 1 500 caractères : ce n’est pas une API numérique complète pour le frontend.
- **Garde-fous :** l’exigence de nombres provenant des outils et de citations se trouve dans le prompt. Aucune validation finale ne bloque systématiquement une réponse financière lorsque les outils échouent ou lorsque les preuves sont absentes.

Sources : `iam/README.md`, `iam/cascade-agent-role.json`, `iam/cascade-agent-role.trust.json`, `iam/cascade-worker-lambda.json`, `lambdas/submit/app.py`, `lambdas/worker/app.py`, `lambdas/tools/app.py`, `agent/agent.py`, `prompts/agent_instructions.md`.

## F. Frontend et API : champs exacts et états indisponibles

### F1. Recherche chiffrée

`frontend/config.js` contient actuellement :

```javascript
investigationUrl: null,
submitUrl: null,
statusUrl: null
```

En preview, `frontend/api.js` charge `./preview-data.json`. En mode backend, il attend un **GET** sur `investigationUrl` avec `?ticker=XIU.TO`. La réponse attendue est un objet contenant les tableaux du contrat :

```json
{
  "sensitivities": [],
  "links": [],
  "chain_reconciliation": [],
  "scenarios": [],
  "evidence": [],
  "confidence": [],
  "edges": [],
  "rolling": [],
  "duration_check": [],
  "persona_holdings": [],
  "portfolio_exposure": [],
  "portfolio_beta": [],
  "alternatives": []
}
```

Cet exemple montre **la forme**, pas des résultats disponibles. `sensitivities` est obligatoire comme tableau ; une ligne valide du ticker sélectionné est ensuite nécessaire à l’affichage du beta. Les autres tableaux omis deviennent `[]`. `normalizeTables` élimine les clés inconnues : ajouter aujourd’hui `etf_holdings` dans une réponse ne l’exposerait pas au rendu.

**Aucune Lambda actuelle ne renvoie directement cette enveloppe d’investigation.** `lambdas/tools/app.py` est une interface d’outils pour l’agent ; ses réponses sont imbriquées, réparties par fonction et parfois arrondies/tronquées. Il faut un endpoint agrégateur ou un adaptateur explicite, avec provenance, et pas analyser le texte libre de l’agent.

### F2. Champs nécessaires au rendu existant

| Élément affiché | Champs existants nécessaires | Limite actuelle |
|---|---|---|
| Beta et intervalle | Ligne `sensitivities` avec `ticker,beta_simple,lo_simple,hi_simple,n_weeks` valides ; p-values et autres champs pour les diagnostics. | Le snapshot XIU est présent mais ancien/non vérifié. |
| Arête statistique Brent→ETF | Même ligne `sensitivities` ; `p_simple` et `n_weeks` enrichissent l’inspecteur. | Association statistique, pas causalité. |
| Liens macro | `links`: `link_id,from_node,to_node,beta,lo,hi,p,unit`. | Le graphe ne connaît que `us10y,ca10y,ca2y,usdcad,breakeven` comme facteurs intermédiaires. |
| Chaîne de transmission | `chain_reconciliation`: `ticker,chain,beta_direct,beta_chain,share_explained`, et liens correspondants pour le réseau. | Aucune chaîne XIU produite. Le ratio chaîne/direct peut dépasser 1 ou être négatif ; ce n’est pas une part causale. |
| Arête documentaire | `edges`: `from_node:"oil",to_node:<ticker>,edge_type:"cited",evidence_id`; jointure sur `evidence.evidence_id`. | Le graphe actuel n’accepte pas un réseau général entreprise→entreprise→ETF. |
| Preuve inspectable | `evidence`: `evidence_id,ticker,doc_type,channel,direction,source_url,section,excerpt,s3_key`. | Filtre ticker exact ; original title/issuer/publication date/page/verification absents du contrat. |
| Label de confiance | `confidence`: `ticker,channel,label,reason_code,reason_text`. | Vide en preview ; ne doit pas être inventé côté interface. |
| Scénario | `scenarios`: `subject:<ticker>,subject_type:"ticker",shock_pct,impact_pct,lo_pct,hi_pct`. | Les quatre chocs uniquement ; valeurs invalides/absentes → indisponible. |
| Rolling | `rolling`: `ticker,week,beta_52w` ; au moins deux points valides pour le tracé. | Preview vide ; l’outil asset ne renvoie que quatre dernières observations et sous une autre enveloppe. |
| Attribution des constituants | **Aucun schéma existant ne la permet.** | Le rendu ETF affiche systématiquement l’indisponibilité. Nécessite nouveau contrat, producteur, API et rendu. |

Références : `frontend/api.js::TABLES`, `normalizeTables`, `frontend/formatters.js::hasEstimate`, `frontend/graph.js::buildNetwork`, `frontend/render.js::renderDecomposition`, `renderEvidence`, `renderScenario`, `renderExpert`.

Le graphe fabrique ses arêtes mesurées depuis `sensitivities` et `links`, pas depuis toutes les lignes `edges` de type mesuré. Les preuves du ticker peuvent aussi devenir automatiquement des arêtes citées si la table edges les omet. Les hypothèses sont explicitement créées par l’utilisateur et restent non mesurées. Les dates affichées dans l’inspecteur proviennent des libellés généraux de provenance, pas d’une date propre à chaque relation.

### F3. Chat asynchrone

`frontend/agent-api.js` prévoit :

```text
POST submitUrl
corps : {question, persona, level, sessionId?}
persona : robert | amira | mateo
level : beginner | expert
réponse HTTP 202 : {jobId, sessionId}

GET statusUrl, en remplaçant {id} par jobId
réponse : {jobId, status, answer?, toolCalls?, citations?, error?, durationMs?}
status : PENDING | RUNNING | DONE | FAILED
```

Les appels d’outils de l’agent ont la forme `{name,input,output}`. Les citations actuelles ont la forme `{text,source_url,section,ticker,channel}`. `status` ne renvoie pas tous les champs persistés : notamment `traceKey` et les informations de garde-fou ne sont pas exposés par sa liste autorisée. Sources : `agent/agent.py`, `lambdas/status/app.py`, `frontend/agent-render.js`.

Le client soumet une fois, puis interroge l’état environ toutes les 1,2 seconde, avec délai global prévu de 120 secondes. L’annulation navigateur ne supprime pas le job AWS. `frontend/app.js` ajoute le ticker, Brent et la devise à la question textuelle ; il n’existe pas de champ structuré `ticker` dans le contrat submit.

Avec les URLs `null`, le chat affiche une connexion non configurée. L’explication locale de `frontend/render.js::previewExplanation` est une logique déterministe de démonstration, pas une réponse de Bedrock. Le workspace charge toujours le snapshot local via `loadSnapshot`, même lorsque la recherche est réglée sur backend.

### F4. Explication des états actuels

| État visible | Cause exacte | Travail nécessaire |
|---|---|---|
| Holdings breakdown unavailable | Branche ETF de `renderDecomposition` sans implémentation d’attribution ; aucun tableau de constituants. | Données + calcul + nouveau contrat + backend + frontend. |
| Transmission chain not supplied for XIU | Absence de XIU dans `CHAINS` et dans `chain_reconciliation`. | Définir/tester une méthode et des relations étayées ; ne pas inventer un chemin. |
| 0 documents supplied | `evidence: []` ; filtre ticker exact. | Documents, extraction vérifiée, rattachement à l’investigation et API de preuves. |
| Original title / Issuer / Published : Not supplied | Champs absents du contrat et rendu volontairement explicite. | Enrichir la provenance documentaire et son transport. |
| Source link : Not independently verified | URL éventuellement fournie, mais aucune vérification de source attestée. | Contrôle de source et métadonnées de vérification. |
| Rolling history unavailable | `rolling: []` dans le preview. | Publier une série actuelle avec provenance et la transporter dans le bon format. |
| Backend not configured | Trois URLs `null`. | Endpoints réellement déployés et configuration explicite, après vérification externe autorisée. |
| WTI unavailable | Aucun dataset ni calcul WTI dans le contrat. | Nouvelle source/calcul si souhaité ; hors priorité XIU/Brent. |
| Données de couverture/date manquantes en mode API | Contrat sans provenance de lot complète ; `API_PROVENANCE` affiche « Not supplied ». | Métadonnées d’investigation versionnées. |

Le texte « failed to load page » signalé antérieurement ne permet pas d’identifier une cause réseau précise. Aucun navigateur ni serveur n’a été testé pendant cet audit. Cause de cet incident : **UNVERIFIED**. Les états métier ci-dessus sont, eux, directement traçables dans les sources.

## G. Lacunes et priorités : rendre une investigation XIU défendable

### G1. Ordre recommandé et critères de sortie

| Priorité | Action minimale | Nature du travail | Critère concret de réussite |
|---|---|---|---|
| P0 | Fixer une version de référence des données et du calcul ; séparer ancien snapshot et résultats actuels. | Qualité des données + calcul + intégration | Un identifiant de run, versions/hashes des entrées, dates de couverture, code de référence ; aucune sortie ancienne présentée comme actuelle. |
| P1 | Obtenir et normaliser une composition officielle datée de XIU. | Nouvelles données publiques + ingestion | Date officielle conservée, poids normalisés, identités résolues, cash/dérivés/non appariés visibles, source et empreinte enregistrées. |
| P2 | Joindre les constituants aux prix puis produire une attribution cohérente avec le modèle annoncé. | Données de prix complémentaires + nouveau calcul | Couverture pondérée publiée, échantillon et devise communs, méthode mesurée/proxy explicite, incertitude et résidu documentés. |
| P3 | Documenter quelques sociétés réellement présentes dans la composition retenue. | Nouveaux documents publics + extraction + revue | Extraits vérifiés avec titre, émetteur, date, page, URL et lien vers société/holding ; absence de preuve conservée explicitement. |
| P4 | Publier une API d’investigation versionnée et relier le graphe aux preuves et contributions. | Contrat + backend + frontend | Un clic sur une relation ouvre le calcul ou le passage correspondant, avec dates et limites ; états manquants exacts. |
| P5 | Vérifier le parcours AWS/agent sur une même version de données. | Configuration + intégration + évaluation | Job submit→DONE, requêtes/outils documentés, KB synchronisée, citations traçables et réponse cohérente avec les chiffres de l’interface. |

Les actions ci-dessus sont des propositions. **Aucune n’a été implémentée ou exécutée dans cet audit.**

### G2. Holdings datés : le premier verrou

À partir du CSV officiel configuré dans `ingest/fetch_to_s3.py`, il faut conserver séparément : date de composition du fonds, date de récupération, URL, hash, identifiant du fonds, identifiant du titre et poids. Le préambule iShares doit être parsé ; il ne faut pas déduire la date des holdings du nom du dossier.

La jointure doit expliciter les différences de symboles entre fournisseur de holdings et fournisseur de prix, les classes d’actions, les liquidités et les lignes non appariées. Une société déjà présente dans `compute/stats.py` ne doit devenir un constituant XIU qu’après cette vérification. L’absence de prix pour une partie du fonds doit être affichée comme poids non couvert.

### G3. Attribution : choisir une promesse réalisable

**Option MVP : composition courante appliquée à des sensibilités historiques.** Pour chaque constituant, poids daté × beta historique comparable. Cela décrit une **estimation par composition courante**, pas l’attribution exacte du rendement historique de XIU. Utiliser la même devise CAD, le même facteur Brent USD, les mêmes observations et le même choix de contrôles. Ne pas mélanger les betas de sociétés contrôlés par XIU avec le beta XIU non contrôlé.

**Option historique plus rigoureuse :** disposer de poids antérieurs à chaque période, calculer les contributions de rendement simple `poids[t−1] × rendement_simple[t]`, puis régresser ces contributions sur un facteur et un échantillon communs. Avec un modèle linéaire commun, les pentes s’additionnent au beta du portefeuille simple reconstruit. Celui-ci doit être distingué du beta actuel de XIU calculé sur rendements logarithmiques. L’écart avec le fonds observé peut refléter frais, cash, dérivés, dates et suivi de l’indice ; il ne doit pas être renommé arbitrairement « exposition non-énergie ».

Dans les deux cas, les intervalles des agrégats nécessitent la covariance entre contributions, par exemple avec une estimation jointe adaptée ou un bootstrap par blocs. Additionner des bornes individuelles ne donne pas un intervalle de confiance valide pour le total. Le choix de méthode doit être documenté avant affichage.

**Règles à conserver :** ne jamais soustraire un poids sectoriel à un beta ; ne jamais présenter XEG comme la poche énergie exacte de XIU ; ne jamais interpréter un produit de coefficients de régressions distinctes comme une preuve de causalité. Sources motivant ces précautions : `compute/stats.py::portfolio_exposure`, `portfolio_beta`, `chain_reconciliation`, `alternatives`, `frontend/render.js::renderDecomposition`.

### G4. Documents et graphes : limiter le périmètre, garder les preuves

Après confirmation des holdings, sélectionner quelques sociétés utiles à l’explication, puis obtenir leurs publications originales. Prioriser des passages qui décrivent explicitement revenus, coûts, transport, intrants ou exposition macro. Un mécanisme mentionné dans un filing ne fournit pas à lui seul un coefficient financier ni une relation fournisseur/client.

Chaque relation économique proposée doit avoir son type, sa date et son extrait justificatif. Une relation hypothétique doit rester marquée comme telle. Le graphe devra distinguer au minimum : appartenance au fonds avec poids daté, relation statistique avec modèle/intervalle, mécanisme documenté avec preuve, hypothèse sans résultat. Le contrat actuel `edges` ne porte pas ces informations complètes.

**Extension minimale proposée — NON IMPLÉMENTÉE, hors contrat actuel :**

| Objet proposé | Informations à ajouter |
|---|---|
| Composition ETF | `etf_ticker,holding_ticker,security_id,issuer,sector,weight,holdings_as_of,retrieved_at,source_url,source_hash` |
| Attribution | Identifiants ETF/holding/run/modèle, fenêtre commune, benchmark/devise, poids, beta/intervalle/n, contribution/intervalle, méthode, poids couvert/non apparié. |
| Document | Identifiant stable, titre original, émetteur, date de publication, URL originale, clé S3/version/hash, état/date de vérification. |
| Passage | Identifiant stable, document, société, texte exact, page/section, canal/direction, méthode/version d’extraction. |
| Relation | Nœuds source/cible, type, dates, modèle ou evidence IDs, limites ; aucune causalité implicite. |
| Investigation | Identifiant de run, couverture, date de calcul, date de vérification, versions des sources, provenance preview/backend. |

Fichiers concernés lors d’une future implémentation autorisée : `docs/data_contract.md`, `ingest/fetch_to_s3.py`, `compute/stats.py`, `compute/evidence.py`, endpoint d’investigation à créer, `frontend/api.js`, `frontend/render.js`, `frontend/graph.js`, `frontend/agent-render.js`. Ce rapport ne modifie aucun de ces fichiers.

### G5. Preuves minimales d’un fonctionnement AWS

Lors d’une session ultérieure explicitement autorisée, collecter :

1. Inventaire/version des objets sources, manifestes et Parquet correspondant au run ; contrôle de leur schéma et de leur couverture.
2. Définition des tables Glue et identifiants de requêtes Athena avec résultats correspondant au même run.
3. Identité/version du runtime, modèle accessible, permissions réellement attachées, configuration des files/jobs et routes HTTP.
4. Reçu de synchronisation KB, nombre de documents indexés et retrieval ramenant un passage vérifiable du corpus choisi.
5. Job de bout en bout, trace d’outils, réponse et citations comparées aux tables affichées.
6. Petit jeu d’évaluation dans `eval/questions.json` : XIU non significatif, preuves absentes, mauvais ticker, choc non supporté, distinction poids/beta, source correcte et refus d’inventer une relation.

La présence du code d’agent ne remplace aucun de ces contrôles. Une réponse fluide ne prouve pas qu’Athena ou la KB a été consultée avec succès.

## H. Handoff et prochaines étapes les plus petites

### H1. Trois actions prioritaires pour une équipe sur 24 heures

1. **Données et calcul :** produire un lot XIU daté et traçable, résoudre les symboles et calculer une attribution à composition courante clairement marquée comme approximation. Si la couverture est insuffisante, montrer les positions couvertes et le poids manquant, sans inventer le reste. Responsabilité : ingestion/quant. Références : `ingest/fetch_to_s3.py`, `compute/stats.py`.
2. **Preuves et API :** réunir un petit corpus de vrais documents des sociétés confirmées, préserver pages/titres/dates, et publier une enveloppe d’investigation réunissant statistiques, holdings et preuves du même run. Responsabilité : data/backend. Références : `compute/evidence.py`, `docs/data_contract.md`, `lambdas/tools/app.py` ; endpoint GET à créer.
3. **Démonstration intégrée :** raccorder une seule investigation XIU/Brent au frontend, puis vérifier séparément le chat AWS. La même sélection doit permettre découvrir → mesurer → relier → vérifier → expliquer. Si AWS n’est pas vérifié, conserver une démonstration locale explicitement étiquetée. Responsabilité : frontend/AWS. Références : `frontend/config.js`, `frontend/api.js`, `frontend/render.js`, `frontend/graph.js`, `frontend/agent-api.js`, `agent/agent.py`, `lambdas/{submit,worker,status}/app.py`.

Le profil utilisateur, les portefeuilles fictifs et des écrans supplémentaires ne débloquent pas les trois lacunes centrales : poids datés, attribution et preuves.

### H2. Critères d’acceptation d’une investigation complète

- La sélection XIU expose sa date de composition, la période des prix, CAD/Brent USD, la version de calcul et la date de vérification.
- Le beta et son intervalle proviennent de la même version que les contributions ; la faiblesse statistique du signal net est expliquée.
- Chaque holding affiché est rattaché à une composition officielle datée ; les trous de couverture sont visibles.
- Chaque contribution indique sa méthode ; une approximation n’est pas présentée comme une attribution historique exacte.
- Chaque arête documentaire ouvre un passage réel et son document ; les relations non établies restent hypothétiques.
- Le compteur documentaire compte des documents identifiés ou annonce clairement qu’il compte des passages.
- Chat et interface utilisent des faits cohérents ; les citations du chat ne restent pas confondues avec la table de preuves de recherche.
- Le statut AWS est fondé sur des reçus de vérification, pas sur les noms de ressources ou les sorties anciennes d’un notebook.

### H3. Index des références de code utiles

| Sujet | Références exactes |
|---|---|
| Sources, snapshots, téléchargements | `ingest/fetch_to_s3.py`, `docs/data_contract.md` |
| Prix/FX et fréquence | `compute/stats.py::load_raw`, `build_weekly` |
| Régression, contrôles, OOS, multiplicité | `compute/stats.py::_fit_hac`, `regress_with_control`, `market_ticker_for`, `out_of_sample`, `bh_adjust`, `sensitivities` |
| Réseau macro et limites | `compute/stats.py::LINK_SPECS`, `CHAINS`, `links`, `chain_reconciliation`, `duration_check` |
| Portefeuilles / scénarios | `compute/stats.py::persona_holdings`, `portfolio_exposure`, `portfolio_beta`, `shock_impact_pct`, `scenarios`, `alternatives` |
| Résultats sauvegardés | `compute/run_stats.ipynb`, `frontend/preview-data.json` |
| Extraction / provenance | `compute/evidence.py::EVIDENCE_COLUMNS`, `extract_pages`, `validate_answer`, `write_evidence`, `run_part_b`, `check_outputs` |
| Absence de reçu d’extraction | `compute/run_evidence.ipynb` |
| Questions financières / SQL | `lambdas/tools/app.py` : `get_portfolio_exposure`, `get_asset_sensitivity`, `explain_channel`, `run_scenario`, `compare_alternative`, `get_validation` |
| Asynchrone | `lambdas/submit/app.py`, `lambdas/worker/app.py`, `lambdas/status/app.py` |
| Agent / KB / instructions | `agent/agent.py`, `prompts/agent_instructions.md`, `prompts/action_group_functions.md` |
| Configuration cloud | `.kiro/steering/project.md`, `iam/README.md`, `iam/*.json`, `docs/data_contract.md` |
| Recherche frontend | `frontend/api.js`, `frontend/config.js`, `frontend/app.js`, `frontend/render.js`, `frontend/graph.js` |
| Chat et données personnelles locales | `frontend/agent-api.js`, `frontend/agent-render.js`, `frontend/workspace-store.js`, `frontend/workspace.js` |
| Tests et évaluation non exécutés | `compute/test_stats.py`, `compute/test_evidence.py`, `agent/test_agent.py`, `lambdas/*/test_app.py`, `frontend/frontend.test.mjs`, `eval/questions.json` |

**Livrable de cet audit : ce fichier uniquement.** Les modifications frontend déjà présentes dans l’espace de travail ont été conservées. Aucun résultat live, document original ou fonctionnement AWS supplémentaire n’est attesté par ce rapport.
