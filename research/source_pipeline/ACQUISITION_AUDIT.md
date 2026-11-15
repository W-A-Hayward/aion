# Audit final — acquisition RIPPLE des 52 sources

Date : 15 novembre 2026. Aucun accès AWS, aucune intégration de production. Les 52 lignes du registre ont une entrée dans cet inventaire.

## Résultat exact

| Classe | Nombre d’entrées | Signification |
|---|---:|---|
| Exploitables pour la recherche locale | 24 | Au moins un rapport, dataset parsé ou article pertinent non en quarantaine. |
| Contexte ou mapping incomplet | 10 | Page accessible, portail, export vide ou données demandant une adaptation. |
| Intervention requise | 18 | Collecte arrêtée selon la politique d’accès, ou uniquement un document en quarantaine. |
| Total | 52 | Le doublon SRC-052/SRC-005 reste une ligne distincte du registre. |

**28 entrées demandent donc encore une intervention ou un complément.** Même les 24 exploitables ne sont pas toutes entièrement couvertes : certaines entrées demandent simultanément un rapport annuel, un AIF et un trimestre. Aucune citation financière nouvelle n’est approuvée automatiquement.

35 entrées disposent d’au moins une extraction, y compris des documents en quarantaine. Les 64 objets distincts comprennent 26 PDF (7 déjà présents + 19 nouveaux), 29 pages HTML, 3 CSV de holdings parsés, 1 classeur XLSX, 1 réponse JSON de métadonnées StatCan, 1 ZIP de données StatCan, 1 réponse JSON Valet et 2 objets dont l’extraction reste incomplète. **56 objets ont été téléchargés dans ce travail et 8 réutilisés** (7 PDF + le CSV XIU fourni). Les objets identiques partagent leur stockage par hash.

Le dernier passage était entièrement hors ligne : `2026-11-15T153200689426+0000_2b6a5b`. Il réutilise les reçus des passages réseau et ne télécharge rien de nouveau. Les compteurs par lancement ne doivent pas être confondus avec les totaux cumulés ci-dessus.

## Livrables et contrôles

- [Inventaire complet JSON](artifacts/runs/2026-11-15T153200689426+0000_2b6a5b/inventory.json) : entrées originales, provenance, URL, hashes, versions, dates et statuts.
- [Inventaire détaillé des fichiers CSV](artifacts/runs/2026-11-15T153200689426+0000_2b6a5b/artifact_inventory.csv) : un enregistrement par association source/artefact.
- [Inventaire des 52 sources CSV](artifacts/runs/2026-11-15T153200689426+0000_2b6a5b/inventory.csv).
- [Audit hors ligne](artifacts/runs/2026-11-15T153200689426+0000_2b6a5b/offline_audit.json) : 64 hashes recalculés et 3 665 segments comparés exactement aux pages/offsets extraits.
- [Manifeste de préparation](artifacts/runs/2026-11-15T153200689426+0000_2b6a5b/ingestion_preparation.json) : 3 184 segments à revoir, 481 en quarantaine, 7 préparations structurées et 5 mappings de fichiers compatibles/proposés.
- 17 tests locaux passent : refus de remplacement, reprise après interruption, absence de réseau en mode hors ligne, arrêt sur refus/redirect non HTTPS, dates/unités, valeurs manquantes, reconnaissance des années espacées et quarantaine.

Les fichiers téléchargés et préparés sont ignorés par Git. Les anciens fichiers de recherche et les sources de production ne sont pas modifiés. Les tableaux PDF ne sont pas transformés automatiquement en chiffres financiers validés : leur texte et leurs pages sont conservés pour revue.

## Constats prioritaires

- **XIU / SRC-001** : snapshot fourni au 12 novembre conservé (65 positions, total affiché 100,02 %). Nouveau fichier au 13 novembre (65 positions, 100,04 %). Le second est plus récent pour une vue courante, mais ne remplace pas le premier dans une enquête datée du 12 novembre.
- **XESG / SRC-002** : deux URL retournent les mêmes octets, date « - » et aucune position. Téléchargement réussi ne signifie pas composition disponible. Aucune vérification S3 dans ce travail.
- **SPY / SRC-003** : XLSX officiel acquis, cellules conservées, libellé « As of 12-Nov-2026 ». Mapping de la colonne Weight et de son unité non approuvé ; secteurs publiés comme « - » dans les lignes inspectées. Pas de secteurs inventés.
- **IVV / SRC-004** : 509 positions au 12 novembre ; quatre poids manquants restent nulls et les lignes restent présentes. Somme des poids connus 100,10 %, total complet inconnu. Ne pas substituer IVV à SPY.
- **StatCan / SRC-037** : 46 262 lignes de janvier 1979 à septembre 2026, cents par litre, dimensions et statuts conservés. La fréquence mensuelle n’est pas artificiellement convertie en données hebdomadaires.
- **BoC / SRC-040** : 3 736 observations de séries FXUSDCAD et rendements canadiens 2/10 ans, du 12 novembre 2021 au 13 novembre 2026 ; unités CAD par USD et pourcent. Les CSV préparés restent locaux. Le panel des taux est partiel et ne doit pas écraser le panel américain/canadien existant.
- **Enbridge / SRC-011** : PDF ancien conservé mais isolé ; couverture 2024 « management circular », formulaire intérieur FY2025. Identité incohérente non résolue.
- **CPKC / SRC-026** : PDF connu réutilisé mais provenance issuer→CDN toujours en attente. L’accès automatisé à la source SEC du registre n’a pas été poursuivi quand la politique robots n’a pas pu être vérifiée.
- **BNS** : rapport annuel 2025 reconnu même avec une année imprimée « 2 0 2 5 ». La circulaire de gouvernance supplémentaire est isolée car ce n’est pas le rapport financier demandé.
- **Brent/WTI et séries FRED / SRC-030, 031, 043–045** : politique robots non vérifiable dans cette session ; aucune nouvelle série acquise. Cela ne prouve pas que les liens sont morts. Recourir à un téléchargement autorisé ou à un point public documenté dont l’accès est permis.
- **SRC-047** : redirection vers HTTP arrêtée, sans assouplissement TLS. **SRC-052** est le même lien que SRC-005.

## Suivi des 52 entrées

« Accessible » décrit une observation de cette session. Un statut de blocage robots signifie parfois que robots.txt lui-même était inaccessible ; le document cible n’a alors pas été testé. Les dates de publication absentes restent UNVERIFIED.

| ID | Éditeur et source demandée | Résultat | Formats extraits | À traiter |
|---|---|---|---|---|
| SRC-001 | BlackRock/iShares — XIU - holdings, downloadable CSV and fund facts | Exploitable localement | holdings, html | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-002 | BlackRock/iShares — XESG - holdings, downloadable CSV | Contexte / incomplet | html | Invalid isoformat string: '-' ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-003 | State Street — SPY - downloadable daily ETF holdings | Contexte / incomplet | html, xlsx_cells | No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-004 | BlackRock/iShares — IVV - S&P 500 ETF holdings and snapshots | Exploitable localement | holdings, html | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-005 | S&P Dow Jones Indices — S&P/TSX 60 index facts and GICS sector breakdown | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-006 | S&P Dow Jones Indices — S&P/TSX Canadian Indices Methodology | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-007 | Alimentation Couche-Tard — 2026 Annual Report (FR), AIF and MD&A | Exploitable localement | pdf | robots_unavailable_manual_review |
| SRC-008 | Alimentation Couche-Tard — Q1 Fiscal 2027 release (Sep 2026) | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-009 | Canadian National Railway — 2025 Annual Report - full PDF | Exploitable localement | pdf | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-010 | Canadian National Railway — 2026 Investor Fact Book and other reports | Exploitable localement | html, pdf | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-011 | Enbridge — 2025 Form 10-K | Contexte / incomplet | html, pdf | Cover says 2024 management circular; inner filing says FY2025. Mixed identity unresolved. ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-012 | Canadian Natural Resources — 2025 Annual Report and AIF | Exploitable localement | html, pdf | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-013 | Canadian Natural Resources — 2025 Annual Information Form | Exploitable localement | pdf | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-014 | Suncor — 2025 Annual Report and Q3 2026 results | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-015 | TC Energy — 2025 Annual Report | Exploitable localement | html, pdf | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-016 | TC Energy — Q3 2026 results | Exploitable localement | html, pdf | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-017 | Cenovus Energy — 2025 Annual Report / AIF / MD&A | Contexte / incomplet | html | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-018 | Royal Bank of Canada — 2025 Annual Report and 2026 quarterly results | Exploitable localement | html, pdf | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-019 | Royal Bank of Canada — Energy supply lending ratios (2024-2025) | Exploitable localement | pdf | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-020 | TD Bank — 2025 Annual Report & MD&A | Exploitable localement | html, pdf | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-021 | Bank of Montreal — 2025 annual disclosures & 2026 Q3 | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-022 | Bank of Nova Scotia — 2025 Annual Report | Exploitable localement | html, pdf | Proxy/governance document, not the requested financial report. ; Source provenance pending; excluded from ready staging. |
| SRC-023 | CIBC — 2025 Annual Report/MD&A | Exploitable localement | html, pdf | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-024 | National Bank of Canada — 2025 Annual Report and AIF | Exploitable localement | html, pdf | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-025 | Manulife Financial — Annual, Q3 2026 reports and investment fact sheet | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-026 | Canadian Pacific Kansas City — 2025 Form 10-K | Intervention | pdf | Provenance en attente ; robots_unavailable_manual_review ; Source provenance pending; excluded from ready staging. ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-027 | Fortis — 2025 annual and quarterly reports | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-028 | Brookfield Corporation — 2025 Annual Report | Exploitable localement | html, pdf | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-029 | Shopify — 2025 Annual Report | Contexte / incomplet | html | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-030 | FRED/EIA — Brent crude oil spot - DCOILBRENTEU | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-031 | FRED/EIA — WTI spot - DCOILWTICO | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-032 | EIA — Open Data API v2 - spot oil and petroleum products | Contexte / incomplet | html | Portal/documentation captured if accessible; actual filing/dataset selection still required. ; EIA API key and precise route/series selection required. No key requested or used. ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-033 | EIA — Petroleum and other liquids data | Contexte / incomplet | html | Portal/documentation captured if accessible; actual filing/dataset selection still required. ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-034 | EIA — Short-Term Energy Outlook - 2026-11 | Exploitable localement | html | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-035 | Canada Energy Regulator — Canadian pipeline system 2026 - crude oil | Exploitable localement | html | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-036 | Canada Energy Regulator — Trans Mountain expansion and WCS differential analysis | Exploitable localement | html | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-037 | Statistics Canada — Monthly average retail gasoline and fuel-oil prices (18-10-0001-01) | Exploitable localement | html, json_metadata, zip_csv | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-038 | Statistics Canada — Annual manufacturing energy consumption 2025 | Exploitable localement | html | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-039 | Statistics Canada — Input-output / supply-use datasets, table list | Contexte / incomplet | html | Portal/documentation captured if accessible; actual filing/dataset selection still required. ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-040 | Bank of Canada — Valet API (FXUSDCAD and rates) | Exploitable localement | time_series | HTML contains no substantive text; script-only/manual review |
| SRC-041 | Bank of Canada — Financial Stability Report 2026 - Oil shock and market correction | Exploitable localement | html | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-042 | Bank of Canada — Financial Stability Report 2026 - Banks | Exploitable localement | html | Dates de publication/citations et couverture intégrale de la demande à revoir. |
| SRC-043 | FRED — 10-year US breakeven inflation expectations T10YIE | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-044 | FRED — US 10-year constant maturity Treasury DGS10 | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-045 | FRED — US 2-year constant maturity Treasury DGS2 | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-046 | SEDAR+ / CSA — Public search for issuer filings | Contexte / incomplet | html | Portal/documentation captured if accessible; actual filing/dataset selection still required. ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-047 | SEDAR+ / CSA — How to search and download regulatory filings | Intervention | — | Redirect leaves permitted HTTPS policy; not followed ; Portal/documentation captured if accessible; actual filing/dataset selection still required. ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-048 | US SEC — EDGAR company filings search | Intervention | — | robots_unavailable_manual_review ; Portal/documentation captured if accessible; actual filing/dataset selection still required. ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-049 | US SEC — SEC EDGAR APIs & XBRL companyfacts | Intervention | — | robots_unavailable_manual_review ; Portal/documentation captured if accessible; actual filing/dataset selection still required. ; SEC companyfacts requires reviewed CIKs and compliant requester identity; no bulk issuer facts requested. ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-050 | EIA — Daily market prices including diesel gasoline crude and crack spread | Contexte / incomplet | html | Portal/documentation captured if accessible; actual filing/dataset selection still required. ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-051 | Couche-Tard — FY2026 results release with fuel margin explanation | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. |
| SRC-052 | S&P Dow Jones Indices — Source explanation of GICS class and sector weights | Intervention | — | robots_unavailable_manual_review ; No qualified report/dated dataset for intended use; a landing page is not a substitute. ; Doublon SRC-005 |

## Ce qui reste avant AWS

1. Revoir les droits d’usage, identité/titre/période et citations ; compléter les pages imprimées et les contextes de tableaux. Aucun statut `verified` financier ne doit être déduit du seul hash.
2. Résoudre les 28 sources incomplètes/en attente : accès autorisé, exports XESG/SPY, choix de datasets EIA et SEC (clé/CIK/identité de requérant selon le service). Les portails ne sont pas des séries de prix ni des filings.
3. Faire approuver les mappings de dates, unités et séries par le responsable compute. Conserver la vintage de chaque dataset, ne pas incorporer des holdings 2026 dans une attribution historique 2022. Les 52 entrées ne fournissent pas à elles seules tous les prix ajustés de constituants nécessaires aux betas.
4. Faire approuver un contrat documentaire versionné, les préfixes S3 séparés et les filtres KB. Importer les versions sans utiliser le publisher destructif `compute/evidence.py`. Préserver Document/Passage/Context, sujet entreprise et `stock_return_direction=unknown`.
5. Après autorisation distincte seulement : upload, Glue/Athena, ingestion KB, tests de restitution et de citations, puis raccordement à l’API. Aucun de ces appels n’a été effectué.

La préparation KB est un format local à examiner, pas une autorisation de publication. Les pages de navigation et la documentation API sont identifiées séparément et devraient être exclues de la recherche de mécanismes financiers lors du raccordement.

Voir [README.md](README.md) pour les commandes, limites réseau, structure de stockage, reprise et responsabilités des fichiers.
