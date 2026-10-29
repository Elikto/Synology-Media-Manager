# Synology Media Manager

## ⬇️ Télécharger pour Windows en un clic

[![Télécharger Synology Media Manager EXE](https://img.shields.io/badge/TÉLÉCHARGER-Synology_Media_Manager.exe-2363eb?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/Elikto/Synology-Media-Manager/releases/latest/download/SynologyMediaManager.exe)

**[⬇️ Télécharger directement SynologyMediaManager.exe](https://github.com/Elikto/Synology-Media-Manager/releases/latest/download/SynologyMediaManager.exe)**

Un seul fichier portable Windows 11 : télécharger puis **double-cliquer sur le fichier .exe**. Python n'est pas nécessaire.

[Voir les versions et leurs empreintes SHA-256](https://github.com/Elikto/Synology-Media-Manager/releases/latest) · [Voir les builds Windows](https://github.com/Elikto/Synology-Media-Manager/actions/workflows/release-windows.yml)

> L'exécutable est compilé automatiquement sur Windows par GitHub Actions et publié dans la dernière Release. Il n'est pas signé par un certificat de signature de code : Windows SmartScreen peut demander une confirmation. Télécharger uniquement depuis ce dépôt.

## Présentation

Application Windows de gestion **locale** d'un NAS Synology DSM, développée en Python et distribuée sous forme d'un **.exe autonome**. L'application fonctionne sur le PC de l'utilisateur pour accéder à son NAS via HTTPS/Tailscale ; ChatGPT n'a pas de connexion directe au réseau privé.

**Version 0.8.0 : centre d'intégrations Sonarr, Radarr, Prowlarr, Kodi et Plex, connexion par API locale/Tailscale, création contrôlée des liaisons Prowlarr et rafraîchissement des bibliothèques Kodi/Plex.** Le tableau de bord du NAS et Download Station restent disponibles.

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

## Centre d'intégrations *arr, Kodi et Plex — v0.8.0

Cliquer sur **Intégrer Kodi / Plex / *arr** dans l'application. Ce bouton ouvre une seule fenêtre permettant de renseigner les adresses privées (LAN ou Tailscale) des services et leurs clés API, puis de valider une **seule opération** « Tester et connecter les services ».

Le gestionnaire :
1. Détecte Prowlarr, Sonarr (API v5/v3) et Radarr (API v3), si les services sont joignables et qu'une clé API est renseignée.
2. Interroge le schéma *réel* des applications Prowlarr et crée les liaisons Prowlarr → Sonarr et Radarr **uniquement si elles n'existent pas déjà**, avec synchronisation prudente `addOnly`. Si la version Prowlarr refuse le schéma ou la configuration, le programme conserve les paramètres existants et journalise le refus.
3. Demande à **Kodi** de scanner ses sources vidéo existantes via `VideoLibrary.Scan`, à condition que le serveur HTTP/JSON-RPC ait été autorisé dans Kodi.
4. Demande à **Plex Media Server** de rafraîchir les bibliothèques Films et Séries déjà créées, à l'aide du jeton Plex fourni.

Les clés API restent **uniquement en mémoire pendant l'action**, ne sont pas enregistrées dans un fichier, ni publiées sur GitHub. Les connexions directes sont limitées aux hôtes privés/Tailscale, sans redirection HTTP ; pour les services HTTP, le réseau LAN ou le tunnel Tailscale doit être digne de confiance. Les champs vides sont ignorés.

### Prérequis matériels non contournables

Le DS218j est un NAS ARMv7 32 bits doté de 512 Mo de RAM. Les images Docker actuelles de Prowlarr, Sonarr et Plex Media Server (LinuxServer.io) sont prévues pour x86-64 ou ARM64 : **ce programme ne tente pas de les installer sur le DS218j** et ne force pas Docker. Pour que la chaîne tourne avec le PC Windows éteint, il faut **un autre serveur x64/ARM64 qui reste allumé** (mini-PC, autre NAS compatible, VPS privé, etc.). Sans ce second hôte, Download Station peut continuer sur le Synology, mais les composants *arr externes ne s'exécutent pas 24 h/24. Les logiciels doivent être déjà installés sur leur hôte compatible : ce centre automatise la **connexion et la synchronisation**, pas une installation sur du matériel absent.

### Kodi / Plex

Le scan Kodi exige des sources SMB ou NFS déjà configurées sur l'appareil Kodi et l'accès HTTP/JSON-RPC activé. L'API Kodi `VideoLibrary.Scan` ne crée pas de sources. Plex doit déjà être lancé et posséder des sections Films/Séries ; son scanner ne remplace pas la configuration initiale du serveur. Aucune installation de Plex sur le DS218j n'est imposée.

**Liaison Prowlarr :** les URL envoyées à Prowlarr doivent être joignables **depuis son propre hôte**, pas uniquement depuis Windows. Si les services sont hébergés sur des machines différentes, utiliser leur IP locale/Tailscale plutôt que `127.0.0.1`.

Les tests Windows simulent ces services : les connexions et API ne sont pas encore validées sur ton propre équipement. Aucun fichier multimédia n'est supprimé ni déplacé et aucun paramètre SHR/RAID n'est modifié.

## Suivi automatique du NAS — v0.7.0

Un **tableau de bord** intégré affiche, sans ouvrir DSM ni retaper des commandes :
- l'état du stockage SHR et une alerte si un compteur UNC de disque est non nul ;
- le nombre d'éléments directement présents dans `Media/Films`, `Media/Series` et `Media/Telechargements` (sans lecture des contenus des fichiers ni parcours récursif) ;
- les 30 premiers téléchargements Download Station avec nom, état, taille et pourcentage calculé lorsque la taille téléchargée est disponible.

**Démarrage sans autre action :** après un audit réussi ou la configuration automatique, l'application lance le tableau de bord en lecture seule, puis actualise les informations **toutes les 60 secondes**. Le bouton **Suivi automatique : activé/désactivé** permet de suspendre ou relancer les interrogations. **Actualiser état** effectue une lecture ponctuelle.

Les identifiants DSM sont utilisés en mémoire pendant la session : ils ne sont pas sauvegardés et les journaux ne publient pas d'URL de téléchargement ni de secret. Les API NAS utilisées par le nouveau tableau de bord sont **en lecture seule**. Ce tableau de bord n'installe rien et ne déplace aucun média.

**Limite :** la surveillance de l'interface s'arrête quand le PC ou l'application est éteint ; Download Station, s'il est installé et actif, continue toutefois ses téléchargements directement sur le NAS. Les pourcentages peuvent être indisponibles selon les tâches et la version DSM. Les tests Windows utilisent un NAS simulé : vérifier la compatibilité de l'affichage sur le DS218j réel.

## Accès multimédia sans étape manuelle d'indexation — v0.6.2

La configuration automatique peut afficher « Indexation vidéo absente » si le service DLNA de DSM ne référence pas encore `Media/Films` et `Media/Series`. **Ce n'est pas une erreur de Download Station et cela n'empêche pas la lecture directe via SMB**.

- Cliquer sur **Ouvrir bibliothèque** pour ouvrir `\\\\<NAS>\\Media` dans l'Explorateur Windows, sans indexation vidéo ni modification de fichier. Il faut néanmoins que Windows ait accès au service SMB et que le compte possède les droits sur ce partage.
- Le diagnostic d'indexation reconnaît également un dossier vidéo parent (par exemple `/volume1/Media`) comme couvrant ses sous-dossiers.
- L'assistant de configuration n'affiche plus systématiquement une fenêtre « dernières étapes » pour la seule indexation DLNA : il inscrit cette information dans le journal.
- **Pour une TV exclusivement compatible DLNA**, l'indexation des deux dossiers reste une étape distincte dans le Panneau de configuration de DSM. Aucune API Synology fiable et documentée n'a été identifiée pour automatiser en toute sécurité cette création ; l'application ne simule pas une réussite.

Cette version ne force pas l'ouverture de ports Internet, ne change pas le RAID et ne supprime rien du NAS.

## Effacer le journal — v0.6.1

Cliquer sur **Effacer le journal**, au-dessus du journal des opérations, pour vider immédiatement l'affichage. Les nouveaux messages continueront à apparaître normalement, même si une tâche est en cours. Cette action ne supprime aucun fichier, aucun rapport enregistré ni aucun journal de mise à jour ; elle n'accède pas au NAS.

## Automatisation renforcée — v0.6.0

**Depuis la version 0.5.0, utiliser « Vérifier les mises à jour » pour recevoir 0.6.0 directement dans l'application.** Aucun terminal, téléchargement séparé ou installation Python.

Le bouton **Configurer automatiquement** reste le point d'entrée unique : il effectue un audit du SHR/volume, constate les dossiers déjà créés (sans les recréer), vérifie les paquets nécessaires, tente leur installation officielle si DSM expose les API compatibles, attend leur apparition réelle dans le Centre de paquets, puis essaie de configurer la destination Download Station et vérifie si l'indexation vidéo existe déjà.

**Améliorations v0.6.0 :**
- Le programme découvre les versions des API DSM au lieu d'exiger la version 1 pour toutes les fonctions.
- Installation de paquets via la séquence `SYNO.Entry.Request` de Synology (vérification de signature, installation non forcée, refus si la vérification échoue).
- Authentification avec jeton DSM quand disponible, sans publier de secrets ni les enregistrer sur GitHub.
- Attente et contrôle que les paquets apparaissent dans DSM après l'installation, plutôt que de présumer du succès.
- Interrogation **en lecture seule** des dossiers indexés, pour ne plus demander de reconfigurer l'indexation quand elle est déjà active.
- Rapport des seules étapes réellement non confirmées ; les demandes de configuration manuelle sont limitées à ces cas.

**Ce que l'outil ne peut pas garantir :** il n'a pas d'accès direct au NAS depuis GitHub ; toute installation nécessite des identifiants DSM et **une autorisation initiale**. Certaines opérations dépendent d'API internes incompatibles entre firmwares DSM. L'indexation DLNA ne sera **pas écrite automatiquement** tant que l'API d'ajout des dossiers et les permissions ne sont pas identifiées de manière sûre ; l'application détecte son état et signale le blocage éventuel. Les tests exécutés sous Windows simulent un DSM ; ils ne valent pas validation sur ton NAS réel.

**Sécurité :** aucune désinstallation, suppression de données, modification RAID, désactivation du pare-feu, exposition directe d'un port SMB ni installation de paquet d'origine inconnue. Le compteur UNC du premier disque justifie de conserver une sauvegarde indépendante.

## Configuration en un clic : v0.5.0

**Objectif : une seule action dans le programme, après avoir saisi les identifiants DSM.**

1. Dans la version **0.4.2**, cliquer sur **Vérifier les mises à jour** et accepter la **0.5.0**. Le bouton intégré conserve le même fichier EXE.
2. Dans la version 0.5.0, cliquer sur **Configurer automatiquement**, puis confirmer **une seule fois** les modifications proposées.
3. L'application vérifie le SHR, le volume et le partage `Media`, et crée seulement les sous-dossiers manquants. Elle tente ensuite de récupérer **DownloadStation** et **MediaServer** via le catalogue de paquets de DSM **uniquement** s'ils sont proposés par Synology pour ce NAS, avec contrôle de l'éditeur, du domaine de téléchargement et de la signature de paquet, sans forcer l'installation.
4. Si Download Station est disponible, l'application essaie de paramétrer sa destination par défaut sur `Media/Telechargements` et relit la configuration pour vérifier le résultat.
5. Elle indique dans le journal les opérations réussies et les **éventuelles étapes restantes**, avec proposition d'ouvrir DSM.

**Limite importante** : les API internes d'installation des paquets peuvent varier selon DSM et les permissions. Cette fonction est testée avec des NAS simulés ; **elle n'est pas encore validée sur un DS218j réel**. Elle n'exécute jamais de formatage, suppression, désinstallation, upgrade forcée ou changement de RAID. Si un paquet est inconnu, tiers, signé par un éditeur non confirmé, incompatible, ou nécessite des dépendances, **l'installation est refusée** et DSM doit prendre le relais.

Pour la découverte DLNA, les dossiers `Media/Films` et `Media/Series` doivent encore être ajoutés comme dossiers **Vidéo** dans **DSM > Panneau de configuration > Service d'indexation** : cette configuration n'utilise pas ici d'API d'écriture non vérifiée.

**PC éteint :** les téléchargements démarrés par Download Station continuent sur le NAS allumé, sans le programme Windows. Pour les piloter depuis un smartphone, accéder à DSM (QuickConnect ou Tailscale) et ouvrir Download Station ; ne jamais exposer directement SMB à Internet. Le serveur DS218j a 512 Mo de RAM : privilégier la lecture directe par SMB et DLNA, pas le transcodage vidéo.

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
