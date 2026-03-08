# WorkshopDL — Python Edition

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)
![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green)
![Platform](https://img.shields.io/badge/Plattform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![License](https://img.shields.io/badge/Lizenz-MIT-orange)

**Ein plattformübergreifender Steam-Workshop-Mod-Downloader mit übersichtlicher Benutzeroberfläche.**  
Inspiriert vom originalen [WorkshopDL](https://github.com/imwaitingnow/WorkshopDL) von imwaitingnow.

</div>

---

## 🌐 README in anderen Sprachen

| Sprache | Datei |
|---|---|
| 🇬🇧 English | [README.md](README.md) |
| 🇷🇺 Русский | [README_RU.md](README_RU.md) |
| 🇩🇪 Deutsch | [README_DE.md](README_DE.md) ← Sie sind hier |
| 🇨🇳 中文 | [README_ZH.md](README_ZH.md) |

> Möchten Sie eine neue Sprache hinzufügen? Siehe Abschnitt [Übersetzungen](#-übersetzungen).

---

## ✨ Funktionen

- **⬇ Mods herunterladen** via SteamCMD — einzelne Mods oder ganze Listen
- **📦 Steam-Sammlungen importieren** — URL einfügen und alle Mods werden automatisch hinzugefügt
- **🔍 Automatische Game-ID-Erkennung** — einfach Mod-ID einfügen, Game-ID wird gefunden
- **🔄 Update-Prüfung** — lokalen Mod-Ordner scannen und veraltete Mods anzeigen
- **⏸ Pause & Fortsetzen** — Download stoppen und beim nächsten Start fortsetzen
- **🔘 Mods aktivieren / deaktivieren** — ohne Löschen umschalten (Ordner wird in `.disabled` umbenannt)
- **📋 Spielverlauf** — merkt sich alle Spiele, für die Mods heruntergeladen wurden
- **📁 Ordner mit einem Klick öffnen** — direkt aus der Tabelle
- **💾 Größenspalte** — zeigt den Speicherplatz jedes Mods
- **🌐 Lokalisierung** — vollständige Übersetzung der Benutzeroberfläche via JSON-Dateien
- **🖥 Plattformübergreifend** — Windows, Linux, macOS

---

## 📦 Voraussetzungen

```
Python 3.8+
PyQt5
requests
```

Abhängigkeiten installieren:
```bash
pip install PyQt5 requests
```

---

## 🚀 Schnellstart

1. Repository klonen oder herunterladen
2. Abhängigkeiten installieren (siehe oben)
3. Starten:
   ```bash
   python workshopdl.py
   ```
4. **Einstellungen** öffnen → **⬇ SteamCMD automatisch herunterladen** klicken
5. Im Tab **Herunterladen** eine Mod-ID eingeben — Game-ID wird automatisch erkannt
6. **⬇ Herunterladen** klicken

---

## 🗂 Projektstruktur

```
WorkshopDL/
├── workshopdl.py        # Hauptanwendung
├── lang_en.json         # Englische Lokalisierung (Standard)
├── lang_ru.json         # Russische Lokalisierung
├── lang/                # Community-Sprachdateien (optional)
│   ├── lang_de.json
│   └── lang_zh.json
├── Modules/             # Laufzeitdaten (wird automatisch erstellt)
│   ├── queue.json       # Pause/Fortsetzen-Warteschlange
│   ├── history.json     # Spielverlauf
│   └── mod_paths.json   # Gespeicherte Mod-Ordnerpfade
├── steamcmd/            # SteamCMD-Installation (wird automatisch erstellt)
└── WorkshopDL.ini       # Benutzereinstellungen
```

---

## 🔄 Update-Prüfung

Der Tab **🔄 Updates prüfen** ermöglicht das Scannen eines lokalen Mod-Ordners
(z. B. `C:\games\SovietRepublic\media_soviet\workshop_wip`).

Der Ordner muss numerische Unterordner enthalten — einen pro Mod:
```
workshop_wip/
├── 1797996358/
├── 1807300910/
└── 2031421793.disabled   ← deaktivierter Mod
```

WorkshopDL vergleicht das lokale Änderungsdatum mit dem `time_updated`-Feld
der Steam-API und markiert jeden Mod:

| Symbol | Bedeutung |
|---|---|
| 🔴 | Veraltet — neuere Version auf dem Server verfügbar |
| 🟢 | Aktuell |
| 🔘 | Deaktiviert (Ordner hat Suffix `.disabled`) |
| ⚪ | Unbekannt — Steam-API hat keine Daten zurückgegeben |

---

## 🔘 Mods aktivieren / deaktivieren

Auf die Schaltfläche **⏸ / ▶** in der Tabelle klicken, um einen Mod umzuschalten.  
Das Programm benennt den Ordner einfach um:

```
1797996358          →   1797996358.disabled    (deaktiviert)
1797996358.disabled →   1797996358             (aktiviert)
```

Es werden keine Dateien gelöscht.

---

## 🌐 Übersetzungen

Alle UI-Texte befinden sich in einer einzigen JSON-Datei. So erstellen Sie eine neue Übersetzung:

1. `lang_en.json` kopieren und umbenennen, z. B. in `lang_fr.json`
2. Die **Werte** (rechte Seite jeder Zeile) übersetzen — Schlüssel nicht ändern
3. In **Einstellungen → Sprache** zur Datei navigieren und **✅ Übernehmen** klicken

### Übersetzung beitragen

Um Ihre Übersetzung mit allen Nutzern zu teilen:
- `lang_XX.json` in den Ordner `lang/` dieses Repositories legen
- Pull Request öffnen

---

## ⚙ Einstellungen

| Einstellung | Beschreibung |
|---|---|
| Anonymer Modus | Download ohne Steam-Konto (die meisten Mods unterstützen dies) |
| Steam Login / Passwort | Nur erforderlich wenn anonymer Modus deaktiviert ist |
| SteamCMD-Pfad | Pfad zur `steamcmd`-Binärdatei — oder automatisch herunterladen |
| Sprache | Pfad zur Lokalisierungs-`.json`-Datei |
| Mod-Ordner | Standardordner für die Update-Prüfung |

---

## 🛠 SteamCMD

WorkshopDL verwendet [SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD)
zum Herunterladen von Mods. Manuelle Installation ist nicht nötig —
gehen Sie zu **Einstellungen** und klicken Sie **⬇ SteamCMD automatisch herunterladen**.

| Plattform | Binärdatei | Archiv |
|---|---|---|
| Windows | `steamcmd.exe` | `.zip` |
| Linux | `steamcmd.sh` | `.tar.gz` |
| macOS | `steamcmd` | `.tar.gz` |

---

## 📄 Lizenz

MIT — machen Sie damit was Sie möchten, Nennung des Autors ist willkommen.

---

<div align="center">
Erstellt mit ☕ und PyQt5
</div>
