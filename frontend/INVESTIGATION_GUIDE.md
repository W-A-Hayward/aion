# Guide de l’investigation RIPPLE AI

Le guide est accessible dans un volet dépliable près du chat, dans Workspace comme dans Research. Il explique pourquoi il faut rapprocher la composition d’un ETF, les mécanismes décrits par ses entreprises et les sensibilités statistiques. Les exemples producteur / banque / chemin de fer sont pédagogiques : ce ne sont pas des résultats sur l’investissement sélectionné. Le lecteur documentaire effectif est décrit dans `EVIDENCE_DESK.md`.

## Fichiers de cette extension

- `index.html` : phrase de mission, guide après le chat, chargement de ses deux ressources et libellé Beginner explicite. Les contrôles et identifiants existants restent utilisables.
- `investigation-guide.js` : contenu des trois questions, affichage progressif Beginner / Expert, synchronisation de la sélection, navigation clavier et liens vers l’estimation ou l’inspecteur existants. Les détails méthodologiques restent accessibles dans les deux modes.
- `investigation-guide.css` : mise en forme limitée au guide, trois colonnes sur grand écran et une colonne sur mobile.
- `investigation-guide.test.mjs` : mêmes informations dans les deux modes, échappement des libellés et séparation entre exemples et résultats.
- `INVESTIGATION_GUIDE.md` : cette note de fonctionnement et de validation.

## Données et limites

Aucun CSV, PDF ou catalogue de recherche n’est importé par le guide pédagogique. Le module séparé Evidence Desk lit désormais une copie locale assainie du résolveur cinq entreprises, sans modifier les fichiers de recherche. La provenance officielle CPKC reste en attente.

Les estimations, documents et relations affichés dans les panneaux existants dépendent toujours de leur source de données. Le guide explique qu’une absence à l’écran ne prouve pas une absence d’exposition. La connexion réelle au backend n’est pas activée par ce changement.

Validation initiale : 25 tests. La suite étendue et les contrôles Chrome du nouvel Evidence Desk sont documentés dans `EVIDENCE_DESK.md`. Aucun paquet ajouté. Un lecteur d’écran réel n’a pas été testé.
