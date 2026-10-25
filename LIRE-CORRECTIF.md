# AutoShort 0.2.3 — arrêter les corrections contradictoires du storyboard

Pour une installation avec 0.2.1 ou 0.2.2.
Fermer AutoShort, extraire le contenu du ZIP à côté de LANCER.cmd, lancer APPLIQUER-CORRECTIF.cmd, actualiser avec Ctrl+F5 et cliquer REPRENDRE sur la production bloquée.

Le code storytelling.py et assets.py est sauvegardé puis remplacé. La configuration et les productions restent disponibles.

Le juge exigeait alternativement une scène locale, une vue mondiale, un collage, puis interdisait le collage. Les nouveaux critères acceptent explicitement une scène représentative : un village pour une conséquence mondiale, un scientifique pour une communauté. Une image ne doit pas représenter toutes les propositions de la narration. Les corrections ne doivent jamais exiger un volcan distant visible derrière une scène européenne, un collage ou une animation dans une image fixe.

La reprise conserve le dernier storyboard corrigé lorsque son état existe (0.2.2), et démarre une évaluation avec les nouveaux critères. Les anciens verdicts ne sont pas réutilisés pour ce nouveau contrôle.
Maximum trois évaluations et deux corrections du storyboard, puis continuation vers les images même si des réserves restent. Le verdict refusé est conservé dans editorial/storyboard_reservations.json et le statut est continued_with_reservations, sans prétendre que le juge a accepté.
Un refus sans correction exploitable est lui aussi conservé sans bloquer cette étape.

Le juge de correspondance des images reçoit également le principe de représentation locale. Les seuils et tentatives de génération restent ceux de la configuration existante : un vrai défaut d'image peut encore mettre la production en revue. Les erreurs techniques, audio, recherche et budgets restent possibles. Ce patch ne contourne pas les limites globales.

Vérification : tests ciblés de limite de corrections et continuation, conservation du refus, reprise d'un état ancien, reprise après interruption, images hors sujet rejetées, caches et anglais. Les modèles sont simulés dans ces tests ; amélioration de la qualité à confirmer sur le rendu local.
