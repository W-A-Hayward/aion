# Evidence Desk — enquêter à partir des documents

La carte « Transmission paths » n’est plus affichée. L’expérience principale est désormais : **entreprise détenue → passage pertinent → document et vérifications**. Elle est accessible depuis Evidence dans la navigation et directement sous le chat. Le guide conceptuel reste dépliable, et les statistiques/scénarios restent dans Research.

## Données réellement affichées

Le fichier source est `research/evidence_v2/xiu_resolution_5_companies.json`, déjà existant : **35 passages, 5 documents, 5 constituants** de XIU au **12 novembre 2026**. ATD 5, CNR 7, RBC 7, CNQ 8, CPKC 8. Les deux autres séries de candidats RBC/CNQ/CPKC dans le dépôt ne sont pas fusionnées : aucun doublon n’est ajouté pour gonfler les comptes.

Les poids affichés 1,46 / 2,39 / 9,58 / 3,45 / 2,83 % représentent **19,71 % de composition** ; ce ne sont ni une couverture statistique, ni une fraction de beta expliquée. Le lecteur reste explicitement un dossier XIU, indépendant de la sélection du ticker et de la source API du panneau de marché. Aucun beta n’est joint à ces passages.

L’adaptateur conserve sans modification les passages, IDs, pages, poids, contextes de détention et vérifications. Pour les 23 passages RBC/CNQ/CPKC, il joint le contexte des fichiers `candidates_*_2025.verification.json` après concordance d’ID, sujet, page et citation. Les 12 passages ATD/CNR n’ont pas ce contexte complet : une mention visible demande de consulter les notes et tableaux originaux. Le candidat CNR constitué uniquement d’un titre de tableau n’est jamais sélectionné par défaut et porte un avertissement.

Les contrôles de citation « reported_verified » ne sont pas promus. Les contrôles PDF de recherche sont identifiés comme historiques. **CPKC reste `pending_issuer_to_cdn_link`**. Les dates de publication absentes restent absentes, même si l’exercice financier est connu. Les liens externes sont proposés avec page PDF, sans chargement automatique ni nouvelle validation réseau.

Les hashes, citations originales en français/anglais et les statuts suivent aussi l’action Copy citation. Les chemins personnels absolus sont retirés du fichier frontend. Les PDF eux-mêmes ne sont pas copiés ni embarqués.

## Fichiers

| Fichier | Fonction |
|---|---|
| `index.html` | Enquête à trois colonnes, point d’entrée Evidence, suppression du panneau graphique, guide dépliable et distinction des données backend. |
| `app.js` | Retrait du branchement et des événements du graphe ; statistiques, chat et workspace conservés. |
| `evidence-preview.json` | Copie locale portable des recherches, avec hash des artefacts sources ; aucune ressource AWS. |
| `build-evidence-preview.py` | Projection locale avec champs documentaires autorisés ; refuse d’écraser un snapshot existant. Aucun réseau. |
| `evidence-data.js` | Chargement local, contrôles d’identité/hash/contexte/poids, recherche par entreprise et texte de citation. |
| `evidence-render.js` | Liste d’entreprises et de passages, citations, vrais tableaux de contexte, statuts et liens échappés. |
| `evidence-desk.js` | Sélection, recherche, copie, modes, focus, chargement, erreur et reprise. |
| `evidence-desk.css` | En-tête marine, lecteur de document, adaptation mobile et navigation sans débordement. |
| `evidence-desk.test.mjs` | Sept tests de fidélité des données, refus des incohérences, recherche, contexte financier, provenance, liens dangereux et erreurs réseau simulées. |
| `evidence-browser-check.mjs` | Chrome installé, profil temporaire, serveur uniquement loopback ; demandes externes bloquées. Contrôle les interactions et enregistre trois captures temporaires. |
| `investigation-guide.js` | Liens pédagogiques dirigés vers le nouveau lecteur. |
| `README.md`, `INVESTIGATION_GUIDE.md`, `EVIDENCE_DESK.md` | Documentation actualisée de la séparation statistiques / recherche documentaire. |

Le module historique `graph.js` et ses tests restent conservés, mais l’application ne le charge plus. Aucun fichier de recherche, backend ou infrastructure n’est modifié par cette extension.

## Vérification locale

```sh
node --test frontend/frontend.test.mjs frontend/investigation-guide.test.mjs frontend/evidence-desk.test.mjs
node frontend/evidence-browser-check.mjs
```

32 tests unitaires passent. Le contrôle navigateur couvre : chargement réel des fichiers, cinq entreprises, 35 passages, sélection, recherche vide, contexte financier RBC, provenance CPKC, Beginner/Expert, mobile 390 px sans débordement, focus vers la citation, erreur de chargement et reprise. Aucune exception JavaScript ni demande externe dans la page. Le script ferme Chrome et son serveur et supprime son profil temporaire. Captures sur ordinateur/mobile inspectées visuellement. Aucun paquet installé ; lecteur d’écran réel non testé.

## Ce qui reste pour une intégration backend

Approuver un contrat documentaire qui conserve ces identités, contextes et statuts, puis fournir un endpoint versionné. Le fichier de recherche local ne doit pas être substitué silencieusement à une réponse backend en échec. Il reste à fournir des estimations de constituants comparables pour une attribution statistique, à compléter les contextes ATD/CNR et à établir le lien officiel CPKC. Le pipeline destructif de publication n’est pas appelé. Aucun téléchargement, AWS, déploiement, commit ou push.
