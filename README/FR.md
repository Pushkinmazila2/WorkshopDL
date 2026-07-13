# WorkshopDL — Python Edition

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)
![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green)
![Platform](https://img.shields.io/badge/Plateformes-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![License](https://img.shields.io/badge/Licence-MIT-orange)

**Un téléchargeur de mods du Steam Workshop multiplateforme avec une interface graphique épurée.**  
Inspired by the original [WorkshopDL](https://github.com/imwaitingnow/WorkshopDL) by imwaitingnow.

</div>

---
## ⬇ Écran de téléchargement
<img src="screen/FR/FR_mods_downloader.png" width="600">

## 🔄 Mod Manager
<img src="screen/FR/FR_mods_manager.png" width="600">
---

## 🌐 Traductions du README

| Langage | Fichier |
|---|---|
| 🇬🇧 English | [README.md](../README.md) ← you are here |
| 🇩🇪 Deutsch | [README_DE.md](../README/README_DE.md) |
| 🇫🇷 Français | [README_FR.md](../README/README_FR.md) |
| 🇷🇺 Русский | [README_RU.md](../README/README_RU.md) |
| 🇨🇳 中文 | [README_ZH.md](../README/README_ZH.md) |

> Tu veut voir ta langue? lis la section [Traductions](#-Traductions) section below.

---

## ✨ Fonctionnalités

- **⬇ Téléchargement de mods** via SteamCMD — mod unique ou listes entières
- **📦 Importation de collections Steam** — collez l'URL d'une collection pour récupérer tous les mods d'un coup
- **🔍 Détection automatique de l'ID du jeu** — collez simplement l'ID d'un mod (PublishedFileID), l'ID du jeu (AppID) se remplit tout seul
- **🔄 Vérificateur de mises à jour** — scannez un dossier local de mods pour voir lesquels sont obsolètes ou à jour
- **⏸ Pause et reprise** — arrêtez-vous en plein milieu de la file d'attente et reprenez au prochain lancement
- **🔘 Activer / Désactiver des mods** — activez ou désactivez vos mods sans les supprimer (renomme le dossier en `.disabled`)
- **📋 Historique des jeux** — mémorise chaque jeu pour lequel vous avez téléchargé des mods
- **📁 Ouverture des dossiers en un clic** — ouvrez le dossier du mod ou du jeu directement depuis l'interface
- **💾 Colonne Taille** — visualisez l'espace disque utilisé par chaque mod
- **🌐 Localisation** — traduction complète de l'interface via de simples fichiers JSON
- **🖥 Multiplateforme** — Windows, Linux, macOS

---



---

## 🚀 Démarrage rapide
1. Téléchargez le fichier .exe et lancez-le.
2. Démarrez WorkshopDL.exe.
3. Allez dans **Paramètres** → cliquez sur **⬇ Télécharger SteamCMD automatiquement**.
4. Saisissez l'ID d'un mod dans l'onglet **Télécharger** — l'ID du jeu sera détecté automatiquement.
5. Cliquez sur **⬇ Télécharger**.


## 📦 Prérequis pour la compilation

```
Python 3.8+
PyQt5 ou PyQt6
requests
```

Installer les dépendances:
```bash
pip install PyQt5 requests
```
## 🔨 Compilation rapide
1. Clonez ou téléchargez ce dépôt.
2. Installez les dépendances (voir ci-dessus).
3. Exécutez :
   ```bash
   python workshopdl.py
   ```
4. Allez dans Paramètres → cliquez sur ⬇ Télécharger SteamCMD automatiquement.
5. Saisissez l'ID d'un mod dans l'onglet Télécharger — l'ID du jeu sera détecté automatiquement.
6. Cliquez sur ⬇ Télécharger.

---

## 🗂 Structure du projet

```
WorkshopDL/
├── workshopdl.py         # Application principale
├── lang/                 # Langues (optionnel)
│   ├── de.json
│   ├── en.json          # Localisation anglaise (par défaut)
│   ├── fr.json
│   ├── ru.json          # Localisation russe
│   └── zh.json
├── Modules/              # Données d'exécution (créé automatiquement)
│   ├── queue.json        # File d'attente de pause/reprise
│   ├── history.json      # Historique des jeux
│   └── mod_paths.json    # Chemins sauvegardés des dossiers de mods
├── steamcmd/             # Installation de SteamCMD (créé automatiquement)
└── WorkshopDL.ini        # Paramètres utilisateur
```

---

## 🔄 Vérificateur de mises à jour

L'onglet **🔄 Vérifier les mises à jour** vous permet de scanner n'importe quel dossier local contenant des mods
(par ex. `C:\games\SovietRepublic\media_soviet\workshop_wip`).

Le dossier doit contenir des sous-dossiers numériques — un par mod :
```
workshop_wip/
├── 1797996358/
├── 1807300910/
└── 2031421793.disabled   ← mod désactivé (exclu du jeu)
```

WorkshopDL compare la date de modification du dossier local avec le champ
`time_updated` fourni par l'API Steam et catégorise chaque mod ainsi :

| Icône | Signification |
|---|---|
| 🔴 | Obsolète — une version plus récente est disponible sur le serveur |
| 🟢 | À jour |
| 🔘 | Désactivé (le dossier possède le suffixe `.disabled`) |
| ⚪ | Inconnu — l'API Steam n'a renvoyé aucune donnée |

---

---

## 🔘 Activer / Désactiver des mods

Cliquez sur le bouton **⏸ / ▶** dans le tableau pour basculer l'état d'un mod.  
Cela renomme simplement le dossier :

```
1797996358          →   1797996358.disabled    (désactivé)
1797996358.disabled →   1797996358             (activé)
```

Aucun fichier n'est supprimé. Votre jeu ignorera les dossiers portant l'extension `.disabled`
(selon le gestionnaire de mods du jeu).

---

## 🌐 Traductions

Tous les textes de l'interface sont regroupés dans un seul fichier JSON. Pour créer une nouvelle traduction :

1. Copiez `lang_en.json` et renommez-le, par exemple `lang_de.json`.
2. Traduisez les **valeurs** (le côté droit de chaque ligne) — ne modifiez pas les clés.
3. Dans **Paramètres → Langue**, sélectionnez votre fichier et cliquez sur **✅ Appliquer**.

### Contribuer à une traduction

Pour partager votre traduction avec tout le monde :
- Ajoutez votre fichier `lang_XX.json` dans le dossier `lang/` de ce dépôt.
- Ouvrez une Pull Request — nous l'ajouterons à la liste des téléchargements intégrée à l'application.

## ⚙ Paramètres

| Paramètre | Description |
|---|---|
| Mode incognito | Téléchargement sans compte Steam (la plupart des mods le support) |
| Identifiant / Mot de passe Steam | Requis uniquement si le mode incognito est désactivé |
| Chemin SteamCMD | Chemin vers l'exécutable `steamcmd` — ou téléchargement automatique |
| Langue | Chemin vers un fichier de localisation `.json` |
| Chemin de mise à jour des mods | Dossier par défaut utilisé par le vérificateur de mises à jour |

## 🛠 SteamCMD

WorkshopDL utilise [SteamCMD](https://developer.valvesoftware.com/wiki/Fr/SteamCMD)
pour télécharger les mods. Vous n'avez pas besoin de l'installer manuellement —
allez dans les **Paramètres** et cliquez sur **⬇ Télécharger SteamCMD automatiquement**.

Lors du premier lancement, SteamCMD télécharge ses propres fichiers d'exécution (~40 Mo). Cela ne se produit
qu'une seule fois et s'affiche dans les logs des Paramètres.

| Plateforme | Exécutable | Téléchargement |
|---|---|---|
| Windows | `steamcmd.exe` | `.zip` |
| Linux | `steamcmd.sh` | `.tar.gz` |
| macOS | `steamcmd` | `.tar.gz` |

---

## 📄 Licence

MIT — faites-en ce que vous voulez, une attribution est toujours appréciée.

---
## 👷 Virustotal
[https://www.virustotal.com/gui/file/3ee0c7aa1ddbfac2496e6530652e8c71383e37b948b90d8722629c516f586b45/detection](https://www.virustotal.com/gui/file/0af0377f5cf265ac62c91c152e11997b6d4d380731d7e02811665321878b0c33)

<div align="center">
fait avec ☕ et PyQt5
</div>
