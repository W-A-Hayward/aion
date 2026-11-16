# RIPPLE AI — interface locale, 15 novembre 2026

Le concept d’enquête financière et les composants existants sont conservés. La palette passe au blanc bleuté, bleu et turquoise. Le chat est le point d’entrée ; statistiques, preuves documentaires et catalogue ont des accès directs. Aucun changement de modèle financier, de données de recherche ou de configuration AWS dans cette intervention.

Révision éditoriale : titres plus petits et alignés à gauche, descriptions factuelles, suppression des slogans et des animations d’entrée de l’accueil. Les titres identifient directement les fonctions : « Oil exposure research », « XIU constituent evidence » et « Source library ». Cette révision concerne `index.html`, `chat.js`, `explorer.html`, `theme.css` et `ripple-light.css`.

## Parcours disponibles

- `index.html` : question XIU dès l’accueil, outils bêta/scénarios/extraits, historique et recherche de conversations, export Markdown, profil et portefeuille fictif conservés dans le navigateur. Aucun profil obligatoire. Mode local par défaut pour une nouvelle session ; une préférence de mode précédemment enregistrée reste respectée.
- `explorer.html?panel=statistics` : estimations, intervalles, scénarios et limites méthodologiques existants.
- `explorer.html?panel=evidence` : 35 passages pour cinq sociétés, avec poids datés et statuts existants. Une citation du chat ouvre son entreprise et son identifiant de passage exacts.
- `explorer.html?panel=sources` : les 52 entrées du registre, recherche dans les extractions et lecteurs de pages/tableaux. Les sources bloquées, incomplètes ou en quarantaine restent signalées.
- `explorer.html?panel=portfolio` : espace portefeuille, liste de suivi et recherches sauvegardées existants.
- `explorer.html?panel=overview` : visualisations et présentation générale conservées.

Beginner / Expert est accessible sur ordinateur et téléphone. Le menu de commandes permet de retrouver les outils et les documents. Les flèches du clavier changent les onglets des outils et le niveau d’explication ; Échap ferme les menus.

## Corrections fonctionnelles

1. Les cartes et raccourcis ouvrant un outil ne le referment plus par propagation du même clic.
2. Les animations des grands compteurs et des valeurs financières ont désormais des attributs distincts. Elles ne peuvent plus se remplacer mutuellement par `NaN`.
3. Les liens entre chat, entreprise, passage et page source conservent le contexte documentaire. Les boutons de navigation et le retour du navigateur changent le panneau visible.
4. Le profil est facultatif. « Reset local workspace » décrit la suppression locale réelle ; il ne prétend pas déconnecter un compte distant.
5. Les polices externes ont été retirées de l’accueil. L’application utilise les polices système et une marque SVG locale.

## Fichiers de cette intervention

| Fichier dans `frontend/` | Changement |
|---|---|
| `index.html` | Marque RIPPLE, navigation permanente, accès aux outils, accueil sans polices externes. |
| `chat.js` | Nouveau contenu d’accueil, ouverture des outils corrigée, profil facultatif, commandes de navigation, liens des citations, clavier et mode local initial. |
| `chat-answer.js` | Transporte l’identifiant du passage et le ticker original vers le lien documentaire ; calculs inchangés. |
| `chat-tools.js` | Nom RIPPLE AI dans l’export Markdown. |
| `chat-tools.test.mjs` | Vérifie le nom de produit dans cet export. |
| `ripple-light.css` — nouveau | Identité partagée, navigation, surfaces claires et adaptation mobile ; avertissements visibles dans une palette froide. |
| `ripple-mark.svg` — nouveau | Marque locale commune et favicon. |
| `explorer.html` | Navigation commune, liens retour au chat, chargement du thème et du routeur, compteurs de présentation isolés. |
| `explorer-navigation.js` — nouveau | Panneaux nommés dans l’URL, navigation et historique du navigateur, ouverture de la bibliothèque depuis une preuve. |
| `evidence-desk.js` | Sélection initiale du ticker et du passage fournis dans un lien, uniquement s’ils correspondent aux données existantes. |
| `theme.css` | Remplacement ciblé de la palette chaude par bleu/turquoise ; structure et composants existants conservés. |
| `fuel-card.js` | Accent turquoise du graphique de carburant. |
| `workspace-render.js` | Suppression de l’orange de la palette des allocations. |
| `workspace.js` | Titre de page RIPPLE AI. |
| `hero.js` | Animation limitée aux compteurs de présentation. |
| `app.js` | Animation financière limitée aux éléments portant une valeur numérique dédiée. |
| `evidence-browser-check.mjs` | Vérifications historiques dirigées vers `explorer.html`, désormais distinct du chat ; type MIME du SVG. |
| `design-browser-check.mjs` — nouveau | Parcours Chrome avec clics réels, clavier, navigation, portefeuille, liens exacts, vérification anti-NaN et affichage mobile. |
| `UI_REFINEMENT.md` — nouveau | Ce compte rendu. |

Les modifications présentes au début de cette intervention ont été conservées ; seules des modifications ciblées ont été appliquées. Les fichiers `config.js`, les jeux de données et les composants de progression existants n’ont pas été remplacés. Aucune modification hors `frontend/` pour cette refonte.

## Vérifications exécutées

- `node --test frontend/*.test.mjs` : **65 tests réussis**.
- `node frontend/design-browser-check.mjs` : **PASS**. Enquête XIU, quatre chocs autorisés, bêta et incertitude, extraits, lien vers le passage exact, validation d’un portefeuille incorrect puis sauvegarde correcte, persistance, commandes, historique, navigation directe et retour, mobile 390 px et clavier. Vérifie aussi que l’animation conserve les valeurs affichées du fichier local.
- `node frontend/evidence-browser-check.mjs` : **PASS**. Preuves, 52 sources, dates distinctes des compositions XIU, sources bloquées, recherche intégrale, données carburant/FX, quarantaine, erreurs de chargement et nouvelle tentative, absence de débordement mobile.
- Contrôles syntaxiques et `git diff --check` : réussis.
- Captures desktop et mobile examinées. Les tests navigateur bloquent les requêtes externes et n’ont détecté ni requête externe ni exception JavaScript.

## Aperçu et limites

Lancer depuis la racine si le serveur n’est pas déjà actif :

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory frontend
```

Ouvrir `http://127.0.0.1:8000/`. Les modules JavaScript et les fichiers JSON demandent un serveur HTTP local ; ne pas ouvrir le HTML par double-clic en `file://`.

Le chat local interprète les questions prises en charge à partir de données sauvegardées : il ne constitue pas un agent IA connecté. Les endpoints configurés restent disponibles dans le sélecteur, mais leur fonctionnement AWS n’a pas été vérifié ici. Aucun appel AWS, déploiement, installation, commit ou push.

Les données et leurs limites restent inchangées : une composition documentée n’est pas une attribution statistique du bêta ; une exposition opérationnelle ne donne pas la direction du rendement d’une action. Les 52 entrées du registre ne signifient pas 52 sources entièrement vérifiées et exploitables. Les données absentes ne sont pas complétées artificiellement.
