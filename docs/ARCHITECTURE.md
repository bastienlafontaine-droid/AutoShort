# Architecture implémentée — v0.1

## Processus

LANCER.cmd → scripts/start.ps1 → FastAPI / Uvicorn sur 127.0.0.1:8765.
Un dispatcher sélectionne le plus ancien run QUEUED et lance un worker Python.
Le worker exécute un graphe LangGraph séquentiel :
`discover → research → editorial → audio → images → render → final`.
Les boucles de sélection et correction sont bornées à l'intérieur de chaque étape.
Le graphe ne repose pas sur un agent superviseur qui improvise son propre plan.

## Données et reprise

SQLite WAL contient les runs et la file. Un verrou `server.lock` interdit deux
serveurs sur ce dossier ; `gpu.lock` interdit deux workers de génération.
Les sorties d'étapes sont des fichiers JSON remplacés atomiquement. La reprise rejoue
le graphe, mais charge les résultats existants. Ce mécanisme est un checkpoint
applicatif, pas un checkpointer LangGraph PostgreSQL.

La configuration est copiée à la création. Chaque média validé a une empreinte SHA-256.
Les dépendances sont invalidées si le fichier diffère. Le travail d'un lot non validé
peut être refait à la reprise. Les traces sont conservées pour diagnostic.

## Modèles / mémoire

Le texte et la vision utilisent l'API Ollama avec JSON Schema Pydantic.
Avant un appel, l'autre modèle AutoShort est déchargé. Avant SDXL, les deux sont
déchargés. Si d'autres modèles Ollama utilisent encore de la VRAM, le run s'arrête
avec une explication plutôt que de les fermer silencieusement.
SDXL est exécuté dans un processus court avec CPU offload et VAE tiling.
La mémoire CUDA est libérée à la fin du processus. Voix et ASR sont CPU.
La disponibilité du GPU est vérifiée avant SDXL, sans garantie de réservation
exclusive face à un autre programme externe.

## Agents et prompts

Prompts versionnés avec le code dans research.py, editorial.py, assets.py, pipeline.py.
Sorties typées dans schemas.py. Une réponse JSON invalide entraîne au maximum une
nouvelle tentative. Les compteurs couvrent les appels échoués. Le modèle n'a pas
accès à un shell, à un navigateur connecté ou aux fichiers de secrets.
Les agents de recherche voient des textes publics, traités comme données non fiables.

## Contrôles

Les citations du dossier doivent réellement apparaître dans les textes extraits.
Les juges vérifient ensuite le soutien des affirmations et l'originalité narrative.
Ce sont des estimations, pas une vérité certifiée. Les sources sont conservées.
Les juges visuels voient les images produites, puis une planche du montage.
Le montage final est entièrement décodé et analysé par FFmpeg.
Aucun score « probabilité de viralité » n'est affiché.

## Sécurité locale

Serveur lié à loopback, TrustedHost et jeton par processus pour les mutations,
contrôle d'Origin, aucune CORS permissive. La clé n'est jamais renvoyée au navigateur.
Les fichiers servis sont sur liste blanche, le dossier .env n'est pas exposé.
Recherche HTTP sans cookies, proxy ni authentification utilisateur ; blocage des
adresses IP privées et revalidation des redirections. Ce filtrage applicatif ne
constitue pas un pare-feu contre toutes les formes de DNS rebinding. Pour un service
exposé ou multi-utilisateur, ajouter isolation réseau et proxy de sortie contraint.
L'application livrée doit rester privée et locale.

## Extensions non implémentées

ComfyUI peut remplacer Diffusers derrière le contrat des producteurs d'images.
WhisperX peut remplacer l'alignement ASR par un service séparé.
Jev peut être ajouté comme évaluateur externe optionnel ; il n'est pas appelé ici.
Wan peut produire certains plans ; il n'est pas téléchargé ni activé ici.
PostgreSQL / Celery / comptes utilisateurs sont inutiles pour cette version mono-PC.
