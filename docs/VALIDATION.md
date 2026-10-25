# Validation de livraison

## Vérifié dans l'environnement de préparation (Linux, sans GPU NVIDIA)

- Résolution des dépendances pour Windows / Python 3.11 avec PyTorch CUDA 12.8.
- Compilation syntaxique des modules Python et syntaxe JavaScript.
- Tests de persistance, reprise, compteurs et annulation.
- Invalidation d'un média modifié et de ses descendants.
- Rejet des citations absentes et des URL privées usuelles.
- Comparaison de transcription avec normalisation des nombres.
- Sous-titres : ordre temporel, échappement ASS et arrondi des timestamps.
- API locale : jeton et origine requis, création/annulation/reprise,
  clé non renvoyée, chemin de fichier sur liste blanche.
- Graphe LangGraph complet avec services IA simulés, distinct du test des modèles.
- Rejet documentaire : un run refusé ne devient jamais READY.
- Vrai export FFmpeg de scènes synthétiques, voix de test sinusoïdale,
  incrustation des sous-titres et de la barre progressive, puis ffprobe,
  décodage complet et contrôle noir/silence.

La vidéo synthétique des tests n'est pas une démonstration de la qualité IA.
Les résultats exacts sont dans TEST_RESULTS.txt.

## Non vérifié ici

- Exécution des scripts PowerShell/winget sur Windows.
- Inférence et performances RTX 5080 / CUDA.
- Chargement réel des modèles Ollama, SDXL et Kokoro.
- Génération de bout en bout depuis une vraie recherche Brave payante.
- Qualité narrative, historique, visuelle et vocale sur un échantillon représentatif.

L'installateur effectue un préchargement réel et un test TTS/ASR sur le PC cible,
puis un diagnostic CUDA. Il reste nécessaire de produire et visionner une première
vidéo réelle. Une réussite des tests logiciels ne garantit pas que toutes les
combinaisons futures de dépendances/modèles fonctionneront.

## Critère de réception recommandé sur le PC cible

1. Diagnostic : CUDA, modèles, FFmpeg et clé configurés.
2. Écouter `data/voice-test.wav`.
3. Une vraie production arrive à READY ou à NEEDS_REVIEW avec un motif intelligible.
4. Vérifier l'histoire dans les sources et visionner les médias.
5. Interrompre une deuxième production puis la reprendre pour vérifier la reprise.
6. Mesurer durée totale et corrections humaines sur trois sujets avant de lancer des lots.

Conserver installation-lock.txt et les digests des modèles après cette validation.
