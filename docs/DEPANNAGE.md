# Dépannage

## Installation

- **Windows bloque le fichier téléchargé** : examiner les scripts. Dans les propriétés
  du ZIP téléchargé, utiliser « Débloquer » si présent, puis extraire à nouveau.
  Ne pas désactiver durablement les protections Windows.
- **winget absent** : installer « App Installer » depuis Microsoft Store.
- **uv / ffmpeg introuvable juste après installation** : fermer la fenêtre et relancer
  INSTALLER.cmd ; le PATH d'un processus déjà ouvert peut être périmé.
- **Permission administrateur** : certains installateurs peuvent afficher une demande UAC.
  Les scripts ne contournent pas cette demande.
- **Ollama modèle inconnu** : mettre à jour Ollama, puis refaire `ollama pull qwen3-vl:8b`.
- **Téléchargement interrompu** : relancer INSTALLER.cmd ; uv et Hugging Face réutilisent
  leurs caches. Ne pas supprimer vos caches pour une simple interruption.
- **CUDA rouge** : mettre à jour le pilote NVIDIA et relancer DIAGNOSTIC.cmd.
  Le diagnostic effectue une allocation et une opération GPU réelle ; il ne suffit pas
  que `nvidia-smi` voie la carte.
- **eSpeak / set_data_path** : relancer INSTALLER.cmd, qui réinstalle phonemizer-fork
  après les dépendances Kokoro. Deux distributions peuvent partager les mêmes modules.
- **Kokoro demande une dépendance distante** : garder Internet disponible au premier lancement.
  Le préchargement effectue un vrai test vocal et sa retranscription.

## Production

| Symptôme | Action |
|---|---|
| Aucun sujet valide | Lire les rejets sous `research/`, préciser le thème, nouveau run |
| Brave 401/403 | Vérifier la clé et l'accès au service Web Search |
| Brave 429 | Quota ou fréquence atteinte ; attendre selon le fournisseur puis reprendre |
| Modèle Ollama indisponible | Ouvrir Ollama, vérifier ses modèles, puis reprendre |
| VRAM insuffisante | Fermer les autres sessions IA et libérer les modèles Ollama externes |
| Fichier manquant | Reprendre : détection par empreinte et régénération des descendants |
| Audio refusé | Écouter les WAV ; noms propres et nombres peuvent faire diverger l'ASR |
| Image refusée | Voir les PNG et `images/review_*.json`; adapter le style du prochain run |
| Sous-titres imparfaits | Vérifier `subtitle_exact_match_coverage`; corriger le SRT pour publication si nécessaire |
| FFmpeg échoue | Lire `render.log`; vérifier que le build inclut libass et libx264 |
| Run interrompu | Redémarrer LANCER.cmd puis cliquer Reprendre |
| Budget atteint | Nouveau run après ajustement raisonné de config.toml |

`data/installation.log` concerne l'installation.
Chaque run possède `events.jsonl`, `worker.log`, `media.log`, `render.log` et parfois
`error.log`. L'interface donne accès aux dernières lignes des journaux.

Les dossiers `requests/` contiennent les demandes média, `traces/` les réponses des
agents et `search/` les recherches. La clé Brave n'est pas enregistrée dans ces traces.
Les chemins locaux sont présents dans les manifests : anonymiser avant partage.

## Arrêter / reprendre

Le bouton Arrêter demande une annulation : un appel Ollama déjà parti peut prendre
jusqu'à son timeout avant de rendre la main. Les appels média sont interrompus entre
les vérifications périodiques. Fermer l'application arrête le worker et ses enfants.
Après un arrêt brutal du PC, redémarrer et utiliser Reprendre.

## Mettre à jour sans perdre les vidéos

Sauvegarder `data/`, `.env`, `config.toml` et `installation-lock.txt`.
Remplacer uniquement le code. Ne pas lancer deux copies du même projet : leurs verrous
sont distincts et ne protègent pas le GPU l'une contre l'autre.
Ne pas supprimer un dossier de run pendant qu'il est actif.
