# -*- coding: utf-8 -*-
"""Synology Media Manager - application locale Windows, sans dépendance externe."""
from __future__ import annotations

import datetime
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import urllib.parse
import urllib.request
import webbrowser

VERSION = "0.4.2"
REPOSITORY = "Elikto/Synology-Media-Manager"
RAW_BASE = "https://raw.githubusercontent.com/" + REPOSITORY + "/main/"
APP_NAME = "SynologyMediaManager.pyw"
EXE_NAME = "SynologyMediaManager.exe"
RELEASES_API = "https://api.github.com/repos/" + REPOSITORY + "/releases/latest"
RELEASES_URL = "https://github.com/" + REPOSITORY + "/releases/download/"
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SynologyMediaManager"
CONFIG_FILE = CONFIG_DIR / "config.json"
LEGACY_FILE = Path.home() / ".synology_agent_local" / "config.json"


def load_config():
    for path in (CONFIG_FILE, LEGACY_FILE):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {
                "host": str(data.get("host") or ""),
                "port": int(data.get("port") or 5001),
                "fingerprint": str(data.get("fingerprint") or "").replace(":", "").upper().strip(),
            }
        except (OSError, ValueError, TypeError):
            continue
    return {"host": "", "port": 5001, "fingerprint": ""}


def store_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(temp, CONFIG_FILE)


def sha256(data):
    return hashlib.sha256(data).hexdigest().lower()


def update_log_tail(path, max_lines=20):
    """Dernières étapes de la mise à jour Windows, sans accéder au NAS."""
    log_path = Path(path)
    if not log_path.is_file():
        return "Aucun journal de mise à jour pour cette installation."
    try:
        # Garder une limite de 64 Kio, y compris si le journal a beaucoup grandi.
        with log_path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 65536))
            content = stream.read().decode("utf-8-sig", errors="replace")
        return "\n".join(content.splitlines()[-max_lines:]) or "Journal vide."
    except OSError as error:
        return "Lecture du journal impossible : " + str(error)


def version_tuple(text):
    if not re.fullmatch(r"\d+\.\d+\.\d+", text):
        raise ValueError("Format de version invalide.")
    return tuple(int(x) for x in text.split("."))


def check_manifest(data):
    if not isinstance(data, dict):
        raise ValueError("Manifeste incorrect.")
    version = str(data.get("version", ""))
    version_tuple(version)
    digest = str(data.get("sha256", "")).lower()
    if not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("Empreinte SHA-256 de mise à jour incorrecte.")
    return version, digest



def release_version(data):
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        raise ValueError("Réponse GitHub Releases invalide.")
    tag = str(data.get("tag_name", ""))
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Version de release invalide.")
    assets = {str(a.get("name")) for a in data.get("assets", []) if isinstance(a, dict)}
    if EXE_NAME not in assets or "SHA256SUMS.txt" not in assets:
        raise ValueError("La dernière version ne contient pas encore tous les fichiers Windows.")
    return tag[1:]


def release_checksum(text):
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?SynologyMediaManager\.exe", line.strip())
        if match:
            return match.group(1).lower()
    raise ValueError("Empreinte SHA-256 de l'exécutable introuvable.")


def fetch_release_file(version, filename, maximum, sink=None):
    """Télécharge depuis une release versionnée ; calcule le SHA-256 à la volée."""
    version_tuple(version)
    if filename not in (EXE_NAME, "SHA256SUMS.txt"):
        raise ValueError("Nom de fichier de release non autorisé.")
    url = RELEASES_URL + "v" + version + "/" + filename
    request = urllib.request.Request(url, headers={"User-Agent": "SynologyMediaManager/" + VERSION})
    data = bytearray()
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=60) as response:
        with open(sink, "wb") if sink else tempfile.TemporaryFile() as target:
            while True:
                chunk = response.read(1_048_576)
                if not chunk:
                    break
                size += len(chunk)
                if size > maximum:
                    raise RuntimeError("Fichier téléchargé trop volumineux.")
                target.write(chunk)
                digest.update(chunk)
                if sink is None:
                    data.extend(chunk)
    return digest.hexdigest(), bytes(data), size


MEDIA_SHARE = "Media"
MEDIA_FOLDERS = ("Films", "Series", "Telechargements")


def check_media_storage(storage):
    """Empêche une nouvelle écriture si la santé du volume est incertaine."""
    pools = storage.get("storagePools") or []
    volumes = storage.get("volumes") or []
    if len(pools) != 1 or len(volumes) != 1:
        raise RuntimeError("Stockage différent du NAS attendu : aucune écriture.")
    pool = pools[0]
    if str(pool.get("status", "")).lower() != "normal":
        raise RuntimeError("Groupe SHR non normal : création refusée.")
    if pool.get("is_backgroundbuilding") not in (False, 0, None):
        raise RuntimeError("Opération RAID en cours : création reportée.")
    progress = pool.get("progress")
    if isinstance(progress, dict):
        pct = progress.get("percent", -1)
        try:
            number = float(pct)
        except (TypeError, ValueError):
            number = -1
        if 0 <= number < 100:
            raise RuntimeError("Synchronisation RAID inachevée : création refusée.")
    vol = volumes[0]
    if str(vol.get("status", "")).lower() not in ("normal", "healthy"):
        raise RuntimeError("Volume non normal : création refusée.")
    return True


def missing_media_folders(files):
    if not isinstance(files, list):
        raise RuntimeError("Réponse File Station inattendue : aucune écriture.")
    existing = {}
    for entry in files:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if name in MEDIA_FOLDERS:
            if not entry.get("isdir"):
                raise RuntimeError("Un fichier porte déjà le nom " + str(name))
            existing[name] = True
    return [n for n in MEDIA_FOLDERS if n not in existing]


def file_station_entries(client, sid):
    """Lecture des dossiers déjà présents : ne jamais écraser les fichiers."""
    result = client.request("SYNO.FileStation.List", 2, "list",
        {"folder_path": json.dumps("/" + MEDIA_SHARE),
         "offset": "0", "limit": "1000"}, sid=sid)
    total = int(result.get("total", -1))
    files = result.get("files")
    if not isinstance(files, list) or total < 0:
        raise RuntimeError("Lecture File Station impossible ; création annulée.")
    if total > len(files):
        # La page retournée ne contient pas tous les fichiers ; pas de supposition.
        raise RuntimeError("Dossier Media trop rempli pour une création sûre ; inspecter DSM.")
    return files


def create_media_subfolder(client, sid, name):
    if name not in MEDIA_FOLDERS:
        raise ValueError("Nom de dossier non autorisé.")
    return client.request("SYNO.FileStation.CreateFolder", 2, "create",
        {"folder_path": json.dumps(["/" + MEDIA_SHARE]),
         "name": json.dumps([name]),
         "force_parent": "false"}, sid=sid)


def check_media_share(shares):
    if not isinstance(shares, list):
        raise RuntimeError("Liste des partages non disponible.")
    matches = [entry for entry in shares if isinstance(entry, dict)
               and entry.get("name") == MEDIA_SHARE]
    if not matches:
        return False
    if len(matches) != 1 or matches[0].get("vol_path") != "/volume1":
        raise RuntimeError("Partage Media présent, mais sur un autre volume : création annulée.")
    return True



def validated_download_uri(value):
    """Autorise une seule demande explicite, exclut les destinations locales courantes."""
    uri = str(value).strip()
    if not uri or len(uri) > 2048 or any(ch in uri for ch in ("\r", "\n", "\x00", ",")):
        raise ValueError("Lien manquant, multiple ou invalide.")
    if uri.lower().startswith("magnet:?"):
        parsed = urllib.parse.urlsplit(uri)
        if parsed.scheme.lower() != "magnet":
            raise ValueError("Lien magnet invalide.")
        values = urllib.parse.parse_qs(parsed.query, max_num_fields=24)
        hashes = values.get("xt") or []
        if not any(x.lower().startswith(("urn:btih:", "urn:btmh:")) for x in hashes):
            raise ValueError("Magnet sans empreinte torrent valide.")
        return uri
    parsed = urllib.parse.urlsplit(uri)
    if parsed.scheme.lower() not in ("https", "http") or not parsed.hostname:
        raise ValueError("Lien HTTPS, HTTP ou magnet requis.")
    if parsed.username or parsed.password:
        raise ValueError("Ne fournis pas de lien avec identifiants intégrés.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".local", ".internal")):
        raise ValueError("Les liens locaux ne sont pas autorisés.")
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        if "." not in hostname:
            raise ValueError("Domaine public requis.")
    else:
        if not ip.is_global:
            raise ValueError("Les adresses IP privées ou locales ne sont pas autorisées.")
    return uri


def downloadstation_endpoint(api_info):
    if not isinstance(api_info, dict):
        raise RuntimeError("Download Station non disponible : installe-le depuis DSM.")
    entry = api_info.get("SYNO.DownloadStation.Task")
    if not isinstance(entry, dict):
        raise RuntimeError("API Download Station absente. Installer le paquet dans Centre de paquets.")
    path = str(entry.get("path", ""))
    if path not in ("entry.cgi", "DownloadStation/task.cgi"):
        raise RuntimeError("Chemin Download Station inconnu : opération annulée.")
    min_version = int(entry.get("minVersion", 1))
    max_version = int(entry.get("maxVersion", 0))
    if not min_version <= 1 <= max_version:
        raise RuntimeError("Version d'API Download Station non prise en charge.")
    return path


def downloadstation_tasks(client, sid):
    metadata = client.request("SYNO.API.Info", 1, "query",
        {"query": "SYNO.DownloadStation.Task"}, path="query.cgi")
    api_path = downloadstation_endpoint(metadata)
    result = client.request("SYNO.DownloadStation.Task", 1, "list",
        {"offset": "0", "limit": "50", "additional": "detail,transfer"},
        sid=sid, path=api_path)
    tasks = result.get("tasks")
    if not isinstance(tasks, list):
        raise RuntimeError("Liste des téléchargements invalide.")
    return tasks, int(result.get("total", len(tasks)))


def create_downloadstation_task(client, sid, uri):
    verified = validated_download_uri(uri)
    metadata = client.request("SYNO.API.Info", 1, "query",
        {"query": "SYNO.DownloadStation.Task"}, path="query.cgi")
    api_path = downloadstation_endpoint(metadata)
    return client.request("SYNO.DownloadStation.Task", 1, "create",
        {"uri": verified, "destination": "Media/Telechargements"},
        sid=sid, path=api_path)


def redact_report(data):
    """Résumé sans identifiants, numéros de série, SID ou détails du réseau."""
    disks = data.get("disks", [])
    pools = data.get("storagePools", [])
    volumes = data.get("volumes", [])
    return {
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "app_version": VERSION,
        "mode": "lecture seule",
        "disks": [
            {"name": d.get("name"), "model": d.get("model"),
             "status": d.get("status"), "smart": d.get("smart_status"),
             "temperature_c": d.get("temp"), "unc": d.get("unc")}
            for d in disks
        ],
        "pools": [
            {"status": p.get("status"), "type": p.get("device_type"),
             "background": p.get("is_backgroundbuilding"),
             "progress": (p.get("progress") or {}).get("percent")}
            for p in pools
        ],
        "volumes": [
            {"id": v.get("id"), "status": v.get("status"),
             "filesystem": v.get("fs_type")}
            for v in volumes
        ],
    }


class DsmClient:
    """Connexion HTTPS avec empreinte de certificat approuvée localement."""
    def __init__(self, host, port, fingerprint):
        self.host = host
        self.port = int(port)
        self.pin = fingerprint.replace(":", "").upper()
        if not re.fullmatch("[0-9A-F]{64}", self.pin):
            raise RuntimeError("Empreinte HTTPS manquante : vérifie et approuve le certificat.")
        if not self.host or "/" in self.host or "://" in self.host:
            raise RuntimeError("Indique uniquement le nom ou l'adresse IP du NAS.")

    def request(self, api, version, method, params=None, sid=None, path="entry.cgi"):
        if path not in ("entry.cgi", "query.cgi", "DownloadStation/task.cgi"):
            raise RuntimeError("Chemin API DSM non autorisé.")
        values = {"api": api, "version": str(version), "method": method}
        values.update(params or {})
        if sid:
            values["_sid"] = sid
        payload = urllib.parse.urlencode(values).encode("utf-8")
        # Confiance accordée UNIQUEMENT après comparaison SHA-256 avec l'empreinte locale.
        context = ssl._create_unverified_context()
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=25, context=context)
        try:
            conn.connect()
            actual = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest().upper()
            if actual != self.pin:
                raise RuntimeError("CERTIFICAT MODIFIÉ : connexion interrompue (empreinte différente).")
            conn.request("POST", "/webapi/" + path, payload, {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            })
            response = conn.getresponse()
            raw = response.read(4_000_001)
            if len(raw) > 4_000_000 or response.status != 200:
                raise RuntimeError("Réponse DSM inattendue (HTTP ou taille).")
            data = json.loads(raw.decode("utf-8"))
            if not data.get("success"):
                code = (data.get("error") or {}).get("code", "?")
                raise RuntimeError(f"{api}.{method}: erreur DSM {code}")
            return data.get("data") or {}
        finally:
            conn.close()

    def login(self, username, password, session="Core"):
        if session not in ("Core", "FileStation", "DownloadStation"):
            raise ValueError("Session DSM non autorisée.")
        data = self.request("SYNO.API.Auth", 6, "login", {
            "account": username, "passwd": password, "session": session, "format": "sid",
        })
        sid = data.get("sid")
        if not sid:
            raise RuntimeError("Session absente (authentification supplémentaire possible).")
        return sid

    def logout(self, sid, session="Core"):
        try:
            self.request("SYNO.API.Auth", 6, "logout", {"session": session}, sid=sid)
        except Exception:
            pass


def observed_certificate(host, port):
    if not host or "/" in host or "://" in host:
        raise ValueError("Adresse du NAS incorrecte.")
    conn = http.client.HTTPSConnection(
        host, int(port), timeout=15, context=ssl._create_unverified_context()
    )
    try:
        conn.connect()
        return hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest().upper()
    finally:
        conn.close()


# Ce code reste local et ne télécharge qu'un fichier vérifié par SHA-256.
# Il prend le relais une fois que l'interface s'est fermée, sans PowerShell.
UPDATER = r"""
import os, pathlib, shutil, subprocess, sys, time
target, staged, exe, logfile = map(pathlib.Path, sys.argv[1:5])
for attempt in range(40):
    try:
        backup = target.with_suffix(target.suffix + ".backup")
        shutil.copy2(target, backup)
        os.replace(staged, target)
        subprocess.Popen([str(exe), str(target)], cwd=str(target.parent))
        sys.exit(0)
    except (PermissionError, OSError) as exc:
        time.sleep(.5)
try:
    logfile.parent.mkdir(parents=True, exist_ok=True)
    logfile.write_text("Échec de mise à jour : fichier en cours d'utilisation.", encoding="utf-8")
except Exception:
    pass
sys.exit(1)
"""



# Mise à jour EXE : fichier PowerShell LOCAL, généré par l'application,
# utilisé uniquement pour remplacer le programme APRÈS sa fermeture.
EXE_UPDATER = r"""
param(
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][string]$Staged,
    [Parameter(Mandatory=$true)][string]$LogPath,
    [int]$ParentPid = 0,
    [switch]$NoLaunch
)
$ErrorActionPreference = 'Stop'
function Write-UpdateLog([string]$Message) {
    try {
        $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "[$stamp] $Message"
    } catch { }
}
try {
    $directory = Split-Path -Path $LogPath -Parent
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    Write-UpdateLog 'Updater started'
    if ($ParentPid -gt 0) {
        try { Wait-Process -Id $ParentPid -Timeout 90 -ErrorAction SilentlyContinue }
        catch { Write-UpdateLog 'Parent process wait timed out' }
    }
    if (-not (Test-Path -LiteralPath $Staged -PathType Leaf)) {
        throw 'Staged executable is missing'
    }
    $backup = $Target + '.backup'
    $lastError = 'Unknown replacement error'
    $installed = $false
    $siblingStage = $Target + '.update'
    for ($i = 0; $i -lt 120; $i++) {
        try {
            # File.Replace needs files on the same disk.
            [System.IO.File]::Copy($Staged, $siblingStage, $true)
            if (Test-Path -LiteralPath $Target) {
                # Atomically back up and replace only the current executable.
                [System.IO.File]::Replace($siblingStage, $Target, $backup, $true)
            } else {
                [System.IO.File]::Move($siblingStage, $Target)
            }
            $installed = $true
            break
        } catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $installed) { throw "Update could not replace target: $lastError" }
    try { Remove-Item -LiteralPath $Staged -Force -ErrorAction SilentlyContinue } catch { }
    Write-UpdateLog 'Replacement successful'
    if (-not $NoLaunch) {
        Start-Process -FilePath $Target -WorkingDirectory (Split-Path -Path $Target -Parent)
        Write-UpdateLog 'New executable launched'
    }
    exit 0
} catch {
    Write-UpdateLog ("FAILURE: " + $_.Exception.Message)
    exit 1
}
"""


class Application:
    def __init__(self, root):
        self.root = root
        root.title("Synology Media Manager " + VERSION)
        root.geometry("920x720")
        self.events = queue.Queue()
        self.busy = False
        self.latest = None
        self.report = None
        self.pending_fp = None
        self.pending_update = None
        self.cfg = load_config()
        self.host = tk.StringVar(value=self.cfg["host"])
        self.port = tk.StringVar(value=str(self.cfg["port"]))
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.status = tk.StringVar(value="Prêt — modifications uniquement après confirmation")
        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="SYNOLOGY MEDIA MANAGER", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Audit sécurisé du NAS · Qwen local · Mise à jour depuis GitHub",
                  foreground="#526577").pack(anchor="w", pady=(2, 10))
        conn = ttk.LabelFrame(outer, text="Connexion NAS (les secrets ne sont pas enregistrés)", padding=8)
        conn.pack(fill="x")
        line = ttk.Frame(conn)
        line.pack(fill="x")
        ttk.Label(line, text="Hôte Tailscale :").pack(side="left")
        ttk.Entry(line, width=22, textvariable=self.host).pack(side="left", padx=6)
        ttk.Label(line, text="Port :").pack(side="left")
        ttk.Entry(line, width=7, textvariable=self.port).pack(side="left", padx=6)
        ttk.Button(line, text="Lire certificat", command=self.inspect_cert).pack(side="left", padx=4)
        ttk.Button(line, text="Approuver certificat", command=self.accept_cert).pack(side="left")
        auth = ttk.Frame(conn)
        auth.pack(fill="x", pady=(9, 0))
        ttk.Label(auth, text="Compte DSM :").pack(side="left")
        ttk.Entry(auth, textvariable=self.username, width=23).pack(side="left", padx=6)
        ttk.Label(auth, text="Mot de passe :").pack(side="left")
        ttk.Entry(auth, textvariable=self.password, show="*", width=27).pack(side="left", padx=6)
        row = ttk.Frame(outer)
        row.pack(fill="x", pady=11)
        self.audit_button = ttk.Button(row, text="Auditer DSM", command=self.audit)
        self.audit_button.pack(side="left", padx=(0, 7))
        ttk.Button(row, text="Tester Ollama", command=self.test_ollama).pack(side="left", padx=3)
        ttk.Button(row, text="Analyse Qwen", command=self.analyze_qwen).pack(side="left", padx=3)
        ttk.Button(row, text="Exporter rapport", command=self.export).pack(side="left", padx=3)
        ttk.Button(row, text="Vérifier les mises à jour", command=self.check_updates).pack(side="left", padx=3)
        media_row = ttk.Frame(outer)
        media_row.pack(fill="x", pady=(0, 11))
        ttk.Button(media_row, text="Créer dossiers multimédias", command=self.prepare_media).pack(side="left", padx=(0, 7))
        ttk.Button(media_row, text="Ouvrir DSM", command=self.open_dsm).pack(side="left", padx=3)
        ttk.Button(media_row, text="Journal MAJ", command=self.show_update_history).pack(side="left", padx=3)
        ttk.Label(media_row, text="Bibliothèque sur volume1.",
                  foreground="#526577").pack(side="left", padx=9)
        download_row = ttk.Frame(outer)
        download_row.pack(fill="x", pady=(0, 10))
        ttk.Button(download_row, text="Centre de paquets DSM", command=self.open_packages).pack(side="left", padx=(0, 7))
        ttk.Button(download_row, text="Tâches Download Station", command=self.download_tasks).pack(side="left", padx=3)
        ttk.Button(download_row, text="Ajouter un téléchargement", command=self.add_download).pack(side="left", padx=3)
        ttk.Label(download_row, text="Installation des paquets depuis DSM.",
                  foreground="#526577").pack(side="left", padx=8)
        ttk.Label(outer, textvariable=self.status).pack(anchor="w")
        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(fill="x", pady=(4, 8))
        self.logarea = tk.Text(outer, font=("Consolas", 10), wrap="word", height=23)
        self.logarea.pack(fill="both", expand=True)
        self.logarea.configure(state="disabled")
        ttk.Label(outer, text="Lecture seule par défaut ; création de dossiers et nouvelles tâches uniquement sur confirmation. "
                  "Aucune installation automatique ni modification RAID. Disque 1 : UNC à surveiller.",
                  foreground="#8b5b15", wraplength=860).pack(anchor="w", pady=(8, 0))
        self.log("Version " + VERSION + " prête. Les paramètres locaux ne seront jamais publiés sur GitHub.")
        self.log("Diagnostic MAJ disponible via le bouton « Journal MAJ ».")
        old_update_log = CONFIG_DIR / "update_error.txt"
        if old_update_log.is_file():
            try:
                rows = old_update_log.read_text(encoding="utf-8-sig").splitlines()
                if rows:
                    self.log("Dernière mise à jour : " + rows[-1][-350:])
            except OSError:
                pass
        self.root.after(100, self.poll)

    def log(self, value):
        self.events.put(("log", str(value)))

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.logarea.configure(state="normal")
                    self.logarea.insert("end", f"[{datetime.datetime.now():%H:%M:%S}] {value}\n")
                    self.logarea.see("end")
                    self.logarea.configure(state="disabled")
                elif kind == "busy":
                    self.busy = value
                    self.status.set("Opération en cours…" if value else "Prêt")
                    if value:
                        self.progress.start(10)
                    else:
                        self.progress.stop()
                        # La vérification vient de se terminer. On peut maintenant
                        # proposer la mise à jour sans que background() la refuse.
                        if self.pending_update is not None:
                            info = self.pending_update
                            self.pending_update = None
                            self.root.after_idle(
                                lambda info=info: self.offer_update(info))
                elif kind == "report":
                    self.report = value
                elif kind == "error":
                    messagebox.showerror("Synology Media Manager", value)
                elif kind == "cert":
                    self.pending_fp = value
                    messagebox.showinfo("Certificat observé",
                        "SHA-256 :\n" + ":".join(value[i:i+2] for i in range(0, 64, 2)) +
                        "\n\nCompare cette empreinte avec une source indépendante avant de l'approuver.")
                elif kind == "update":
                    # Le worker est encore marqué "busy" à ce stade.
                    # Attendre obligatoirement son évènement busy=False.
                    self.pending_update = value
                    self.log("Version " + str(value[0]) +
                             " disponible : préparation de l'installation…")
                elif kind == "media_missing":
                    if messagebox.askyesno("Partager Media absent",
                        "Le partage « Media » n'existe pas encore.\n\n"
                        "Crée-le une seule fois dans DSM : Panneau de configuration > "
                        "Dossier partagé > Créer, sur volume1.\n\n"
                        "Ouvrir DSM maintenant ?"):
                        self.open_dsm()
                elif kind == "packages_help":
                    messagebox.showinfo("Paquets Synology",
                        "Installe Download Station et Media Server dans le Centre de paquets DSM.\n"
                        "Choisis seulement les paquets proposés comme compatibles avec ton NAS.\n"
                        "Dans Media Server, indexe ensuite /Media/Films et /Media/Series.\n"
                        "Aucun paquet n'a été installé par cet outil.")
                    self.open_dsm()
                elif kind == "restart":
                    self.root.after(400, self.root.destroy)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def background(self, work):
        if self.busy:
            return
        self.events.put(("busy", True))
        def job():
            try:
                work()
            except Exception as exc:
                self.log("ERREUR : " + str(exc))
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("busy", False))
        threading.Thread(target=job, daemon=True).start()

    def settings(self):
        host = self.host.get().strip()
        port = int(self.port.get())
        if port < 1 or port > 65535 or not host or "/" in host or "://" in host:
            raise ValueError("Adresse du NAS ou port invalide.")
        if host != self.cfg.get("host") or port != self.cfg.get("port"):
            # Le pin d'un autre hôte n'est jamais automatiquement réutilisé.
            self.cfg = {"host": host, "port": port, "fingerprint": ""}
            self.pending_fp = None
        return host, port

    def inspect_cert(self):
        def work():
            host, port = self.settings()
            observed = observed_certificate(host, port)
            self.events.put(("cert", observed))
            self.log("Empreinte HTTPS reçue ; approbation manuelle requise.")
        self.background(work)

    def accept_cert(self):
        if not self.pending_fp:
            messagebox.showwarning("Certificat", "Clique d'abord sur Lire certificat.")
            return
        if not messagebox.askyesno("Vérification indépendante",
                "As-tu comparé l'empreinte à celle du certificat affiché dans DSM, "
                "sans te fier uniquement à cette fenêtre ?"):
            return
        host, port = self.settings()
        self.cfg = {"host": host, "port": port, "fingerprint": self.pending_fp}
        store_config(self.cfg)
        self.log("Certificat épinglé localement. En cas de changement, accès bloqué.")

    def open_dsm(self):
        try:
            host, port = self.settings()
            if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
                raise ValueError("Adresse NAS non prise en charge pour ouverture navigateur.")
            url = "https://" + host + ":" + str(port) + "/"
            webbrowser.open(url)
            self.log("DSM ouvert dans le navigateur. Connexion manuelle à effectuer.")
        except Exception as exc:
            messagebox.showerror("Ouvrir DSM", str(exc))

    def prepare_media(self):
        if not messagebox.askyesno("Créer les dossiers multimédias",
            "Ce bouton vérifie le SHR et le partage « Media » sur volume1, puis "
            "crée UNIQUEMENT les dossiers absents :\n"
            "  • Films\n  • Series\n  • Telechargements\n\n"
            "Le disque 1 présente toujours UNC=129. Les données importantes "
            "doivent être sauvegardées indépendamment.\n\n"
            "Autorises-tu explicitement cette création, sans suppression ni changement RAID ?"):
            return
        user, password = self.username.get().strip(), self.password.get()
        if not user or not password:
            messagebox.showwarning("DSM", "Saisis les identifiants DSM dans l'application.")
            return

        def work():
            host, port = self.settings()
            client = DsmClient(host, port, self.cfg.get("fingerprint", ""))
            sid = None
            fs_sid = None
            try:
                sid = client.login(user, password)
                self.log("Préparation multimédia : relecture du SHR (aucune modification)…")
                storage = client.request("SYNO.Storage.CGI.Storage", 1, "load_info", sid=sid)
                check_media_storage(storage)
                self.log("Contrôle SHR et volume : OK.")
                share_data = client.request("SYNO.Core.Share", 1, "list", sid=sid)
                if not check_media_share(share_data.get("shares")):
                    self.log("Aucun partage « Media » trouvé. Action stoppée : "
                             "il doit être créé depuis DSM une seule fois.")
                    self.events.put(("media_missing", None))
                    return
                fs_sid = client.login(user, password, session="FileStation")
                self.log("Session File Station créée ; liste des dossiers en lecture seule…")
                files = file_station_entries(client, fs_sid)
                missing = missing_media_folders(files)
                if not missing:
                    self.log("Tous les dossiers multimédias existent déjà. Aucune écriture.")
                    return
                self.log("Création limitée aux dossiers absents : " + ", ".join(missing))
                for name in missing:
                    create_media_subfolder(client, fs_sid, name)
                    self.log("Dossier créé : /Media/" + name)
                self.log("Préparation terminée. Aucun fichier supprimé ou déplacé.")
            finally:
                if fs_sid:
                    client.logout(fs_sid, session="FileStation")
                if sid:
                    client.logout(sid)

        self.background(work)

    def open_packages(self):
        messagebox.showinfo("Centre de paquets",
            "Dans DSM > Centre de paquets > Tous les paquets, recherche :\n\n"
            "1. Download Station (téléchargements sur le NAS)\n"
            "2. Media Server (DLNA pour la télévision)\n\n"
            "Clique sur Installer pour chacun, seulement s'ils sont proposés comme compatibles.\n"
            "Ensuite, configure dans DSM l'indexation multimédia de Media/Films et Media/Series.\n"
            "Cette application n'installe pas de paquets en ton nom.")
        self.open_dsm()

    def download_tasks(self):
        user, password = self.username.get().strip(), self.password.get()
        if not user or not password:
            messagebox.showwarning("DSM", "Renseigne les identifiants DSM pour consulter Download Station.")
            return
        def work():
            host, port = self.settings()
            client = DsmClient(host, port, self.cfg.get("fingerprint", ""))
            sid = None
            try:
                sid = client.login(user, password, session="DownloadStation")
                tasks, total = downloadstation_tasks(client, sid)
                self.log(f"Download Station : {total} tâche(s), {len(tasks)} affichée(s).")
                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    title = str(task.get("title") or "Sans titre")
                    status = str(task.get("status") or "inconnu")
                    size = task.get("size", 0)
                    try:
                        total_mb = round(int(size) / 1048576, 1)
                        extra = f" ({total_mb} Mio)"
                    except (ValueError, TypeError):
                        extra = ""
                    self.log(f"  • {title[:110]} — {status}{extra}")
                if total > len(tasks):
                    self.log("Affichage limité aux 50 premières tâches.")
            finally:
                if sid:
                    client.logout(sid, session="DownloadStation")
        self.background(work)

    def add_download(self):
        uri = simpledialog.askstring("Nouvelle tâche",
            "Colle un lien HTTPS/HTTP direct ou magnet autorisé.\n"
            "Destination : Media/Telechargements sur le NAS.\n"
            "Un seul lien par demande.", parent=self.root)
        if uri is None:
            return
        try:
            uri = validated_download_uri(uri)
        except ValueError as exc:
            messagebox.showerror("Lien refusé", str(exc))
            return
        parsed = urllib.parse.urlsplit(uri)
        origin = "magnet (torrent)" if parsed.scheme == "magnet" else (parsed.hostname or "hôte inconnu")
        if not messagebox.askyesno("Autoriser le téléchargement",
            "Lancer cette tâche Download Station sur TON NAS ?\n\n"
            "Source : " + origin + "\n"
            "Destination : Media/Telechargements\n\n"
            "N'ajoute que des contenus que tu es autorisé à télécharger.\n"
            "Aucune tâche ne sera créée sans cette confirmation."):
            return
        user, password = self.username.get().strip(), self.password.get()
        if not user or not password:
            messagebox.showwarning("DSM", "Renseigne les identifiants DSM.")
            return
        def work():
            host, port = self.settings()
            client = DsmClient(host, port, self.cfg.get("fingerprint", ""))
            core_sid = None
            dl_sid = None
            fs_sid = None
            try:
                core_sid = client.login(user, password)
                storage = client.request("SYNO.Storage.CGI.Storage", 1, "load_info", sid=core_sid)
                check_media_storage(storage)
                shares = client.request("SYNO.Core.Share", 1, "list", sid=core_sid).get("shares")
                if not check_media_share(shares):
                    raise RuntimeError("Le partage Media sur volume1 est absent.")
                fs_sid = client.login(user, password, session="FileStation")
                files = file_station_entries(client, fs_sid)
                if "Telechargements" in missing_media_folders(files):
                    raise RuntimeError("Le dossier Media/Telechargements n'existe pas.")
                dl_sid = client.login(user, password, session="DownloadStation")
                create_downloadstation_task(client, dl_sid, uri)
                self.log("Nouvelle tâche acceptée par Download Station, destination : Media/Telechargements.")
                self.log("Pour voir sa progression, clique sur Tâches Download Station.")
            finally:
                if dl_sid:
                    client.logout(dl_sid, session="DownloadStation")
                if fs_sid:
                    client.logout(fs_sid, session="FileStation")
                if core_sid:
                    client.logout(core_sid)
        self.background(work)

    def audit(self):
        user, password = self.username.get().strip(), self.password.get()
        if not user or not password:
            messagebox.showwarning("DSM", "Saisis les identifiants DSM directement ici.")
            return
        def work():
            host, port = self.settings()
            client = DsmClient(host, port, self.cfg.get("fingerprint", ""))
            sid = None
            try:
                sid = client.login(user, password)
                self.log("Authentification Core OK. Lecture du stockage…")
                storage = client.request("SYNO.Storage.CGI.Storage", 1, "load_info", sid=sid)
                report = redact_report(storage)
                self.events.put(("report", report))
                for disk in report["disks"]:
                    self.log(f'{disk["name"]} : {disk["status"]}, SMART={disk["smart"]}, '
                             f'{disk["temperature_c"]}°C, UNC={disk["unc"]}')
                    try:
                        if int(disk["unc"] or 0):
                            self.log("ATTENTION : UNC non nul ; vérification SMART et sauvegarde recommandées.")
                    except (ValueError, TypeError):
                        pass
                for pool in report["pools"]:
                    self.log(f'SHR : {pool["status"]}, synchronisation={pool["progress"]}, '
                             f'activité={pool["background"]}')
                self.log(f'Volumes : {len(report["volumes"])}')
                try:
                    shares = client.request("SYNO.Core.Share", 1, "list", sid=sid).get("shares", [])
                    self.log("Partages DSM : " + (", ".join(str(s.get("name")) for s in shares) if shares else "aucun"))
                except Exception as exc:
                    self.log("Partages non disponibles : " + str(exc))
                try:
                    packs = client.request("SYNO.Core.Package", 2, "list", sid=sid).get("packages", [])
                    names = [str(p.get("name") or p.get("id") or "") for p in packs]
                    self.log("Paquets : " + (", ".join(x for x in names if x) if names else "aucun"))
                except Exception as exc:
                    self.log("Paquets non disponibles : " + str(exc))
                self.log("Audit terminé : aucune écriture sur le NAS.")
            finally:
                if sid:
                    client.logout(sid)
        self.background(work)

    def export(self):
        if not self.report:
            messagebox.showinfo("Rapport", "Lance d'abord un audit.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json",
                  initialfile="synology_diagnostic.json", filetypes=[("JSON", "*.json")])
        if path:
            Path(path).write_text(json.dumps(self.report, indent=2, ensure_ascii=False), encoding="utf-8")
            self.log("Rapport anonymisé enregistré.")

    def test_ollama(self):
        def work():
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=8) as r:
                data = json.load(r)
            names = [x.get("name", "") for x in data.get("models", [])]
            self.log("Modèles Ollama : " + ", ".join(names))
        self.background(work)

    def analyze_qwen(self):
        if self.report is None:
            messagebox.showinfo("Qwen", "Lance un audit avant l'analyse.")
            return
        def work():
            prompt = ("Analyse ce diagnostic Synology. Réponds en français, brièvement, "
                      "en distinguant observations, incertitudes et recommandations. "
                      "Ne suggère aucune suppression, aucun formatage ni modification RAID.\n"
                      + json.dumps(self.report, ensure_ascii=False))
            data = json.dumps({"model": "qwen2.5-coder:7b", "prompt": prompt,
                    "stream": False, "options": {"num_predict": 220}}).encode("utf-8")
            req = urllib.request.Request("http://127.0.0.1:11434/api/generate",
                   data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=150) as r:
                output = json.load(r)
            self.log("Analyse Qwen (conseil seulement, sans accès DSM) :\n"
                     + str(output.get("response", "Réponse vide")))
        self.background(work)

    def show_update_history(self):
        """Affiche directement le résultat du remplaçant externe sur Windows."""
        path = CONFIG_DIR / "update_error.txt"
        data = update_log_tail(path)
        if "FAILURE:" in data or "Échec" in data:
            self.log("Dernière mise à jour : erreur détectée (voir fenêtre).")
        else:
            self.log("Journal de mise à jour consulté.")
        messagebox.showinfo("Journal des mises à jour", data, parent=self.root)

    def check_updates(self):
        def work():
            if getattr(sys, "frozen", False):
                request = urllib.request.Request(RELEASES_API,
                    headers={"User-Agent": "SynologyMediaManager/" + VERSION,
                             "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(request, timeout=20) as response:
                    release = json.load(response)
                version = release_version(release)
                if version_tuple(version) <= version_tuple(VERSION):
                    self.log("Application EXE à jour : " + VERSION)
                    return
                self.events.put(("update", (version, "exe")))
            else:
                req = urllib.request.Request(RAW_BASE + "update.json",
                        headers={"User-Agent": "SynologyMediaManager/" + VERSION})
                with urllib.request.urlopen(req, timeout=15) as response:
                    raw = response.read(10000)
                version, digest = check_manifest(json.loads(raw.decode("utf-8")))
                if version_tuple(version) <= version_tuple(VERSION):
                    self.log("Application Python à jour : " + VERSION)
                    return
                self.events.put(("update", (version, digest)))
        self.background(work)

    def offer_update(self, info):
        version, digest = info
        is_exe = getattr(sys, "frozen", False)
        if not messagebox.askyesno("Mise à jour disponible",
              f"Installer Synology Media Manager {version} depuis GitHub ?\n"
              "L'ancien programme sera sauvegardé avant remplacement."):
            return

        def work():
            self.log("Téléchargement et installation demandés pour la version " + version + ".")
            if is_exe:
                target = Path(sys.executable).resolve()
                if target.suffix.lower() != ".exe" or not target.is_file():
                    raise RuntimeError("L'application lancée n'est pas un exécutable Windows valide.")
                self.log("Lecture du SHA-256 de la release GitHub…")
                _, checksum_data, _ = fetch_release_file(version, "SHA256SUMS.txt", 4096)
                expected = release_checksum(checksum_data.decode("ascii"))
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                # Write stage in writable LocalAppData, even if EXE lives in Downloads.
                staged = CONFIG_DIR / "SynologyMediaManager.update.exe"
                try:
                    self.log("Téléchargement EXE " + version + "…")
                    actual, _, size = fetch_release_file(version, EXE_NAME, 150_000_000, sink=staged)
                    if size < 100_000 or actual != expected:
                        raise RuntimeError("Téléchargement refusé : taille ou SHA-256 incorrect.")
                    self.log(f"SHA-256 vérifié ({size} octets).")
                    script_file = CONFIG_DIR / "apply_update.ps1"
                    script_file.write_text(EXE_UPDATER, encoding="utf-8-sig")
                    log_file = CONFIG_DIR / "update_error.txt"
                    log_file.unlink(missing_ok=True)
                    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                    env = os.environ.copy()
                    # A fresh PyInstaller onefile instance must not inherit stale extraction state.
                    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
                    for key in list(env):
                        if key.startswith("_PYI_"):
                            del env[key]
                    proc = subprocess.Popen(
                        ["powershell.exe", "-NoProfile", "-NonInteractive",
                         "-ExecutionPolicy", "Bypass", "-File", str(script_file),
                         "-Target", str(target), "-Staged", str(staged),
                         "-LogPath", str(log_file), "-ParentPid", str(os.getpid())],
                        cwd=str(CONFIG_DIR), creationflags=flags, env=env)
                    self.log("Remplacement lancé (PID " + str(proc.pid) + ").")
                    self.log("Journal local : " + str(log_file))
                    self.log("Fermeture de l'application pour finaliser la mise à jour…")
                    self.events.put(("restart", None))
                except Exception:
                    staged.unlink(missing_ok=True)
                    raise
            else:
                target = Path(sys.argv[0]).resolve()
                if target.name != APP_NAME or not target.is_file() or target.is_symlink():
                    raise RuntimeError("Lance le fichier nommé " + APP_NAME)
                with urllib.request.urlopen(RAW_BASE + APP_NAME, timeout=25) as response:
                    content = response.read(1_000_001)
                if not content or len(content) > 1_000_000 or sha256(content) != digest:
                    raise RuntimeError("Téléchargement invalide : l'empreinte SHA-256 ne correspond pas.")
                staged = target.with_name(target.name + ".next")
                staged.write_bytes(content)
                logpath = CONFIG_DIR / "update_error.txt"
                subprocess.Popen([sys.executable, "-c", UPDATER,
                                  str(target), str(staged), sys.executable, str(logpath)],
                                 cwd=str(target.parent))
                self.log("Mise à jour validée. Fermeture de l'application avant remplacement…")
                self.events.put(("restart", None))
        self.background(work)


if __name__ == "__main__":
    main = tk.Tk()
    Application(main)
    main.mainloop()
