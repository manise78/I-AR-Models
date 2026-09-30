"""Remove root GLB files 30 days after their latest publication. No third-party dependencies."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

DAYS = 30
BRANCH = "main"


def is_model(entry):
    path = entry["path"]
    return (entry.get("type") == "blob" and entry.get("mode") == "100644"
            and "/" not in path and "\\" not in path and path.lower().endswith(".glb"))


def metadata_path(name):
    return ".ar-metadata/" + name + ".json"


class GitHub:
    def __init__(self, repository, token):
        if not token:
            raise RuntimeError("Configura il secret AR_CLEANUP_TOKEN nel repository.")
        if repository != "manise78/I-AR-Models":
            raise RuntimeError("Repository diverso da quello previsto; nessuna modifica.")
        self.base = "https://api.github.com/repos/" + repository + "/"
        self.token = token

    def call(self, method, route, body=None):
        request = Request(self.base + route,
                          data=None if body is None else json.dumps(body).encode("utf-8"),
                          method=method, headers={
                              "Authorization": "Bearer " + self.token,
                              "User-Agent": "InventorToAR-Cleanup",
                              "Accept": "application/vnd.github+json",
                              "Content-Type": "application/json",
                              "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with urlopen(request, timeout=90) as response:
                return json.load(response)
        except HTTPError as exc:
            # Never output headers or request body (credential).
            raise RuntimeError("GitHub HTTP " + str(exc.code) +
                               ": operazione interrotta. Verificare permessi, conflitti e stato del repository.") from None


def latest_date(api, path, head):
    commits = api.call("GET", "commits?" + urlencode({"sha": head, "path": path, "per_page": 1}))
    if not commits:
        raise RuntimeError("Cronologia non disponibile per un modello; pulizia interrotta.")
    value = commits[0]["commit"]["committer"]["date"]
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise RuntimeError("Data GitHub senza fuso orario; pulizia interrotta.")
    return result


def cleanup(api, now, dry_run=True):
    head = api.call("GET", "git/ref/heads/" + BRANCH)["object"]["sha"]
    tree_sha = api.call("GET", "git/commits/" + head)["tree"]["sha"]
    tree = api.call("GET", "git/trees/" + tree_sha + "?recursive=1")
    if tree.get("truncated", True):
        raise RuntimeError("Elenco incompleto: nessuna eliminazione.")
    entries = {entry["path"]: entry for entry in tree["tree"]}
    expired = []
    cutoff = now - timedelta(days=DAYS)
    for name, entry in entries.items():
        if not is_model(entry):
            continue
        modified = latest_date(api, name, head)
        metadata = entries.get(metadata_path(name))
        if metadata:
            if metadata.get("type") != "blob" or metadata.get("mode") != "100644":
                raise RuntimeError("Metadati non regolari; nessuna eliminazione.")
            # Server-side commit date: no dependency on the clock of the uploading PC.
            modified = max(modified, latest_date(api, metadata_path(name), head))
        if modified <= cutoff:
            expired.append(name)
    print("Modalità:", "SIMULAZIONE" if dry_run else "ELIMINAZIONE")
    print("Modelli scaduti:", json.dumps(expired, ensure_ascii=True))
    if dry_run or not expired:
        return expired
    # Reject any repository change, including a fresh upload of identical bytes.
    if api.call("GET", "git/ref/heads/" + BRANCH)["object"]["sha"] != head:
        raise RuntimeError("Repository cambiato durante il controllo. Nessun file eliminato; riprovare.")
    deletions = []
    for name in expired:
        deletions.append({"path": name, "mode": "100644", "type": "blob", "sha": None})
        metadata = metadata_path(name)
        if metadata in entries:
            deletions.append({"path": metadata, "mode": "100644", "type": "blob", "sha": None})
    new_tree = api.call("POST", "git/trees", {"base_tree": tree_sha, "tree": deletions})
    commit = api.call("POST", "git/commits", {
        "message": "Pulizia AR: modelli scaduti dopo 30 giorni",
        "tree": new_tree["sha"], "parents": [head]})
    # Fast-forward only. Concurrent updates are never overwritten.
    api.call("PATCH", "git/refs/heads/" + BRANCH, {"sha": commit["sha"], "force": False})
    print("Eliminazione completata:", len(expired))
    return expired


if __name__ == "__main__":
    try:
        api = GitHub(os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("AR_CLEANUP_TOKEN", ""))
        cleanup(api, datetime.now(timezone.utc), os.environ.get("AR_DRY_RUN", "true").lower() != "false")
    except Exception as exc:
        print("Pulizia non completata:", str(exc), file=sys.stderr)
        sys.exit(1)
