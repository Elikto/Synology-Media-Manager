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

VERSION = "0.1.0"
REPOSITORY = "Elikto/Synology-Media-Manager"
RAW_BASE = "https://raw.githubusercontent.com/" + REPOSITORY + "/main/"
APP_NAME = "SynologyMediaManager.pyw"
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
            req = urllib.request.Request(RAW_BASE + "update.json",
                     headers={"User-Agent": "SynologyMediaManager/" + VERSION})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read(10000)
            version, digest = check_manifest(json.loads(raw.decode("utf-8")))
            if version_tuple(version) <= version_tuple(VERSION):
                self.log("Application à jour : " + VERSION)
                return
            self.events.put(("update", (version, digest)))
        self.background(work)

    def offer_update(self, info):
        version, digest = info
        if not messagebox.askyesno("Mise à jour disponible",
              f"Installer Synology Media Manager {version} depuis GitHub ?\n"
              "L'ancien programme sera sauvegardé avant remplacement."):
            return
        def work():
            target = Path(sys.argv[0]).resolve()
            if target.name != APP_NAME or not target.is_file() or target.is_symlink():
                raise RuntimeError("Pour les mises à jour, lance le fichier téléchargé nommé " + APP_NAME)
            with urllib.request.urlopen(RAW_BASE + APP_NAME, timeout=25) as response:
                content = response.read(1_000_001)
            if not content or len(content) > 1_000_000 or sha256(content) != digest:
                raise RuntimeError("Téléchargement invalide : l'empreinte SHA-256 ne correspond pas.")
            staged = target.with_name(target.name + ".next")
            staged.write_bytes(content)
            # L'outil auxiliaire attend la fermeture de cette interface pour échanger le fichier.
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
