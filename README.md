# GHXP | Make Clone Hero Look Like Classic Guitar Hero

**One place for the complete setup: classic Guitar Hero visuals, song resources, performance backgrounds, and an easier way to install them.**

GHXP is a free, unofficial **Windows 11** Python utility for assigning downloaded song-specific performance videos to their correct Clone Hero song folders. It supports both ZIP archives and already-extracted song-named folders.


## Start with the full beginner guide

- **[Read the GitHub Markdown guide](docs/GHXP_Complete_Setup_Guide.md)** — fully readable on GitHub.
- **[Download the plain-text guide](docs/GHXP_Complete_Setup_Guide.txt)** — for offline use.

The guide walks through **Clone Hero → GHLarp → songs/setlists → background videos → GHXP → in-game settings**, with no separate theme-download requirement for this setup.

## All the resources together

| Resource | Link | Purpose |
|---|---|---|
| Clone Hero | [Official website](https://clonehero.net/) | Install the base game |
| GHLarp | [GHLarp releases](https://github.com/arceuss/GHLarp/releases/) | Classic Guitar Hero-style HUDs and visuals |
| Songs and charts | [Songs/setlists directory](https://docs.google.com/spreadsheets/d/13B823ukxdVMocowo1s5XnT3tzciOfruhUVePENKc01o/htmlview#gid=0) | Find song/chart resources |
| Performance videos | [Background video directory](https://docs.google.com/spreadsheets/u/0/d/1mKjWQptErA6qolvxx-EYQUl1mECp1_7Q4BEd3zZb69w/htmlview) | Locate song-specific background downloads |
| GHXP | **This repository** | Match and install video files from your downloads |

**Note on GHLarp:** The necessary theme options are already included with the GHLarp installation used for this setup. You do not need to download additional themes to follow this guide. Always check the GHLarp release notes for Clone Hero version compatibility.

## Running GHXP

**Requirements:** Windows 11, Python 3.10+ with tkinter, Clone Hero, installed song charts, and ZIPs or song-named extracted folders containing a `video.mp4`, `video.webm`, or another supported video file.

1. download this repository using Code → Download ZIP and **extract it fully**.
2. Install Python 3.10+ from [python.org](https://www.python.org/downloads/windows/) if needed.
3. Double-click `START_INSTALLER.bat`.
4. Select **Source Folder** (downloads) and **Clone Hero Songs** (the actual chart library used by the game).
5. Leave scan mode set to **Both** for ZIP files and extracted folders.
6. Click **1 Preview matches**, inspect any uncertain/duplicate matches, and use **Assign selected** when needed.
7. Click **2 Install ready videos**. GHXP copies the `video.*` files; it does not delete the original downloads or overwrite existing song backgrounds.
8. In Clone Hero, rescan songs if needed and enable **Song Videos** in Settings → Gameplay.

**Naming example:** `Shiver-20261118T211812Z-1-001.zip` containing `video.mp4` → `Coldplay - Shiver/video.mp4`. The **ZIP/folder title** identifies the song, not the generic `video.mp4` filename.

Read [PREREQUISITES.txt](PREREQUISITES.txt) for requirements and troubleshooting. Full details and screenshots are in the [beginner guide](docs/GHXP_Complete_Setup_Guide.md).

## Screenshots

Gameplay and GHXP application screenshots can be added here as the project develops.

## Credits and disclaimer

GHLarp is by [arceuss](https://github.com/arceuss/GHLarp/releases/). Clone Hero and all external song/chart/video directories belong to their respective creators and maintainers. GHXP is independent and does not include/download songs, chart packs, or performance-video libraries. Only obtain and use media you have the rights to use.