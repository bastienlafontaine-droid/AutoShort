# AutoShort Local — Windows / RTX 5080 16 Go

Une thématique → recherche de sujets → vérification documentaire → script révisé → voix française → illustrations SDXL contrôlées → montage vertical → rapport qualité.

**La publication reste manuelle.** Aucun compte TikTok ou YouTube n'est requis.
Cette version est un projet exécutable, pas une garantie de production sans défaut :
les services IA réels et le GPU doivent être validés sur votre PC.

## Démarrage : trois actions

1. Extraire **tout** le ZIP dans un dossier, par exemple `C:\AutoShort`.
   Éviter OneDrive et les chemins très longs. Ne pas exécuter depuis l'archive.
2. Double-cliquer **INSTALLER.cmd**. Accepter si nécessaire les fenêtres Windows
   des installateurs officiels. L'installation réutilise Ollama s'il est déjà présent.
3. Dans l'interface qui s'ouvre, saisir une clé [Brave Search API](https://brave.com/search/api/),
   puis cliquer **Créer une vidéo**. La thématique est préremplie.

Pour les démarrages suivants : **LANCER.cmd**.
L'interface est disponible à http://127.0.0.1:8765 . Si le navigateur s'ouvre avant
le démarrage du serveur, actualiser la page quelques secondes plus tard.
Garder la fenêtre ouverte pendant les productions. Désactiver temporairement
la mise en veille Windows pendant une longue production.

### Ce qui reste nécessaire

- Windows 11 x64, accès Internet et pilote NVIDIA récent compatible CUDA 12.8.
- `winget` (App Installer Microsoft Store), généralement déjà installé.
- Environ **35 à 50 Go libres**, ordre de grandeur incluant environnement, modèles
  et premiers médias. L'installation ne télécharge pas tous les fichiers SDXL.
- Une clé Brave Search : cette API peut être payante selon votre offre.
  Aucun abonnement IA générative cloud n'est nécessaire.
- Fermer les autres applications qui utilisent fortement le GPU (ComfyUI,
  jeux, sessions Ollama/Open WebUI). Le verrou AutoShort ne peut pas réserver
  physiquement le GPU face aux autres applications.
- Écouter et visionner les premiers résultats avant publication pour calibrer
  les juges. La qualité factuelle et le naturel de la voix ne sont pas certifiés.

La clé Brave est conservée en clair dans `.env`, uniquement sur votre PC. Ne
partagez ni ce fichier, ni `data/` sans en examiner le contenu. L'archive fournie
ne contient aucune clé. Les recherches sortent sur Internet ; les scripts,
voix et images ne sont pas envoyés à un fournisseur de génération cloud.
Les téléchargements initiaux des modèles nécessitent également Internet.

## Ce qui est installé automatiquement

| Composant | Installation |
|---|---|
| uv et Python 3.11 isolé | winget + uv |
| Ollama | installation uniquement si absent |
| FFmpeg et ffprobe | paquet Gyan.FFmpeg si absents |
| PyTorch pour Blackwell | 2.7.1, CUDA 12.8, build officiel |
| Modules du projet | environnement `.venv` séparé |
| Qwen3 8B et Qwen3-VL 8B | `ollama pull` |
| SDXL base | téléchargement Hugging Face FP16 |
| Kokoro + voix française | téléchargement automatique, test vocal |
| Whisper small | téléchargement et retranscription du test vocal |

Le script ne met pas à jour vos pilotes et ne change pas la politique PowerShell
persistante. `ExecutionPolicy Bypass` s'applique uniquement au processus de lancement.
Il ne désinstalle pas vos modèles existants et ne modifie pas Open WebUI.
Les paquets système déjà présents sont conservés. Si Ollama est trop ancien pour
Qwen3-VL, mettre à jour Ollama puis relancer l'installation.

Les dépendances Windows/Python 3.11 sont figées dans `requirements-windows.lock`,
résolu lors de la préparation. Les versions réellement installées sont aussi
enregistrées dans `installation-lock.txt`.
Les digests des modèles Ollama sont enregistrés par le diagnostic. Les tags Ollama
et les branches Hugging Face peuvent évoluer : figer ces digests/revisions après
votre premier benchmark validé. Les versions de code de ce paquet sont `0.1.0`.

## Utilisation quotidienne

1. Lancer `LANCER.cmd`.
2. Vérifier le diagnostic, puis saisir une thématique précise.
3. Lancer une ou plusieurs productions ; la file traite **une vidéo à la fois**.
4. Attendre le statut « Prête à visionner ».
5. Visionner, écouter, consulter les sources puis télécharger `video.mp4`.

Exemples d'entrées :
- Histoires vraies insolites, inventions et erreurs historiques.
- Histoires vraies insolites de transports au XIXe siècle.
- Histoires étonnantes et documentées de découvertes scientifiques.

Le moteur peut refuser tous les candidats. Cela signifie qu'il n'a pas trouvé
assez de preuves ou un angle suffisamment clair dans son budget de recherche.
Modifier la thématique ou lancer une nouvelle production permet une nouvelle recherche.
Il ne remplace jamais des preuves absentes par une anecdote inventée.

## Livrables

Dans `data/runs/<identifiant>/export/` :

- `video.mp4` : 1080 × 1920, 25 images/seconde, H.264/AAC ; cible 60–95 secondes.
- `cover.jpg` : capture de couverture, pas une miniature conçue séparément.
- `subtitles.srt` et `subtitles.ass`.
- `script.md`, `description.txt`.
- `sources.json` : textes sources et dossier de faits.
- `quality_report.html`, `technical_report.json`, `final_visual_review.json`.
- `manifest.json` : configuration, médias, seeds, évaluations et compteurs.
- `contact_sheet.jpg`, `timeline.json`.

Une vidéo peut exister en brouillon avant d'être acceptée. Le statut `READY`
indique que tous les contrôles implémentés ont accepté le résultat, **pas**
une certification historique ni une promesse de monétisation.

## Architecture livrée

- Orchestration **LangGraph** avec rôles spécialisés et boucles bornées dans les étapes.
- Checkpoints applicatifs atomiques JSON après chaque étape validée ; file et états
  en **SQLite WAL**. Pas de serveur PostgreSQL à gérer.
- Backend **FastAPI**, interface HTML/JavaScript locale sans compilation Node.
- Images **Diffusers / SDXL** dans un sous-processus qui libère le GPU à sa sortie.
  Pas de dépendance ComfyUI à configurer.
- Texte et inspection visuelle via **Ollama**, chargés successivement.
- Voix Kokoro et ASR Whisper en **CPU** pour simplifier la compatibilité Windows
  et préserver la VRAM. Plus lents qu'un traitement GPU, mais isolés du générateur d'images.
- Montage FFmpeg en **CPU libx264** pour une disponibilité reproductible. NVENC
  n'est pas activé ni requis dans cette version.

Ces adaptations réduisent l'installation tout en conservant la chaîne de production.
Les poids ne sont pas intégrés au ZIP, seulement téléchargés depuis leurs dépôts.

## Vérifications effectivement implémentées

| Étape | Contrôle | Échec |
|---|---|---|
| Découverte | Historique des titres, filtre de similarité | Nouveau candidat |
| Recherche | Pages lisibles, citations présentes, ≥2 domaines et juge d'indépendance | Candidat suivant |
| Faits | Juge sur chaque fait et les textes sources | Candidat suivant |
| Script | Références aux faits, longueur, juge factuel/éditorial | Jusqu'à 3 versions |
| Audio | Retranscription indépendante, écart de mots, amplitude, silences, durée | Jusqu'à 2 productions par segment |
| Images | Vrai fichier inspecté par Qwen3-VL | Jusqu'à 3 images par scène |
| Montage | Décodage, dimensions, pistes, durée, noir et silence | À revoir |
| Vidéo finale | Planche de captures contrôlée par VLM | À revoir |

Les corrections d'images sont intégrées en tête de prompt. Le style passe aussi
par le second encodeur SDXL. Les prompts réellement tronqués à la limite des
encodeurs CLIP sont enregistrés dans les métadonnées de génération.

Les sous-titres reprennent le **texte original**, avec correspondance aux mots
reconnus et interpolation locale en cas de non-correspondance. Ce n'est pas un
alignement forcé WhisperX complet : l'installer séparément augmenterait la fragilité
Windows. Le taux de correspondance est visible dans `timeline.json`.

## Limites explicites de cette version

- Le même modèle texte joue plusieurs rôles : ses erreurs peuvent être corrélées.
- Deux domaines et un juge ne prouvent pas l'indépendance historique des sources.
  Les citations sont vérifiées mécaniquement, leur implication est évaluée par IA.
- La qualité esthétique, la prosodie et les anachronismes ne sont pas parfaitement détectés.
- Les images d'un même personnage ne garantissent pas la continuité d'identité.
  Les prompts privilégient donc objets, lieux et compositions simples.
- Pas de génération vidéo Wan, de lip-sync ni de transitions 3D. Vidéo = illustrations
  originales avec mouvements légers, narration, sous-titres et barre progressive optionnelle.
- Pas de musique incluse. Ajouter votre fichier autorisé via `production.music`.
- Pas de modification autonome du code ou des prompts système. Les corrections portent
  sur le contenu du run, pas sur les règles de validation.
- Pas de mesure automatique des vues et pas de publication.
- L'application est locale, mono-utilisateur. Ne pas l'exposer sur Internet ou le LAN.

## Reprise et budgets

« Reprendre » conserve les étapes valides et les budgets de la production. Les modèles
ne repassent pas sur un dossier documentaire déjà accepté. Si un média est absent ou
modifié, son étape et les suivantes sont invalidées.

Limites initiales : 14 recherches API, 75 appels LLM, 180 minutes actives par production.
Un appel réseau ou une inférence en cours peut finir avant l'annulation ; les
sous-processus média sont arrêtés rapidement. Un run peut rester en reprise partielle
après arrêt de l'application. Le temps total est sauvegardé aux sorties normales ;
un arrêt brutal peut perdre le compteur de temps du segment interrompu, mais pas les
compteurs d'appels déjà persistés.

Les tentatives d'un lot média non validé sont rejouées lors d'une reprise d'étape.
Pour refaire volontairement une étape et ses descendants :

```powershell
.\.venv\Scripts\python.exe -m autoshort.cli retry IDENTIFIANT --from-stage images
```

Le run ne doit pas être actif. Les budgets restent inchangés. Si le budget est épuisé,
créer une nouvelle production. `config.toml` s'applique aux nouveaux runs uniquement.

## Commandes utiles

```powershell
# Installation (alternative au double-clic)
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1

# Installer sans télécharger les modèles immédiatement
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -SkipModels

# Démarrer
.\LANCER.cmd

# Diagnostic complet (inclut un calcul CUDA réel)
.\.venv\Scripts\python.exe -m autoshort.cli doctor

# Précharger SDXL, voix et reconnaissance vocale
.\.venv\Scripts\python.exe -m autoshort.cli prefetch

# Tester le code et FFmpeg, sans génération IA ni recherche payante
.\.venv\Scripts\python.exe -m pytest -q

# Production sans interface (ne pas la lancer en parallèle de l'interface)
.\.venv\Scripts\python.exe -m autoshort.cli run --theme "Histoires vraies insolites"
```

Consulter `docs/DEPANNAGE.md`, `docs/ARCHITECTURE.md`, `docs/VALIDATION.md` et
`LICENSES.md` avant de modifier les composants.


## Sélection des images après les essais

Chaque image reçoit deux notes distinctes sur 100 : qualité visuelle et pertinence
par rapport à la narration. La note finale est leur moyenne (une décimale).
Le seuil `min_visual_score` conserve la compatibilité avec la configuration sur 10
(ex. 8 = 80/100). Les notes des juges sont toujours sur 100 : 5 reste 5/100.

Une scène qui atteint le seuil ne consomme plus de nouvelles générations. Après
`image_attempts`, la meilleure image disponible de chaque scène est retenue même
sous le seuil ; une égalité conserve le premier essai. Le montage continue avec
les réserves, sans modifier les verdicts originaux des juges.

Le juge visuel final reste consultatif pour ce mode : son refus est conservé au
rapport sans empêcher la livraison. Les vérifications techniques du montage restent actives.

Les notes, motifs et essais retenus figurent dans `images/selection.json` et dans
le rapport HTML final. Les évaluations sont réutilisées seulement pour une image,
une scène, un style et un modèle de vision identiques. Les anciennes évaluations
sans cette identité sont recalculées. Les erreurs techniques et l'absence d'image
exploitable restent des erreurs, pas des notes de qualité.

Après mise à jour du code : relancer AutoShort puis cliquer **Reprendre** sur une
production arrêtée à l'étape images. Les étapes déjà validées sont conservées.


## Mode guidé progressif

La case **Auto**, à côté de **Créer une vidéo**, est décochée par défaut.
Auto coché conserve l'enchaînement automatique, sans validation ni bouton +.
La publication reste manuelle ; la CLI et les anciennes productions automatiques
conservent leur fonctionnement.

Le parcours guidé comporte cinq étapes :

1. **Idées** : chaque sujet s'affiche dès qu'il est prêt, avec titre, angle et note
   indicative sur 100. Trois propositions sont préparées. Choisir une idée lance
   sa recherche approfondie. Si ses preuves ne tiennent pas, les autres restent
   disponibles et les alternatives en attente reprennent.
2. **Script** : la première narration complète s'affiche pendant la préparation
   d'une deuxième version. Choisir, modifier ou utiliser **+**.
3. **Découpage** : même fonctionnement, avec le texte dit, la description et le
   prompt de chaque plan. **+ Ce plan** régénère uniquement ce plan dans une
   nouvelle version du découpage, en conservant les autres plans et la narration.
4. **Images** : les plans se remplissent un par un. Chaque plan propose **Retenir**,
   **Modifier le prompt** et **+ Nouvelle image**. L'image suivante n'écrase pas
   le choix retenu. La première image disponible est le choix par défaut.
5. **Short** : **Valider l'ensemble des images** exige une image disponible par
   plan, puis lance le montage et les contrôles. Le lecteur et le rapport restent
   identiques au mode automatique.

À toutes les étapes, **+** ouvre le prompt actuel, modifiable avant **Générer**.
Modifier un texte puis enregistrer, valider ou relancer ajoute une version,
sans effacer la précédente. Les anciennes propositions sont consultables dans
les rubriques « propositions conservées ». Les versions modifiées ne reprennent
pas une note calculée pour le texte précédent. La validation humaine n'est pas
une certification factuelle.

Une seule unité de génération travaille à la fois, sous le verrou GPU existant.
Une unité comprend la production d'une proposition et ses contrôles, ou une tâche
technique (recherche, voix, montage). Les demandes **+** passent juste après l'unité
en cours, dans l'ordre où elles ont été demandées, avant le remplissage automatique.
Choisir ne coupe pas le calcul en cours : son résultat est conservé. Les variantes
**automatiques encore en attente** de cette étape sont annulées. Les demandes
manuelles déjà envoyées sont conservées et restent prioritaires.

Le remplissage est borné : trois idées, deux scripts, deux découpages, puis le
nombre d'essais configuré par image, en parcourant tous les plans avant le tour
suivant. **+** permet de demander d'autres versions dans les budgets existants.
La voix est mise en file après le choix du script, sans validation supplémentaire ;
elle ne bloque pas la consultation du découpage ou des images. Le montage attend
la validation des images et la disponibilité de la voix.

La file, les versions et les choix sont enregistrés dans `live.json` sous verrou ;
les résultats de chaque calcul ont un identifiant stable pour la reprise après
interruption. Les propositions déjà affichées restent disponibles en cas d'erreur.
**Réessayer** reprend un calcul en erreur ; **+** permet de modifier sa demande.
**Arrêter / Reprendre** conserve les choix validés. Les anciens runs guidés de la
première PR conservent leur ancien parcours à validations de lots, pour ne pas
perdre leurs checkpoints. Créer une nouvelle production pour le mode progressif.

### Vérifications

```shell
python -m pytest tests -q
# Contrôle DOM optionnel, sans navigateur (npm install jsdom) :
node tests/live_dom.cjs
# Parcours navigateur, avec Playwright et Chromium installés :
python tests/ui_fixture_server.py
# Dans un autre terminal :
node tests/browser_guided.cjs
```

Le serveur de test utilise un dossier temporaire, simule l'IA et produit un vrai
petit MP4 avec FFmpeg. Fermer l'application normale avant d'utiliser son port 8765.
Le scénario navigateur couvre les arrivées progressives, les prompts éditables,
la priorité des demandes, la conservation des variantes, le choix des images
pendant le remplissage, le montage et le mode Auto.

Tests Python et DOM exécutés lors de cette modification. Le contrôle navigateur
reste non exécuté jusqu'au bout : Chromium est installé, mais son lancement est
bloqué par le système d'exécution (`socket(): Operation not permitted`). La qualité
réelle des générations et le parcours à la souris restent à vérifier sur Windows.


## V2 cinematic (integration progressive)

Cette branche ajoute une timeline de **plans** distincte des scenes narratives,
avec IDs stables `s01-p01`, timing entier en frames base sur les durées TTS,
mouvements Ken Burns easing (FFmpeg), et export `shot_timeline.json`.
Les cinq étapes et la validation explicite des images sont conservées.

En mode guidé, l'étape **Images** permet de régler un mouvement et un type
de média (image animée ou génération vidéo locale) sur jusqu'à trois plans par scène.
Seuls les plans effectivement créés selon la durée du TTS seront rendus.
Ces choix sont conservés dans `live.json`, sans relancer les images.

**I2V facultatif**, non activé par défaut : configurer
`production.video_generation.enabled = true`, `workflow_path` vers un
workflow **ComfyUI API** compatible avec les nœuds réellement installés, et
démarrer ComfyUI sur `http://127.0.0.1:8188`. L'interface du provider
requiert exactement un `LoadImage` et une sortie vidéo détectable.
Le workflow détermine modèle, résolution, durée et autres paramètres.
**Aucun modèle n'est installé ni téléchargé automatiquement.**
La compatibilité GPU, le modèle I2V et la durée doivent être testés localement.
Pour un clip inutilisable, absent, trop court ou sans workflow, le rendu
retombe sur une image animée et enregistre le motif.

**Limites actuelles** : il ne s'agit pas de la V2 complète du cahier des
charges. Le son design avancé, la recherche d'archives, la parallaxe par carte
de profondeur, la QA temporelle VLM, les thèmes de sous-titres et le diagnostic
de VRAM sont encore à implémenter. Aucun test matériel RTX 5080 n'a été effectué
dans cette branche. L'ancienne publication manuelle est conservée.
