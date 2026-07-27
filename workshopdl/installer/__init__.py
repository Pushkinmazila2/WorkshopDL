import os, json, requests, configparser, sys, traceback

from workshopdl.config import INSTALL_LOCAL_DIR, install_repo_url



def install_fetch_recipe(game_id: str, force: bool = False,
                         cfg: configparser.ConfigParser = None) -> dict | None:
    """Fetch a mod-install recipe (JSON) for the given game_id.

    Looks in the local cache first; falls back to a remote fetch.
    Returns ``None`` when no recipe exists (404) or on any error,
    so callers never receive a corrupt/empty value.
    """
    os.makedirs(INSTALL_LOCAL_DIR, exist_ok=True)
    local = os.path.join(INSTALL_LOCAL_DIR, f"{game_id}.json")

    # ── Try local cache ──────────────────────────────────────────────
    if os.path.exists(local) and not force:
        try:
            with open(local, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            # Corrupt / wrong-type file — fall through to re-fetch
            sys.stderr.write(
                f"[install_fetch_recipe] WARNING: {local} is not a valid JSON dict, re-fetching\n"
            )
        except (json.JSONDecodeError, OSError) as e:
            # Empty or corrupt cache file — fall through to re-fetch
            sys.stderr.write(
                f"[install_fetch_recipe] WARNING: failed to read {local}: {e}, re-fetching\n"
            )

    # ── Fetch from remote ────────────────────────────────────────────
    raw_base, _ = install_repo_url(cfg)
    url = f"{raw_base}/{game_id}.json"

    try:
        r = requests.get(url, timeout=10)
    except requests.RequestException as e:
        sys.stderr.write(
            f"[install_fetch_recipe] ERROR: network failure for {game_id}: {e}\n"
        )
        return None

    if r.status_code == 404:
        return None

    r.raise_for_status()

    try:
        data = r.json()
    except ValueError:
        sys.stderr.write(
            f"[install_fetch_recipe] ERROR: invalid JSON in response for {game_id}\n"
        )
        return None

    if not isinstance(data, dict):
        sys.stderr.write(
            f"[install_fetch_recipe] ERROR: recipe for {game_id} is not a JSON object\n"
        )
        return None

    with open(local, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data


