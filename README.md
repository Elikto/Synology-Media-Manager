# Synology Media Manager

## ⬇️ Télécharger pour Windows en un clic

[![Télécharger Synology Media Manager EXE](https://img.shields.io/badge/TÉLÉCHARGER-Synology_Media_Manager.exe-2363eb?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/Elikto/Synology-Media-Manager/releases/latest/download/SynologyMediaManager.exe)

**[⬇️ Télécharger directement SynologyMediaManager.exe](https://github.com/Elikto/Synology-Media-Manager/releases/latest/download/SynologyMediaManager.exe)**

Un seul fichier portable Windows 11 : télécharger puis **double-cliquer sur le fichier .exe**. Python n'est pas nécessaire.

[Voir les versions et leurs empreintes SHA-256](https://github.com/Elikto/Synology-Media-Manager/releases/latest) · [Voir les builds Windows](https://github.com/Elikto/Synology-Media-Manager/actions/workflows/release-windows.yml)

> L'exécutable est compilé automatiquement sur Windows par GitHub Actions et publié dans la dernière Release. Il n'est pas signé par un certificat de signature de code : Windows SmartScreen peut demander une confirmation. Télécharger uniquement depuis ce dépôt.

## Présentation

Application Windows de gestion **locale** d'un NAS Synology DSM, développée en Python et distribuée sous forme d'un **.exe autonome**. L'application fonctionne sur le PC de l'utilisateur pour accéder à son NAS via HTTPS/Tailscale ; ChatGPT n'a pas de connexion directe au réseau privé.

**Version 0.4.2 : bouton « Journal MAJ » pour consulter les résultats de mise à jour, correctif du bouton de téléchargement, bibliothèque multimédia et gestion de Download Station.** L'application ne modifie ni le RAID ni les disques et n'installe aucun paquet. Elle peut créer trois dossiers dans un partage existant, après confirmation. Le DS218j ne possède que 512 Mo de RAM.

## Installation initiale (une seule fois)

1. Cliquer sur le grand bouton **TÉLÉCHARGER** ci-dessus.
2. Double-cliquer sur **SynologyMediaManager.exe**, sans installation Python ni terminal.
3. Entrer l'adresse du NAS. Si une ancienne configuration locale contient une empreinte de certificat approuvée, elle peut être réutilisée. Sinon, cliquer sur **Lire certificat**, vérifier son empreinte depuis DSM ou une source indépendante, puis **Approuver certificat**.
4. Entrer les identifiants DSM dans l'application et cliquer sur **Auditer DSM**.

Les mots de passe ne sont pas enregistrés.

## Préparer la bibliothèque films et séries (v0.3.0)

1. Dans l'application, cliquer **Auditer DSM** pour vérifier le volume et les disques.
2. Cliquer **Créer dossiers multimédias** et lire la confirmation. Aucune écriture n'est effectuée sans accord explicite.
3. Si le partage racine `Media` n'existe pas, l'application **ouvre DSM** : créer **une seule fois** le dossier partagé `Media` dans **Panneau de configuration > Dossier partagé > Créer**, sur **volume1**, et lui donner les permissions appropriées. Les API de création des partages racine sont devenues incompatibles avec certaines versions récentes de DSM ; ce choix évite les commandes SSH et API non fiables.
4. Revenir dans l'application et cliquer de nouveau **Créer dossiers multimédias** : après relecture de la santé SHR, des permissions et des dossiers existants, l'application crée uniquement les sous-dossiers manquants `/Media/Films`, `/Media/Series` et `/Media/Telechargements` via l'API File Station.
5. En cas d'échec, l'application s'arrête et affiche le code DSM ; aucun dossier existant n'est supprimé ni écrasé.

**Prudence** : un UNC non nul sur le disque 1 impose une surveillance SMART et des sauvegardes indépendantes pour les fichiers irremplaçables. Les scripts ne remplacent pas une vraie sauvegarde.

## Installer les paquets et gérer les téléchargements (v0.4.0)

1. Mettre à jour l'application avec le bouton **Vérifier les mises à jour**.
2. Cliquer sur **Centre de paquets DSM**. Dans le Centre de paquets, installer **Download Station**, puis **Media Server** s'ils sont proposés comme compatibles avec le **DS218j**.
3. Dans DSM, configurer **Download Station** avec un dossier de téléchargement accessible au compte DSM. L'application utilise systématiquement la destination `Media/Telechargements` pour ses nouvelles tâches.
4. Dans DSM > **Panneau de configuration > Service d'indexation**, ajouter les dossiers `Media/Films` et `Media/Series` en catégorie vidéo pour Media Server/DLNA.
5. Dans l'application, utiliser **Tâches Download Station** pour afficher les 50 premières tâches, ou **Ajouter un téléchargement** pour créer une tâche depuis un lien HTTP/HTTPS ou magnet accepté par Download Station.

**Aucune installation de paquet n'est effectuée automatiquement :** le Centre de paquets est l'interface officielle qui contrôle la compatibilité des applications avec l'architecture et la version de DSM. L'ajout d'une tâche exige une confirmation explicite, vérifie la présence du volume et du dossier cible, et ne déplace ni ne supprime de fichier.

Pour programmer un téléchargement depuis un téléphone lorsque le PC est éteint, accéder à **DSM / Download Station** depuis le navigateur mobile via une connexion autorisée (QuickConnect ou Tailscale déjà configuré). **La recherche et le suivi automatisés de nouveaux épisodes façon Sonarr ne sont pas encore intégrés**. Le client Windows ne fournit pas encore d'interface web mobile dédiée.

### Compatibilité

Le DS218j n'a que 512 Mo de RAM, donc ne pas multiplier les applications lourdes ou exiger un transcodage vidéo. Pour la lecture : Kodi sur box Android TV, VLC sur PC/Android et Infuse/VLC sur iPhone en accédant au NAS par SMB sécurisé. Le DLNA est limité au réseau local et doit indexer les dossiers.

## Tester les mises à jour : v0.4.1 → v0.4.2

Cette release sert notamment à valider le bouton **Vérifier les mises à jour** corrigé en v0.4.1. **Depuis la version 0.4.1**, cliquer sur le bouton, accepter la version **0.4.2**, puis laisser l'application redémarrer. Le journal principal doit ensuite afficher `Version 0.4.2 prête`.

**Nouveauté : « Journal MAJ »** dans la seconde rangée de l'application. Ce bouton affiche les dernières étapes du script de remplacement Windows (réussite ou échec) sans ouvrir PowerShell. Le journal est stocké uniquement sur le PC, dans `%LOCALAPPDATA%\\SynologyMediaManager\\update_error.txt`.

La publication GitHub réussie **ne garantit pas** que l'installation sur le PC de chaque utilisateur fonctionne : le test final de mise à jour intégrée doit être confirmé sur Windows avec la version 0.4.1.

## Correctif important : mise à jour v0.4.1

Dans la version 0.4.0 (et les versions précédentes), la vérification détectait la nouvelle Release **mais ouvrait la boîte de dialogue avant que la tâche de vérification ne soit libérée**. En cliquant sur « Oui », l'application ignorait silencieusement le lancement du téléchargement.

La version **0.4.1** résout le problème : la boîte de dialogue est maintenant présentée **après** la fin de la vérification. Un test de non-régression Windows simule cette chronologie.

**Si tu es encore sur v0.4.0 ou avant**, utilise le bouton de téléchargement en tête de ce README **une seule fois**, puis ferme l'ancienne version et lance le nouveau fichier. Le programme conserve la configuration locale, mais le bouton de mise à jour des anciennes versions ne peut pas s'auto-réparer.

Pour tester le mécanisme corrigé lors de la prochaine version, ouvrir le journal de l'application, cliquer « Vérifier les mises à jour » et confirmer. Le journal doit alors afficher « Téléchargement et installation demandés », puis la vérification SHA-256 et le remplacement.

## Mises à jour directement dans l'application

Cliquer sur **Vérifier les mises à jour**. Le programme :

1. Vérifie la dernière **GitHub Release** publiée pour Windows.
2. Demande une confirmation avant téléchargement.
3. Télécharge `SynologyMediaManager.exe` et `SHA256SUMS.txt` de la même release versionnée.
4. Vérifie la taille maximale et l'empreinte SHA-256 téléchargée.
5. Prépare une sauvegarde `.backup`, ferme l'ancienne application, la remplace et la redémarre automatiquement sous Windows.

L'application génère un script de remplacement **local**, lancé automatiquement après confirmation : il n'y a **aucune commande à copier-coller**. Le fichier doit rester nommé `SynologyMediaManager.exe` pour permettre les mises à jour.

**Version 0.3.1 :** les mises à jour fonctionnent aussi si le navigateur a renommé l'EXE en `SynologyMediaManager (1).exe`. Le nouvel outil attend la fermeture du processus, vérifie le fichier téléchargé, effectue un remplacement avec sauvegarde et enregistre le résultat.

**Si le bouton d'une ancienne version (0.2.0 ou 0.3.0) échoue**, télécharger une seule fois l'EXE corrigé avec le bouton en haut de cette page, fermer l'ancien et exécuter le fichier téléchargé. Les versions suivantes devraient ensuite être récupérées par le bouton intégré ; cela reste à confirmer sur le PC réel.

En cas de souci, conserver l'ancienne version (`.backup`) et consulter `%LOCALAPPDATA%\SynologyMediaManager\update_error.txt` ; la dernière ligne de ce journal est aussi affichée dans l'interface à la prochaine ouverture. Les fichiers exécutables restent hébergés sur GitHub Releases.

La somme SHA-256 protège contre la corruption ou la substitution entre l'exécutable et le manifeste ; **elle ne remplace pas une signature de code indépendante**, car les deux fichiers sont publiés sur le même compte GitHub.

## Fonctionnalités actuelles

- Connexion DSM en session `Core` avec certificat TLS épinglé ; lecture via `SYNO.Storage.CGI.Storage.load_info`.
- État des disques, température, SMART global, UNC, groupe SHR et volumes.
- Consultation des partages et paquets si les permissions DSM le permettent.
- Export de diagnostic réduit, sans secrets d'authentification ni numéros de série.
- Détection d'Ollama local et analyse facultative avec `qwen2.5-coder:7b` sans accès DSM accordé à Qwen.
- Journal horodaté et mise à jour intégrée.
- Liste des téléchargements Download Station et ajout de tâche avec confirmation explicite vers Media/Telechargements.
- Assistant pour installer les paquets officiels depuis le Centre de paquets DSM.
- Création guidée des sous-dossiers Films, Series et Telechargements dans un partage Media déjà créé, après confirmation, sans suppression.

## Sécurité et confidentialité

- Ne jamais publier de mots de passe, numéros de série, adresses Tailscale, SID ou configurations privées dans le dépôt.
- La configuration locale se trouve dans `%LOCALAPPDATA%\SynologyMediaManager\config.json`, sans mot de passe.
- Un changement du certificat HTTPS bloquera la connexion jusqu'à une vérification manuelle.
- Aucune action de formatage, d'effacement, de changement de RAID ou d'installation de paquet.
- SHR ne remplace pas une sauvegarde. Surveiller toute anomalie SMART, notamment un compteur UNC non nul.

## Feuille de route

- Vérification et installation guidée de Download Station et Media Server dans DSM, selon la compatibilité réelle.
- Gestion et visualisation des médias sur TV, PC, Android et iPhone.

## Pour les développeurs

Le script source reste disponible : [SynologyMediaManager.pyw](./SynologyMediaManager.pyw). Il nécessite Python 3.10+ et Tkinter, contrairement à l'exécutable Windows.

Vérification syntaxique : `python -m py_compile SynologyMediaManager.pyw`.

Tests : `python -m unittest discover -s tests -v`.

Le workflow [Build and publish Windows EXE](./.github/workflows/release-windows.yml) utilise PyInstaller sur `windows-latest`, calcule une empreinte SHA-256 et publie automatiquement l'EXE dans GitHub Releases. Il ne requiert aucun secret personnel du NAS.
