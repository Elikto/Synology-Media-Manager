"""Connecteurs locaux optionnels Kodi et Servarr.

Exécution uniquement depuis Windows et vers une adresse privée / Tailscale.
Aucun identifiant conservé sur disque, aucune installation sur le DS218j.
"""
import base64
import ipaddress
import json
import re
import urllib.error
import urllib.request


SERVICE_PORTS = {"Prowlarr": 9696, "Sonarr": 8989, "Radarr": 7878,
                 "Kodi": 8080}
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


def downloadstation_client_payload(schemas, nas_host, nas_port, username, password,
                                   category):
    """Prépare uniquement le modèle TorrentDownloadStation fourni par l'API *arr."""
    from copy import deepcopy
    if category not in ("sonarr", "radarr"):
        raise ValueError("Catégorie non autorisée.")
    nas_host = local_host(nas_host)
    nas_port = int(nas_port)
    if not 1 <= nas_port <= 65535 or not username or not password:
        raise ValueError("Connexion Download Station incomplète.")
    if not isinstance(schemas, list):
        raise RuntimeError("Schéma *arr invalide.")
    template = next((item for item in schemas if isinstance(item, dict)
                     and item.get("implementation") == "TorrentDownloadStation"), None)
    if template is None:
        raise RuntimeError("Le client TorrentDownloadStation n'est pas pris en charge par cette version.")
    payload = deepcopy(template)
    fields = payload.get("fields")
    if not isinstance(fields, list):
        raise RuntimeError("Schéma Download Station invalide.")
    values = {
        "host": nas_host, "port": nas_port, "useSsl": nas_port == 5001,
        "username": username, "password": password, "tvCategory": category,
        "tvDirectory": "",
    }
    names = set()
    for field in fields:
        if not isinstance(field, dict):
            raise RuntimeError("Champ de configuration invalide.")
        name = str(field.get("name") or "")
        if name in values:
            field["value"] = values[name]
            names.add(name)
    required = {"host", "port", "useSsl", "username", "password", "tvCategory"}
    if not required.issubset(names):
        raise RuntimeError("Schéma Download Station incompatible : " +
                           ", ".join(sorted(required - names)))
    payload["name"] = "Synology Download Station (" + category + ")"
    payload["enable"] = True
    # Les torrents doivent rester en partage : ne pas autoriser une suppression
    # automatique des téléchargements depuis Sonarr ou Radarr.
    if "removeCompletedDownloads" in payload:
        payload["removeCompletedDownloads"] = False
    return payload


def downloadstation_clients_for(name, host, port, key, opener=None):
    """Inspecte en lecture seule les clients configurés dans Sonarr/Radarr."""
    if name not in ("Sonarr", "Radarr"):
        raise ValueError("Application non prise en charge.")
    api, _version = servarr_version(name, host, port, key, opener=opener)
    base = "/api/" + api + "/downloadclient"
    clients = api_json(host, port, base, key, opener=opener)
    if not isinstance(clients, list):
        raise RuntimeError("Liste des clients torrent invalide.")
    return api, clients


def link_downloadstation_to_arr(name, arr_host, arr_port, arr_key,
                                nas_host, nas_port, nas_user, nas_password,
                                opener=None):
    """Test et ajout idempotent, sans modifier ou supprimer les clients existants.

    Les identifiants du NAS sont enregistrés par Sonarr/Radarr si l'ajout réussit.
    Ne jamais les journaliser. L'import nécessite un partage SMB monté sur l'hôte.
    """
    if name not in ("Sonarr", "Radarr"):
        raise ValueError("Seuls Sonarr et Radarr peuvent être configurés.")
    if not arr_key:
        raise ValueError("Clé API *arr manquante.")
    api, clients = downloadstation_clients_for(name, arr_host, arr_port, arr_key,
                                                opener=opener)
    target_host = local_host(nas_host)
    target_port = int(nas_port)
    category = name.lower()
    for item in clients:
        if not isinstance(item, dict):
            continue
        if item.get("implementation") != "TorrentDownloadStation":
            continue
        fields = item.get("fields") or []
        existing = {str(field.get("name")): field.get("value")
                    for field in fields if isinstance(field, dict)}
        try:
            same = (str(existing.get("host") or "").lower() == target_host and
                    int(existing.get("port")) == target_port and
                    str(existing.get("tvCategory") or "") == category)
        except (TypeError, ValueError):
            same = False
        if same:
            return "déjà configuré, aucune modification"
    base = "/api/" + api + "/downloadclient"
    schema = api_json(arr_host, arr_port, base + "/schema", arr_key,
                      opener=opener)
    payload = downloadstation_client_payload(schema, target_host, target_port,
                                             nas_user, nas_password, category)
    # Les nouvelles versions permettent de tester le client avant l'écriture.
    check = api_json(arr_host, arr_port, base + "/test", arr_key,
                     method="POST", payload=payload, opener=opener)
    if check not in ([], {}):
        raise RuntimeError(name + " refuse la liaison Download Station : test non validé.")
    result = api_json(arr_host, arr_port, base, arr_key,
                      method="POST", payload=payload, opener=opener)
    if not isinstance(result, dict) or not isinstance(result.get("id"), int):
        raise RuntimeError(name + " : création non confirmée.")
    # Relire l'état confirmé par l'application, sans écraser aucun client.
    _, updated = downloadstation_clients_for(name, arr_host, arr_port, arr_key,
                                              opener=opener)
    if not any(isinstance(row, dict) and row.get("id") == result["id"]
               for row in updated):
        raise RuntimeError(name + " : client non retrouvé après création.")
    return "client Download Station créé, test réussi"


def kodi_media_paths(host):
    """Deux sources SMB accessibles depuis Kodi, sans configuration du NAS."""
    safe = local_host(host)
    if ":" in safe:
        safe = "[" + safe + "]"
    base = "smb://" + safe + "/Media/"
    return {"Films": base + "Films/", "Series": base + "Series/"}


def kodi_scan(host, port, username="", password="", opener=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.Scan",
               "params": {"showdialogs": False}}
    raw = local_request(host, port, "/jsonrpc", method="POST", payload=payload,
                        user=username, password=password, opener=opener)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or data.get("error") or data.get("id") != 1:
        raise RuntimeError("Kodi a refusé le scan vidéo.")
    return True


