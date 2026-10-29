"""Connecteurs locaux optionnels Kodi, Plex et Servarr.

Exécution uniquement depuis Windows et vers une adresse privée / Tailscale.
Aucun identifiant conservé sur disque, aucune installation sur le DS218j.
"""
import base64
import ipaddress
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


SERVICE_PORTS = {"Prowlarr": 9696, "Sonarr": 8989, "Radarr": 7878,
                 "Kodi": 8080, "Plex": 32400}
APP_API = {"Prowlarr": ("v1",), "Sonarr": ("v5", "v3"), "Radarr": ("v3",)}
MAX_RESPONSE = 1_000_000


def local_host(host):
    value = str(host).strip().lower()
    if not value or len(value) > 253 or not re.fullmatch(r"[a-z0-9.:-]+", value):
        raise ValueError("Adresse locale invalide.")
    if value in ("localhost",):
        return value
    try:
        address = ipaddress.ip_address(value)
        if address.is_private or address.is_loopback or address in ipaddress.ip_network("100.64.0.0/10"):
            return value
        raise ValueError("Adresse publique refusée : utiliser Tailscale ou le réseau local.")
    except ValueError as exc:
        if "refusée" in str(exc):
            raise
    if (value.endswith((".local", ".ts.net")) or
            ("." not in value and re.fullmatch(r"[a-z0-9-]+", value))):
        return value
    raise ValueError("Utiliser une IP locale, une adresse Tailscale ou un nom .local.")


def service_address(host, port):
    host = local_host(host)
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("Port invalide.")
    if ":" in host:
        host = "[" + host + "]"
    return "http://" + host + ":" + str(port)


class BlockRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError("Redirection HTTP interdite pour une API locale.")


def local_request(host, port, path, key="", method="GET", payload=None,
                  user="", password="", opener=None):
    if not path.startswith("/") or "//" in path or "?" in path or ".." in path:
        raise ValueError("Chemin API invalide.")
    url = service_address(host, port) + path
    headers = {"Accept": "application/json", "User-Agent": "SynologyMediaManager"}
    if key:
        headers["X-Api-Key"] = key
    if user:
        auth = base64.b64encode((user + ":" + password).encode("utf-8")).decode("ascii")
        headers["Authorization"] = "Basic " + auth
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    else:
        body = None
    request = urllib.request.Request(url, headers=headers, data=body, method=method)
    handler = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                    BlockRedirect())
    with handler.open(request, timeout=7) as response:
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise RuntimeError("Réponse du service trop volumineuse.")
        return raw


def api_json(host, port, path, key="", method="GET", payload=None, opener=None):
    raw = local_request(host, port, path, key=key, method=method,
                        payload=payload, opener=opener)
    return json.loads(raw.decode("utf-8")) if raw else {}


def servarr_version(name, host, port, key, opener=None):
    if name not in APP_API or not key:
        raise ValueError("Service ou clé API manquant.")
    last_error = None
    for api in APP_API[name]:
        try:
            data = api_json(host, port, "/api/" + api + "/system/status",
                            key, opener=opener)
            if isinstance(data, dict) and data.get("version"):
                return api, str(data["version"])[:50]
        except (urllib.error.URLError, ValueError, RuntimeError) as error:
            last_error = error
    raise RuntimeError(name + " : API non joignable ou clé incorrecte") from last_error


def prowlarr_application_payload(schema, name, prowlarr_url, service_url, key):
    """Se base sur le schéma réel renvoyé par Prowlarr, plutôt que des champs inventés."""
    matching = next((x for x in schema if isinstance(x, dict) and
                    str(x.get("implementation", "")).lower() == name.lower()), None)
    if matching is None:
        raise RuntimeError("Prowlarr ne propose pas le connecteur " + name)
    fields = matching.get("fields")
    if not isinstance(fields, list):
        raise RuntimeError("Schéma Prowlarr sans champs.")
    required = {"prowlarrUrl": prowlarr_url, "baseUrl": service_url, "apiKey": key}
    seen = set()
    for field in fields:
        if not isinstance(field, dict):
            continue
        field_name = field.get("name")
        if field_name in required:
            field["value"] = required[field_name]
            seen.add(field_name)
    if seen != set(required):
        raise RuntimeError("Schéma Prowlarr incomplet ; liaison annulée.")
    matching["name"] = name + " - Synology Media Manager"
    matching["syncLevel"] = "addOnly"
    return matching


def link_prowlarr(prowlarr, prowlarr_key, targets, opener=None):
    """Crée au plus une liaison par service, ne modifie pas les liaisons existantes."""
    host, port = prowlarr
    installed = api_json(host, port, "/api/v1/applications", prowlarr_key, opener=opener)
    if not isinstance(installed, list):
        raise RuntimeError("Applications Prowlarr : réponse inattendue.")
    templates = api_json(host, port, "/api/v1/applications/schema",
                         prowlarr_key, opener=opener)
    if not isinstance(templates, list):
        raise RuntimeError("Schéma des applications Prowlarr indisponible.")
    existing = {str(row.get("implementation") or "").lower()
                for row in installed if isinstance(row, dict)}
    results = []
    for name, data in targets.items():
        if name not in ("Sonarr", "Radarr"):
            continue
        if name.lower() in existing:
            results.append((name, "déjà relié"))
            continue
        target_host, target_port, target_key = data
        servarr_version(name, target_host, target_port, target_key, opener=opener)
        payload = prowlarr_application_payload(
            templates, name, service_address(host, port),
            service_address(target_host, target_port), target_key)
        created = api_json(host, port, "/api/v1/applications",
                           prowlarr_key, method="POST", payload=payload, opener=opener)
        if not isinstance(created, dict) or not isinstance(created.get("id"), int):
            raise RuntimeError("Prowlarr n'a pas confirmé la création de " + name)
        results.append((name, "liaison créée"))
    return results


def installed_video_servers(packages):
    """Repère les paquets DSM déjà installés, sans les démarrer ni les modifier."""
    if not isinstance(packages, list):
        return set()
    found = set()
    for item in packages:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").lower()
        package_id = str(item.get("id") or item.get("package_id") or "").lower()
        if ("plex media server" in name or package_id in ("plexmediaserver", "plex")):
            found.add("Plex")
        if ("emby server" in name or package_id in ("embyserver", "emby")):
            found.add("Emby")
    return found


def video_server_address(service, host):
    """Uniquement les interfaces locales des deux serveurs déjà installables."""
    paths = {"Plex": (32400, "/web"), "Emby": (8096, "/web/index.html")}
    if service not in paths:
        raise ValueError("Serveur vidéo non autorisé.")
    port, page = paths[service]
    return service_address(host, port) + page


def probe_video_server(service, host, opener=None):
    """Vérification en lecture seule sans authentification ni donnée privée publiée."""
    if service == "Plex":
        raw = local_request(host, 32400, "/identity", opener=opener)
        root = ET.fromstring(raw)
        if root.tag != "MediaContainer":
            raise RuntimeError("Réponse Plex inconnue.")
        version = str(root.attrib.get("version") or "")
    elif service == "Emby":
        # DSM / anciennes versions Emby peuvent exposer /emby ou la racine.
        last_error = None
        for path in ("/emby/System/Info/Public", "/System/Info/Public"):
            try:
                raw = local_request(host, 8096, path, opener=opener)
                info = json.loads(raw.decode("utf-8"))
                if not isinstance(info, dict):
                    raise RuntimeError("Réponse Emby inconnue.")
                version = str(info.get("Version") or "")
                if version:
                    break
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
                last_error = error
        else:
            raise RuntimeError("Emby ne répond pas sur le port 8096.") from last_error
    else:
        raise ValueError("Serveur vidéo non autorisé.")
    # Ne retourne jamais le nom du NAS, son identifiant serveur ou son adresse.
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,60}", version):
        raise RuntimeError("Version du serveur non reconnue.")
    return version


def kodi_scan(host, port, username="", password="", opener=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.Scan",
               "params": {"showdialogs": False}}
    raw = local_request(host, port, "/jsonrpc", method="POST", payload=payload,
                        user=username, password=password, opener=opener)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or data.get("error") or data.get("id") != 1:
        raise RuntimeError("Kodi a refusé le scan vidéo.")
    return True


def plex_scan(host, port, token, opener=None):
    if not token:
        raise ValueError("Jeton Plex manquant.")
    # Plex demande X-Plex-Token, sans l'envoyer dans les URL/logs.
    class PlexOpener:
        def __init__(self, origin):
            self.origin = origin
        def open(self, request, timeout=7):
            request.add_header("X-Plex-Token", token)
            return self.origin.open(request, timeout=timeout)
    base = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                BlockRedirect())
    handler = PlexOpener(base)
    raw = local_request(host, port, "/library/sections", opener=handler)
    try:
        root = ET.fromstring(raw)
        section_ids = [
            item.attrib["key"] for item in root.findall(".//Directory")
            if item.attrib.get("type") in ("movie", "show") and
               re.fullmatch(r"[0-9]+", item.attrib.get("key", ""))
        ]
    except ET.ParseError as error:
        raise RuntimeError("Réponse Plex invalide.") from error
    for item_id in section_ids:
        local_request(host, port, "/library/sections/" + item_id + "/refresh",
                      opener=handler)
    return len(section_ids)
