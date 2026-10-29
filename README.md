# Synology Media Manager

## ⬇️ Télécharger pour Windows en un clic

[![Télécharger Synology Media Manager EXE](https://img.shields.io/badge/TÉLÉCHARGER-Synology_Media_Manager.exe-2363eb?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/Elikto/Synology-Media-Manager/releases/latest/download/SynologyMediaManager.exe)

**[⬇️ Télécharger directement SynologyMediaManager.exe](https://github.com/Elikto/Synology-Media-Manager/releases/latest/download/SynologyMediaManager.exe)**

Un seul fichier portable Windows 11 : télécharger puis **double-cliquer sur le fichier .exe**. Python n'est pas nécessaire.

[Voir les versions et leurs empreintes SHA-256](https://github.com/Elikto/Synology-Media-Manager/releases/latest) · [Voir les builds Windows](https://github.com/Elikto/Synology-Media-Manager/actions/workflows/release-windows.yml)

> L'exécutable est compilé automatiquement sur Windows par GitHub Actions et publié dans la dernière Release. Il n'est pas signé par un certificat de signature de code : Windows SmartScreen peut demander une confirmation. Télécharger uniquement depuis ce dépôt.

## Présentation

Application Windows de gestion **locale** d'un NAS Synology DSM, développée en Python et distribuée sous forme d'un **.exe autonome**. L'application fonctionne sur le PC de l'utilisateur pour accéder à son NAS via HTTPS/Tailscale ; ChatGPT n'a pas de connexion directe au réseau privé.

**Version 0.3.0 : audit DSM et préparation guidée des dossiers multimédias.** L'application ne modifie ni le RAID ni les disques et n'installe aucun paquet. Elle peut créer trois dossiers dans un partage existant, après confirmation. Le DS218j ne possède que 512 Mo de RAM.

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

## Mises à jour directement dans l'application

Cliquer sur **Vérifier les mises à jour**. Le programme :

1. Vérifie la dernière **GitHub Release** publiée pour Windows.
2. Demande une confirmation avant téléchargement.
3. Télécharge `SynologyMediaManager.exe` et `SHA256SUMS.txt` de la même release versionnée.
4. Vérifie la taille maximale et l'empreinte SHA-256 téléchargée.
5. Prépare une sauvegarde `.backup`, ferme l'ancienne application, la remplace et la redémarre automatiquement sous Windows.

L'application génère un script de remplacement **local**, lancé automatiquement après confirmation : il n'y a **aucune commande à copier-coller**. Le fichier doit rester nommé `SynologyMediaManager.exe` pour permettre les mises à jour.

En cas de souci, conserver l'ancienne version (`.backup`) et consulter `%LOCALAPPDATA%\SynologyMediaManager\update_error.txt`. Les fichiers exécutables restent hébergés sur GitHub Releases.

La somme SHA-256 protège contre la corruption ou la substitution entre l'exécutable et le manifeste ; **elle ne remplace pas une signature de code indépendante**, car les deux fichiers sont publiés sur le même compte GitHub.

## Fonctionnalités actuelles

- Connexion DSM en session `Core` avec certificat TLS épinglé ; lecture via `SYNO.Storage.CGI.Storage.load_info`.
- État des disques, température, SMART global, UNC, groupe SHR et volumes.
- Consultation des partages et paquets si les permissions DSM le permettent.
- Export de diagnostic réduit, sans secrets d'authentification ni numéros de série.
- Détection d'Ollama local et analyse facultative avec `qwen2.5-coder:7b` sans accès DSM accordé à Qwen.
- Journal horodaté et mise à jour intégrée.
- Création guidée des sous-dossiers Films, Series et Telechargements dans un partage Media déjà créé, après confirmation, sans suppression.

## Sécurité et confidentialité

- Ne jamais publier de mots de passe, numéros de série, adresses Tailscale, SID ou configurations privées dans le dépôt.
- La configuration locale se trouve dans `%LOCALAPPDATA%\SynologyMediaManager\config.json`, sans mot de passe.
- Un changement du certificat HTTPS bloquera la connexion jusqu'à une vérification manuelle.
- Aucune action de formatage, d'effacement, de changement de RAID ou d'installation de paquet.
- SHR ne remplace pas une sauvegarde. Surveiller toute anomalie SMART, notamment un compteur UNC non nul.

## Feuille de route

- Installation/configuration de Download Station et Media Server, selon compatibilité du DS218j.
- Gestion et visualisation des médias sur TV, PC, Android et iPhone.

## Pour les développeurs

Le script source reste disponible : [SynologyMediaManager.pyw](./SynologyMediaManager.pyw). Il nécessite Python 3.10+ et Tkinter, contrairement à l'exécutable Windows.

Vérification syntaxique : `python -m py_compile SynologyMediaManager.pyw`.

Tests : `python -m unittest discover -s tests -v`.

Le workflow [Build and publish Windows EXE](./.github/workflows/release-windows.yml) utilise PyInstaller sur `windows-latest`, calcule une empreinte SHA-256 et publie automatiquement l'EXE dans GitHub Releases. Il ne requiert aucun secret personnel du NAS.
