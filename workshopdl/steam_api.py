"""
Steam API функции.
"""

import requests

def fetch_game_id_for_mod(workshop_id):
    try:
        r = requests.post(
            "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
            data={"itemcount": "1", "publishedfileids[0]": workshop_id}, timeout=10
        )
        d = r.json()["response"]["publishedfiledetails"][0]
        app_id = str(d.get("consumer_app_id", ""))
        name = ""
        if app_id:
            try:
                r2 = requests.get(
                    f"https://store.steampowered.com/api/appdetails?appids={app_id}&filters=basic",
                    timeout=8
                )
                name = r2.json().get(app_id, {}).get("data", {}).get("name", "")
            except Exception:
                pass
        return app_id, name
    except Exception:
        return "", ""

def fetch_collection(collection_id):
    try:
        r = requests.post(
            "https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/",
            data={"collectioncount": "1", "publishedfileids[0]": collection_id}, timeout=10
        )
        children = r.json()["response"]["collectiondetails"][0].get("children", [])
        return [str(c["publishedfileid"]) for c in children]
    except Exception:
        return []

def fetch_mod_details_batch(mod_ids: list) -> dict:
    """Возвращает {mod_id: {title, time_updated, children: [mod_id, ...]}}"""
    result = {}
    for i in range(0, len(mod_ids), 100):
        chunk = mod_ids[i:i+100]
        data = {"itemcount": str(len(chunk))}
        for j, mid in enumerate(chunk):
            data[f"publishedfileids[{j}]"] = mid
        try:
            r = requests.post(
                "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                data=data, timeout=15
            )
            for item in r.json()["response"]["publishedfiledetails"]:
                fid = str(item.get("publishedfileid", ""))
                children = [
                    str(c["publishedfileid"])
                    for c in item.get("children", [])
                    if c.get("file_type", 0) == 0
                ]
                result[fid] = {
                    "title":        item.get("title", fid),
                    "time_updated": int(item.get("time_updated", 0)),
                    "children":     children,
                }
        except Exception:
            pass
    return result

def fetch_dependencies(mod_ids: list, depth: int = 3) -> dict:
    """
    Рекурсивно собирает все зависимости для списка модов.
    Возвращает {dep_id: title} — только зависимости, не сами моды.
    depth — максимальная глубина рекурсии (защита от циклов).
    """
    if depth == 0 or not mod_ids:
        return {}
    details = fetch_mod_details_batch(mod_ids)
    all_deps = {}
    next_level = []
    for mid, info in details.items():
        for child_id in info.get("children", []):
            if child_id not in all_deps:
                child_info = details.get(child_id)
                title = child_info["title"] if child_info else child_id
                all_deps[child_id] = title
                next_level.append(child_id)
    next_level = [x for x in next_level if x not in details]
    if next_level:
        deeper = fetch_dependencies(next_level, depth - 1)
        for k, v in deeper.items():
            all_deps.setdefault(k, v)
    return all_deps