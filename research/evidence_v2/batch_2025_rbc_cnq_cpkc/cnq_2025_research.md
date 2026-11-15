# Canadian Natural Resources Limited — recherche documentaire 2025

Sept candidats relient références de prix, change, WCS, prix réalisés, redevances et netback. La sensibilité WTI publiée concerne flux/bénéfices, pas le beta Brent du titre.

Source : **Canadian Natural 2025 Annual Report**, exercice clos le 2025-12-31. Publication : non vérifiée.
[URL d'origine](https://www.cnrl.com/content/uploads/2026/04/CNQ_2025-Annual-Report.pdf) ; [URL finale](https://www.cnrl.com/content/uploads/2026/04/CNQ_2025-Annual-Report.pdf).
SHA-256 du PDF : `497adbc4c8be70021f2974cfec6876fe058f3ea2dc384196f3c424f450e7dfe8`.
Fichier local : `/Users/leahemidj/Documents/GitHub/cascade/research/source_documents/runs/20261115T131702Z_d4fbb4fa/CNQ_2025_EN_497adbc4c8be.pdf`.

Provenance : URL du domaine de l'émetteur conservée dans le reçu d'acquisition ; aucun contrôle réseau nouveau.

Les citations sont des sous-chaînes exactes du texte PDFKit des pages d'origine, avec sauts de ligne conservés. Les tableaux sélectionnés ont aussi été inspectés dans le rendu du PDF. Le contexte complet avant/après est conservé dans chaque ligne CSV ; il ne doit pas être confondu avec l'interprétation.

## Candidats

### CNQ-2025-01 — benchmark_pricing_and_fx

PDF **21**, page imprimée **20** — MD&A — Benchmark commodity prices

**Citation originale :**

> Substantially all of the Company's production is sold based on US dollar benchmark pricing, with crude oil marketed based on
> WTI and Brent indices, and natural gas marketed using a diversified mix of AECO- and NYMEX-based pricing. The Company's
> realized prices are directly impacted by fluctuations in foreign exchange rates resulting in product revenues being impacted by
> changes in Canadian dollar sales prices relative to the US dollar benchmark prices.

**Fait divulgué :** Tarification largement fondée sur références USD, dont WTI/Brent, avec effet du change sur prix réalisés CAD.

**Notre interprétation :** Séparer pétrole et USD/CAD dans l’étude statistique.

**Limites :** Le passage inclut aussi le gaz ; prix réalisé ≠ Brent ≠ rendement du titre.

### CNQ-2025-02 — wcs_wti_differential

PDF **21**, page imprimée **20** — MD&A — Benchmark commodity prices / WCS Heavy Differential

**Citation originale :**

> The WCS Heavy Differential averaged US$11.10 per bbl for 2025 compared with US$14.73 per bbl for 2024 (2023 –
> US$18.62 per bbl). The narrowing of the WCS Heavy Differential for 2025 from 2024 primarily reflected full year takeaway
> capacity on the TMX pipeline and strong US Gulf Coast heavy oil pricing.

**Fait divulgué :** Différentiel WCS-WTI : 11,10 USD/baril en 2025 contre 14,73 en 2024 ; CNQ cite TMX et les prix du brut lourd du Golfe.

**Notre interprétation :** Un différentiel régional peut influer sur les revenus indépendamment du niveau de Brent.

**Limites :** Explication attribuée à l’émetteur, pas identification économétrique causale.

**Contexte de tableau contrôlé :**

- title : BENCHMARK COMMODITY PRICES
- units : USD/baril pour WTI, Brent, différentiel WCS
- columns : Moyennes annuelles 2025, 2024, 2023
- scope : Références de marché, pas prix réalisés de toute la production
- footnote_review : Aucune note spécifique ; gaz et change ont d’autres unités.

### CNQ-2025-03 — realized_crude_pricing

PDF **26**, page imprimée **25** — MD&A — Realized product prices / North America

**Citation originale :**

> North America realized crude oil and NGLs prices decreased 7% to average $70.90 per bbl for 2025 from $76.37 per bbl for
> 2024 (2023 – $70.51 per bbl), primarily reflecting lower WTI benchmark pricing, partially offset by a narrowing of the WCS
> Heavy Differential.

**Fait divulgué :** Prix réalisé nord-américain pétrole/NGLs : 70,90 CAD/baril en 2025 contre 76,37 en 2024 ; WTI plus faible compensé en partie par WCS.

**Notre interprétation :** Niveau de référence et différentiel influent sur les prix de vente.

**Limites :** Ratio non-GAAP, périmètre E&P nord-américain incluant NGLs ; ne pas mélanger CAD et USD.

**Contexte de tableau contrôlé :**

- title : REALIZED PRODUCT PRICES – EXPLORATION AND PRODUCTION
- units : CAD/baril ; règle de devise page PDF 15
- columns : 2025, 2024, 2023
- scope : Crude oil and NGLs / North America
- footnote_review : Note 1 : volumes et rapprochements ; note 2 : Non-GAAP Ratio, applicable à North America ; note 3 : ventes/volumes.

### CNQ-2025-04 — international_brent_contract_timing

PDF **26**, page imprimée **25** — MD&A — Realized product prices / International

**Citation originale :**

> International realized crude oil and NGLs prices averaged $98.07 per bbl for 2025, a decrease of 10% from $108.80 per bbl for
> 2024 (2023 – $107.46 per bbl). Realized crude oil and NGLs prices per bbl in any particular year are dependent on the terms of
> the various sales contracts, the frequency and timing of liftings from each field, prevailing Brent benchmark prices and foreign
> exchange rates at the time of lifting.

**Fait divulgué :** Prix réalisé international dépendant des contrats, levées, Brent et change selon CNQ.

**Notre interprétation :** Exposition commerciale à Brent avec calendrier et termes contractuels.

**Limites :** Le mécanisme de revenu n’établit pas le signe ou la valeur du beta boursier.

### CNQ-2025-05 — royalties_and_production_economics

PDF **27**, page imprimée **26** — MD&A — Royalties / North America

**Citation originale :**

> Government royalties on a significant portion of North America crude oil and NGLs production fall under the oil sands royalty
> regime and are calculated on a project by project basis as a percentage of gross revenue less production, capital, and
> abandonment costs incurred.
> North America crude oil and NGLs and natural gas royalties for 2025 and the comparable periods reflected movements in
> benchmark commodity prices, fluctuations in the WCS Heavy Differential and the impact of sliding scale royalty rates.

**Fait divulgué :** Redevances dépendantes des revenus/coûts, références et barèmes ; taux pétrole/NGLs de 17 % en 2025 contre 20 % en 2024.

**Notre interprétation :** Les redevances modifient la transmission du prix de vente au résultat économique.

**Limites :** Taux non-GAAP et régimes par projet, pas élasticité universelle du profit.

**Contexte de tableau contrôlé :**

- title : ROYALTIES – EXPLORATION AND PRODUCTION
- units : CAD/baril pour montants unitaires ; % product sales pour taux
- columns : 2025, 2024, 2023
- scope : North America / crude oil and NGLs
- footnote_review : Note du taux (1) au pied : Non-GAAP Ratio ; note du tableau : royalties/sales volumes. Montant unitaire ≠ taux.

### CNQ-2025-06 — netback_production_economics

PDF **50**, page imprimée **49** — MD&A — Non-GAAP and Other Financial Measures / NETBACK

**Citation originale :**

> Netback is a non-GAAP ratio that represents net cash flows provided from core activities after the impact of all costs associated
> with bringing a product to market, on a per unit basis.

**Fait divulgué :** Netback défini comme ratio non-GAAP de flux nets après coûts d’acheminement au marché, par unité.

**Notre interprétation :** Compléter l’étude des prix par les coûts, redevances et transport.

**Limites :** Définition, pas sensibilité estimée. Présentation transport/blending modifiée en 2025 et comparatifs retraités, selon cette page.

### CNQ-2025-07 — issuer_cashflow_wti_sensitivity

PDF **54**, page imprimée **53** — MD&A — Other / Sensitivity analysis

**Citation originale :**

> The following table is indicative of the annualized sensitivities of cash flows from operating activities and net earnings due to
> changes in certain key variables. The analysis is based on business conditions and sales volumes during the fourth quarter of
> 2025, excluding mark-to-market gains (losses) on risk management activities and is not necessarily indicative of future results.
> Each separate line item in the sensitivity analysis shows the effect of a change in that variable only with all other variables being
> held constant.
> Cash flows
> from Operating
> Activities
> ($ millions)
> Cash flows
> from Operating
> Activities
> (per common
> share, basic)
> Net
> earnings
> ($ millions)
> Net
> earnings
> (per common
> share, basic)
> Price changes
> Crude oil – WTI US$1.00/bbl $ 409 $ 0.20 $ 409 $ 0.20

**Fait divulgué :** Variation WTI de 1 USD/baril : sensibilité annualisée affichée de 409 M CAD des flux opérationnels et 409 M CAD du résultat net.

**Notre interprétation :** Point d’appui documentaire sur flux/bénéfices, à distinguer d’une régression du titre.

**Limites :** Conditions et volumes T4 2025 ; autres variables constantes ; mark-to-market exclu ; pas nécessairement indicatif du futur ; aucun IC ni beta Brent.

**Contexte de tableau contrôlé :**

- title : SENSITIVITY ANALYSIS
- units : Choc : USD/baril ; impacts : millions CAD et CAD/action de base
- columns : Cash flows ($ millions), cash flows/share basic, net earnings ($ millions), net earnings/share basic
- scope : Sensibilités annualisées T4 2025 ; une variable à la fois
- footnote_review : Note 1 renvoie aux instruments pour gaz/change, pas à la ligne WTI. Préambule complet conservé dans l’extrait.

## Validation statistique encore nécessaire

Comparer séparément Brent, WTI, WCS-WTI et CAD/USD avec rendements CNQ et variables de production/coûts. Obtenir séries historiques, contrôles, fenêtres communes et incertitude ; la table d’émetteur ne remplace pas une régression.

Tous les passages restent `evidence_kind=operational` et `stock_return_direction=unknown`. Aucune contribution au beta de XIU, causalité boursière ou relation fournisseur-client nommée n'est créée. Aucun contexte XIU n'est ajouté à ce lot.

## Périmètre de vérification

Revue locale : 2026-11-15T14:39:22.205059+00:00. Citations et hash vérifiés ; interprétations non validées statistiquement. Les champs v2 sont exportés dans le catalogue de recherche associé. La lecture directe de ce CSV étendu par l'ancien importateur n'est pas autorisée : la projection explicite de `research_batch.py` conserve les champs additionnels dans le CSV.
