# Lot RBC / CNQ / CPKC — rapports annuels 2025

Vingt candidats de recherche : **RBC 6, CNQ 7, CPKC 7**. Les trois PDF existaient déjà localement. Aucun téléchargement, accès AWS, pipeline de publication ou modification du résolveur XIU précédent.

| Société | Directement documenté | Hypothèses à tester | Validation statistique manquante |
|---|---|---|---|
| RBC / RY.TO | EAD et prêts oil and gas ; prêts dépréciés ; PCL ; allocation Canada ; remplacement du scénario énergie au T2 2025 | Choc pétrole → qualité de crédit du secteur → résultats de la banque | Séries de crédit et rendements, Brent/marché/taux/FX ; identification et incertitude ; aucun signe boursier conclu |
| CNQ.TO | WTI/Brent et FX dans les prix de vente ; WCS-WTI ; prix réalisés ; redevances ; netback ; sensibilité WTI des flux/bénéfices | Ampleur et stabilité de la transmission de ces mécanismes au rendement du titre | Comparaison Brent/WTI/WCS et CAD, contrôles et fenêtres communes ; sensibilité d’émetteur ≠ beta boursier |
| CPKC / CP.TO | Charges diesel, programme de surcharges, calendrier des recouvrements, fret énergétique et risques d’approvisionnement | Compensation nette des coûts par surcharges ; sensibilité au prix après mix/volumes/FX | Historique CP comparable, références diesel, surcharges et volumes ; aucun délai CNR transféré à CPKC |

## Fichiers et schéma

Chaque société a un `*_research.md`, un `*_candidates.csv` et un `*_catalog.json`. Le rapport distingue citation, fait divulgué, interprétation et limite. Le CSV contient tous les champs de l’importateur v2 initial **plus** contexte intégral avant/après, offsets, hash du texte de page, contexte de tableau, statut de provenance, fait et limites. Une projection explicite dans `../research_batch.py` produit les structures `Document` et `EvidencePassage` existantes sans modifier ce schéma. Les champs additionnels restent dans le CSV ; aucun contexte de détention XIU n’est inventé.

`selection.json` conserve les bornes de sélection et les annotations de recherche. `validation_receipt.json` conserve hashes, pages, nombre de candidats et pages inspectées visuellement. Les noms de fichiers ne sont pas des preuves d’identité : les hashes des PDF ont été recalculés avant extraction.

## Ce qui a été vérifié

- Les 20 citations sont des sous-chaînes **exactes**, avec sauts de ligne, du texte extrait des pages PDF originales ; aucune paraphrase n’est stockée dans `excerpt`.
- Le contexte intégral de chaque page est reconstituable par `source_context_before + excerpt + source_context_after` ; aucune ligne financière ne doit être utilisée sans son contexte de tableau.
- Les tableaux sélectionnés ont été contrôlés dans le rendu : RBC PDF 79/130/131/132/133, CNQ 21/26/27/54 et CPKC 53/54 ; les notes et conventions de devise ont été lues. La convention CAD de CNQ est PDF 15 ; celle de CPKC PDF 17. Les pages de texte restantes ont été vérifiées par extraction de l’original, avec leurs étiquettes imprimées.
- `quote_verification=verified` porte sur la transcription et sa localisation ; ni la vérité économique indépendante des comptes, ni l’interprétation causale, ni la réaction boursière ne sont certifiées.
- **CPKC : provenance officielle `unverified`, état `pending_issuer_to_cdn`, `url_verified=False`**, même si les citations et le hash sont contrôlés. Aucune recherche réseau pour lever ce point.
- RBC/CNQ : provenance `reported_verified` fondée sur le reçu historique de l’URL émetteur. Disponibilité actuelle des liens et date de publication non vérifiées.

Les tableaux RBC ont des périmètres différents : 18 880 M CAD d’EAD ne sont pas 18 880 M CAD de prêts ; l’allocation de 7 M CAD concerne les prêts dépréciés au Canada ; la PCL 6/(51) est un flux, pas cette allocation. CNQ publie 409 M CAD de sensibilité annualisée à une variation WTI de 1 USD/baril sous conditions T4 2025, pas une prévision ni un beta Brent. CPKC publie une baisse de charge carburant de 71 M CAD et une composante prix/taxes de 159 M CAD : ces deux nombres ne sont pas interchangeables.

## Tests locaux

```sh
python3 -B -m unittest discover -s research/evidence_v2 -p 'test_*.py' -v
```

Les tests relisent les PDF locaux avec PDFKit, contrôlent citations, contexte, hashes, schéma v2, périmètres et refus de promotion CPKC. Ils n’utilisent ni AWS ni réseau. La commande de construction `research_batch.py --build` a déjà été exécutée ; elle refuse de remplacer les artefacts existants. Les catalogues restent de recherche, sans publication ni fusion avec les catalogues précédents.
