import os, json, requests, configparser, sys, traceback

from workshopdl.config import INSTALL_LOCAL_DIR, install_repo_url



def install_fetch_recipe(game_id: str, force: bool = False,
                         cfg: configparser.ConfigParser = None) -> dict | None:
    os.makedirs(INSTALL_LOCAL_DIR, exist_ok=True)
    local = os.path.join(INSTALL_LOCAL_DIR, f"{game_id}.json")

    if os.path.exists(local) and not force:
        with open(local, encoding="utf-8") as f:
            return json.load(f)

    raw_base, _ = install_repo_url(cfg)
    url = f"{raw_base}/{game_id}.json"
    
    r = requests.get(url, timeout=10)
    if r.status_code == 404:
        return None
        
    r.raise_for_status()
    data = r.json()
    
    with open(local, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    return data
