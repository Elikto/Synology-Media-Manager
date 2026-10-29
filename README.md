# Synology Media Manager

Application Windows de gestion **locale** d'un NAS Synology DSM, développée en Python. Le programme utilise le PC de l'utilisateur pour joindre son NAS via **HTTPS et Tailscale** ; ChatGPT n'accède pas directement au réseau privé.

> **Version 0.1.0 : diagnostic en lecture seule.** Aucun paquet installé, aucune création de dossier, aucune modification du stockage ou du RAID. Le DS218j peut être limité à 512 Mo de RAM.

## Installation initiale (une seule fois)

1. Avoir **Python 3.10 ou plus récent** installé sur Windows, avec Tkinter.
2. Télécharger [SynologyMediaManager.pyw](./SynologyMediaManager.pyw) via **Raw / Download raw** et conserver ce nom de fichier.
3. Double-cliquer sur le fichier. Aucun copier-coller PowerShell n'est nécessaire.
4. Si une ancienne application Synology Agent a déjà approuvé un certificat, sa configuration locale \`~/.synology_agent_local/config.json\` peut être réutilisée automatiquement. Sinon, indiquer l'adresse du NAS, cliquer sur **Lire certificat**, **comparer son empreinte depuis une source de confiance**, puis cliquer sur **Approuver certificat**.
5. Renseigner le compte DSM et le mot de passe **dans l'application**, puis cliquer sur **Auditer DSM**.

**Important** : ne pas approuver un certificat dont on n'a pas pu vérifier l'empreinte indépendamment. L'empreinte SHA-256 doit correspondre au certificat réellement souhaité.

## Bouton « Vérifier les mises à jour »

Dans l'application, cliquer sur **Vérifier les mises à jour**. Si une version plus récente est publiée sur \`main\` dans ce dépôt, l'application :

1. Lit \`update.json\` via HTTPS sur GitHub.
2. Demande confirmation.
3. Télécharge le fichier \`SynologyMediaManager.pyw\` depuis ce même dépôt.
4. Contrôle le SHA-256 indiqué dans le manifeste et la taille maximale.
5. Ferme l'application, conserve une copie \`.backup\`, remplace l'ancien fichier et redémarre.

Les mises à jour ne s'installent **jamais sans confirmation**. Le SHA-256 protège contre une corruption ou un fichier qui ne correspond pas au manifeste ; ce n'est **pas une signature indépendante** si le dépôt GitHub lui-même est compromis. Télécharger uniquement depuis le dépôt attendu.

> La mise à jour intégrée concerne **le fichier \`.pyw\`**. Un exécutable Windows \`.exe\` n'est **pas encore** disponible ; sa publication exigera un mécanisme de mise à jour adapté.

## Fonctionnalités actuelles

- Connexion DSM en session \`Core\` avec certificat TLS épinglé : méthode \`SYNO.Storage.CGI.Storage.load_info\`.
- État des deux disques, température, statut SMART global, compteur UNC, groupe SHR et volumes.
- Consultation de la liste des partages et paquets quand les autorisations DSM le permettent.
- Export JSON limité aux informations du diagnostic, sans secrets d'authentification ni numéros de série.
- Détection d'Ollama local et analyse facultative avec \`qwen2.5-coder:7b\` **sans aucun outil DSM accordé à Qwen**.
- Journal horodaté des actions et erreurs.
- Vérification et installation des nouvelles versions du logiciel.

## Sécurité et confidentialité

- **Ne jamais commiter** les mots de passe, numéros de série, adresses Tailscale, fichiers de configuration, empreintes de certificat, SID ou rapports non anonymisés.
- La configuration reste dans \`%LOCALAPPDATA%\SynologyMediaManager\config.json\` ; le mot de passe et les SID ne sont pas enregistrés dans ce fichier.
- Le certificat est contrôlé par empreinte SHA-256 approuvée localement. Une modification du certificat bloque l'accès et doit être examinée.
- L'application ne propose **aucune** opération de formatage, d'effacement ou de modification RAID.
- Un SHR ne remplace pas une sauvegarde externe. Si un compteur de défaut de disque est non nul (par exemple UNC), vérifier son évolution et l'état SMART détaillé.

## Feuille de route

- Assistant pour dossiers partagés, après validation explicite des actions et de l'état du stockage.
- Diagnostic de compatibilité Download Station / Media Server / SynoCommunity.
- Mise en place multimédia via DSM et lecteurs compatibles, sans exposer SMB sur Internet.
- Vérification des téléchargements et alertes de santé, sans automatismes destructifs.
- Packaging Windows \`.exe\` et système de mise à jour adapté aux binaires.

## Développement

Tests unitaires : \`python -m unittest discover -s tests -v\`.

Vérification de syntaxe : \`python -m py_compile SynologyMediaManager.pyw\`.

La CI GitHub teste le projet sous Windows. Les informations privées du NAS ne sont pas nécessaires à ces tests.
