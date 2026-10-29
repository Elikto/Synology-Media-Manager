# -*- coding: utf-8 -*-
"""Synology Media Manager - application locale Windows, sans dépendance externe."""
from __future__ import annotations

import datetime
import hashlib
import http.client
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
from tkinter import ttk, messagebox, filedialog
import urllib.parse
import urllib.request
import webbrowser

VERSION = "0.3.0"
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

    def request(self, api, version, method, params=None, sid=None):
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
            conn.request("POST", "/webapi/entry.cgi", payload, {
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

    def login(self, username, password):
        data = self.request("SYNO.API.Auth", 6, "login", {
            "account": username, "passwd": password, "session": "Core", "format": "sid",
        })
        sid = data.get("sid")
        if not sid:
            raise RuntimeError("Session absente (authentification supplémentaire possible).")
        return sid

    def logout(self, sid):
        try:
            self.request("SYNO.API.Auth", 6, "logout", {"session": "Core"}, sid=sid)
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
    [Parameter(Mandatory=$true)][string]$LogPath
)
$ErrorActionPreference = 'Stop'
for ($i=0; $i -lt 120; $i++) {
    try {
        if (-not (Test-Path -LiteralPath $Staged)) { throw 'Mise à jour introuvable' }
        Copy-Item -LiteralPath $Target -Destination ($Target + '.backup') -Force
        Move-Item -LiteralPath $Staged -Destination $Target -Force
        Start-Process -FilePath $Target -WorkingDirectory (Split-Path $Target -Parent)
        exit 0
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
"Échec du remplacement du programme. Ancienne version conservée." |
    Set-Content -LiteralPath $LogPath -Encoding UTF8
exit 1
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
        self.cfg = load_config()
        self.host = tk.StringVar(value=self.cfg["host"])
        self.port = tk.StringVar(value=str(self.cfg["port"]))
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.status = tk.StringVar(value="Prêt — lecture seule")
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
        ttk.Label(media_row, text="Après création du partage « Media » dans DSM.",
                  foreground="#526577").pack(side="left", padx=9)
        ttk.Label(outer, textvariable=self.status).pack(anchor="w")
        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(fill="x", pady=(4, 8))
        self.logarea = tk.Text(outer, font=("Consolas", 10), wrap="word", height=23)
        self.logarea.pack(fill="both", expand=True)
        self.logarea.configure(state="disabled")
        ttk.Label(outer, text="Lecture seule : aucune installation, suppression, création de volume ni modification RAID. "
                  "Surveiller le disque 1 (ancien compteur UNC=129).",
                  foreground="#8b5b15", wraplength=860).pack(anchor="w", pady=(8, 0))
        self.log("Version " + VERSION + " prête. Les paramètres locaux ne seront jamais publiés sur GitHub.")
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
                    self.offer_update(value)
                elif kind == "media_missing":
                    if messagebox.askyesno("Partager Media absent",
                        "Le partage « Media » n'existe pas encore.\n\n"
                        "Crée-le une seule fois dans DSM : Panneau de configuration > "
                        "Dossier partagé > Créer, sur volume1.\n\n"
                        "Ouvrir DSM maintenant ?"):
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
                files = file_station_entries(client, sid)
                missing = missing_media_folders(files)
                if not missing:
                    self.log("Tous les dossiers multimédias existent déjà. Aucune écriture.")
                    return
                self.log("Création limitée aux dossiers absents : " + ", ".join(missing))
                for name in missing:
                    create_media_subfolder(client, sid, name)
                    self.log("Dossier créé : /Media/" + name)
                self.log("Préparation terminée. Aucun fichier supprimé ou déplacé.")
            finally:
                if sid:
                    client.logout(sid)

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
            if is_exe:
                target = Path(sys.executable).resolve()
                if target.name.lower() != EXE_NAME.lower() or not target.is_file():
                    raise RuntimeError("Renomme le programme en " + EXE_NAME + " avant sa mise à jour.")
                self.log("Lecture de l'empreinte SHA-256 publiée sur GitHub Releases…")
                _, checksum_data, _ = fetch_release_file(version, "SHA256SUMS.txt", 4096)
                expected = release_checksum(checksum_data.decode("ascii"))
                staged = target.with_name(target.name + ".next")
                try:
                    self.log("Téléchargement de la nouvelle version EXE…")
                    actual, _, size = fetch_release_file(version, EXE_NAME, 150_000_000, sink=staged)
                    if size < 100_000 or actual != expected:
                        raise RuntimeError("Téléchargement refusé : taille ou SHA-256 incorrect.")
                    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                    script_file = CONFIG_DIR / "apply_update.ps1"
                    script_file.write_text(EXE_UPDATER, encoding="utf-8-sig")
                    log_file = CONFIG_DIR / "update_error.txt"
                    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                    subprocess.Popen(
                        ["powershell.exe", "-NoProfile", "-NonInteractive",
                         "-ExecutionPolicy", "Bypass", "-File", str(script_file),
                         "-Target", str(target), "-Staged", str(staged),
                         "-LogPath", str(log_file)],
                        cwd=str(CONFIG_DIR), creationflags=flags)
                    self.log("Exécutable vérifié. Fermeture pour mise à jour automatique.")
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
