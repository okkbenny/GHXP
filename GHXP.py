#!/usr/bin/env python3
"""GHXP — Clone Hero Universal Video Background Utility (unofficial).

One GUI for ZIP archives and already-extracted folders. Python 3.10+, standard
library only. PREVIEW changes nothing; INSTALL copies only one video to each
uniquely selected song. Never deletes a source or overwrites existing videos.
"""
from __future__ import annotations

import csv
import json
import os
import queue
import re
import shutil
import tempfile
import threading
import unicodedata
import zipfile
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "GHXP | Clone Hero Video Background Utility"
VERSION = "1.0"
EXTENSIONS = frozenset({".mp4", ".webm", ".avi", ".ogv", ".mpeg", ".mpg"})
MAX_VIDEO_BYTES = 5 * 1024 ** 3
STAMP = re.compile(r"-\d{8}T\d{6}Z(?:-\d+){1,3}$", re.IGNORECASE)
CONFIG = Path(os.environ.get("APPDATA") or str(Path.home())) / "CHUniversalBackgroundInstaller" / "settings.json"
ASSET_DIR = Path(__file__).resolve().parent

BG = "#F1F3F6"
WHITE = "#FFFFFF"
TEXT = "#1C2733"
MUTED = "#657280"
LINE = "#DDE3E9"
GREEN = "#159255"
RED = "#E74C52"
YELLOW = "#E5AF32"
BLUE = "#357AC6"
ORANGE = "#E98A2E"
DARK = "#273447"


def clean_source_title(name: str) -> str:
    """Remove common download-service timestamp (ZIP stem or folder name)."""
    return STAMP.sub("", name).strip(" -_\t")


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def read_song_ini(path: Path) -> tuple[str, str]:
    try:
        raw = path.read_bytes()
    except OSError:
        return "", ""
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeError:
        content = raw.decode("cp1252", errors="replace")
    title, artist = "", ""
    in_song = False
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_song = line[1:-1].strip().casefold() == "song"
        elif in_song and "=" in line and not line.startswith((";", "#")):
            key, val = (x.strip() for x in line.split("=", 1))
            val = val.strip('"').strip("'")
            if key.casefold() == "name":
                title = val
            elif key.casefold() == "artist":
                artist = val
    return title, artist


@dataclass(frozen=True)
class Song:
    folder: Path
    title: str
    artist: str
    display: str
    aliases: tuple[str, ...]


def index_songs(root: Path) -> list[Song]:
    songs: list[Song] = []
    for where, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(where) / d).is_symlink()]
        file_set = {f.casefold() for f in files}
        if not file_set.intersection({"song.ini", "notes.chart", "notes.mid", "notes.midi"}):
            continue
        folder = Path(where)
        ini = next((folder / f for f in files if f.casefold() == "song.ini"), None)
        title, artist = read_song_ini(ini) if ini else ("", "")
        folder_title = folder.name.split(" - ", 1)[-1] if " - " in folder.name else folder.name
        aliases = tuple(dict.fromkeys(filter(None, (
            normalize(title), normalize(folder_title), normalize(folder.name),
            normalize(f"{artist} - {title}") if title and artist else "",
        ))))
        songs.append(Song(folder, title, artist, str(folder.relative_to(root)), aliases))
    return sorted(songs, key=lambda s: s.display.casefold())


def match_song(query: str, songs: list[Song]) -> tuple[str, Optional[Song], str]:
    needle = normalize(query)
    if not needle:
        return "NO MATCH", None, "Empty or unreadable song title"
    exact = [song for song in songs if needle in song.aliases]
    if len(exact) == 1:
        return "READY", exact[0], "Unique exact song-title match"
    if len(exact) > 1:
        return "AMBIGUOUS", None, f"{len(exact)} chart folders have this title; choose manually"
    ranked = []
    for song in songs:
        score = max((SequenceMatcher(None, needle, alias).ratio() for alias in song.aliases), default=0)
        if score >= 0.78:
            ranked.append((score, song))
    ranked.sort(key=lambda x: (-x[0], x[1].display.casefold()))
    if ranked:
        score, candidate = ranked[0]
        return "REVIEW", candidate, f"Possible match ({score:.0%}); confirm manually"
    return "NO MATCH", None, "No exact song-title match; use manual assignment"


def has_video(folder: Path) -> bool:
    try:
        return any(p.is_file() and p.stem.casefold() == "video" and
                   p.suffix.casefold() in EXTENSIONS for p in folder.iterdir())
    except OSError:
        return True  # fail closed: never blindly write when directory can't be read


def video_from_zip(archive: Path) -> tuple[str, str, int, int, str]:
    """Identify one video member; extraction uses ZipFile.open directly, NOT extractall."""
    try:
        with zipfile.ZipFile(archive) as zf:
            videos = []
            for info in zf.infolist():
                if info.is_dir():
                    continue
                basename = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
                stem, ext = os.path.splitext(basename)
                if stem.casefold() == "video" and ext.casefold() in EXTENSIONS:
                    videos.append((info, ext.lower()))
            if not videos:
                return "", "", 0, 0, "No file named video.mp4 / video.webm / etc. in ZIP"
            if len(videos) != 1:
                return "", "", 0, 0, "Multiple video files in ZIP; resolve the archive first"
            info, ext = videos[0]
            if info.file_size <= 0 or info.file_size > MAX_VIDEO_BYTES:
                return "", "", 0, 0, "Video is empty or exceeds 5 GiB safety limit"
            if info.flag_bits & 1:
                return "", "", 0, 0, "Password-protected ZIP video is not supported"
            return info.filename, ext, info.file_size, info.CRC, ""
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        return "", "", 0, 0, f"Unreadable ZIP: {exc}"


def video_from_folder(folder: Path) -> tuple[Optional[Path], int, int, str]:
    found: list[Path] = []
    for where, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(where) / d).is_symlink()]
        for filename in files:
            path = Path(where) / filename
            if path.is_symlink():
                continue
            if path.stem.casefold() == "video" and path.suffix.casefold() in EXTENSIONS:
                found.append(path)
    if not found:
        return None, 0, 0, "No file named video.mp4 / video.webm / etc. in folder"
    if len(found) != 1:
        return None, 0, 0, "Multiple video files in folder; resolve manually"
    try:
        stat = found[0].stat()
    except OSError as exc:
        return None, 0, 0, f"Unreadable video: {exc}"
    if stat.st_size <= 0 or stat.st_size > MAX_VIDEO_BYTES:
        return None, 0, 0, "Video is empty or exceeds 5 GiB safety limit"
    return found[0], stat.st_size, stat.st_mtime_ns, ""


@dataclass
class Plan:
    source: Path
    kind: str            # "ZIP" or "FOLDER"
    title: str
    member: str = ""    # archive inner member (never used as extraction path)
    video: Optional[Path] = None
    ext: str = ""
    size: int = 0
    crc: int = 0
    source_size: int = 0
    source_mtime_ns: int = 0
    video_mtime_ns: int = 0
    destination: Optional[Path] = None
    status: str = ""
    note: str = ""


def plan_sources(source: Path, songs_root: Path, mode: str = "Both") -> tuple[list[Plan], list[Song]]:
    songs = index_songs(songs_root)
    plans: list[Plan] = []
    try:
        candidates = sorted(source.iterdir(), key=lambda x: x.name.casefold())
    except OSError:
        raise
    for item in candidates:
        if item.is_symlink():
            continue
        kind = "ZIP" if item.is_file() and item.suffix.casefold() == ".zip" else (
            "FOLDER" if item.is_dir() else None)
        if kind is None or (mode == "ZIPs only" and kind != "ZIP") or (
                mode == "Folders only" and kind != "FOLDER"):
            continue
        title = clean_source_title(item.stem if kind == "ZIP" else item.name)
        plan = Plan(item, kind, title)
        try:
            if kind == "ZIP":
                stat = item.stat()
                plan.source_size, plan.source_mtime_ns = stat.st_size, stat.st_mtime_ns
                plan.member, plan.ext, plan.size, plan.crc, error = video_from_zip(item)
            else:
                plan.video, plan.size, plan.video_mtime_ns, error = video_from_folder(item)
                plan.ext = plan.video.suffix.lower() if plan.video else ""
        except OSError as exc:
            error = str(exc)
        if error:
            plan.status, plan.note = "SOURCE ISSUE", error
            plans.append(plan)
            continue
        status, song, note = match_song(title, songs)
        plan.status, plan.note = status, note
        plan.destination = song.folder if song else None
        if status == "READY" and plan.destination and has_video(plan.destination):
            plan.status, plan.note = "EXISTS", "Song already contains a video; will skip"
        plans.append(plan)

    # Cross-format collisions: ZIP + extracted folder -> the same song.
    targets: dict[Path, list[Plan]] = {}
    for plan in plans:
        if plan.status == "READY" and plan.destination:
            targets.setdefault(plan.destination.resolve(), []).append(plan)
    for group in targets.values():
        if len(group) > 1:
            for plan in group:
                plan.status = "DUPLICATE"
                plan.note = f"{len(group)} sources target this song; select one manually"
                plan.destination = None
    return plans, songs


def safe_install(plan: Plan, source_root: Path, songs_root: Path) -> str:
    """Copy one video into a song directory, never clobber. No source modifications."""
    if not plan.destination or not plan.ext or not plan.size:
        raise ValueError("Incomplete plan; preview again")
    src_root = source_root.resolve(strict=True)
    root = songs_root.resolve(strict=True)
    destination = plan.destination.resolve(strict=True)
    source = plan.source.resolve(strict=True)
    if not destination.is_relative_to(root) or not destination.is_dir():
        raise ValueError("Destination is not within selected Clone Hero Songs directory")
    if not source.is_relative_to(src_root) or source.parent != src_root:
        raise ValueError("Source is not a direct child of the selected downloads folder")
    if plan.source.is_symlink():
        raise ValueError("Symlinked sources aren't supported")
    if has_video(destination):
        return "SKIPPED: video already exists"
    output = destination / ("video" + plan.ext)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".chvideo_", suffix=".tmp",
                                         dir=destination, delete=False) as temp:
            temporary = Path(temp.name)
            if plan.kind == "ZIP":
                stat = source.stat()
                if stat.st_size != plan.source_size or stat.st_mtime_ns != plan.source_mtime_ns:
                    raise ValueError("ZIP changed after preview; preview again")
                with zipfile.ZipFile(source) as zf:
                    info = zf.getinfo(plan.member)
                    if (info.file_size != plan.size or info.CRC != plan.crc or
                            info.file_size > MAX_VIDEO_BYTES):
                        raise ValueError("ZIP contents changed after preview")
                    with zf.open(info) as stream:
                        shutil.copyfileobj(stream, temp, length=1024 * 1024)
            elif plan.kind == "FOLDER":
                if not plan.video or plan.video.is_symlink():
                    raise ValueError("Source video missing or symlinked")
                video = plan.video.resolve(strict=True)
                if not video.is_relative_to(source):
                    raise ValueError("Video is outside its source song folder")
                stat = video.stat()
                if stat.st_size != plan.size or stat.st_mtime_ns != plan.video_mtime_ns:
                    raise ValueError("Source video changed after preview; preview again")
                with video.open("rb") as stream:
                    shutil.copyfileobj(stream, temp, length=1024 * 1024)
                if video.stat().st_size != plan.size or video.stat().st_mtime_ns != plan.video_mtime_ns:
                    raise ValueError("Source changed during copying; preview again")
            else:
                raise ValueError("Unknown source type")
        if temporary.stat().st_size != plan.size:
            raise ValueError("Copied video size differs from preview")
        if has_video(destination):
            return "SKIPPED: video appeared during installation"
        # Hard-link to temporary file atomically creates destination or refuses to replace it.
        try:
            os.link(temporary, output)
        except FileExistsError:
            return "SKIPPED: destination video already exists"
        except OSError:
            # Portable no-overwrite fallback (Windows filesystems without hard links).
            try:
                with output.open("xb") as dst, temporary.open("rb") as stream:
                    shutil.copyfileobj(stream, dst, length=1024 * 1024)
            except FileExistsError:
                return "SKIPPED: destination video already exists"
            except BaseException:
                try:
                    output.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
        return "INSTALLED"
    finally:
        if temporary:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def guess_songs_folder() -> Path:
    home = Path.home()
    options = [home / "Documents" / "Clone Hero" / "Songs",
               home / "OneDrive" / "Documents" / "Clone Hero" / "Songs"]
    return next((p for p in options if p.is_dir()), options[0])


class UniversalUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1290x850")
        self.minsize(940, 650)
        self.configure(bg=BG)
        try:
            with CONFIG.open("r", encoding="utf-8") as f:
                opts = json.load(f)
            if not isinstance(opts, dict):
                opts = {}
        except (OSError, ValueError):
            opts = {}
        self.source_var = tk.StringVar(value=opts.get("source", str(Path.home() / "Downloads")))
        self.songs_var = tk.StringVar(value=opts.get("songs", str(guess_songs_folder())))
        self.mode_var = tk.StringVar(value=opts.get("mode", "Both"))
        if self.mode_var.get() not in ("Both", "ZIPs only", "Folders only"):
            self.mode_var.set("Both")
        self.summary_var = tk.StringVar(value="Choose your folders and click Preview matches. Nothing changes until you install.")
        self.jobs: queue.Queue = queue.Queue()
        self.plans: list[Plan] = []
        self.songs: list[Song] = []
        self.previewed: Optional[tuple[Path, Path, str]] = None
        self.busy = False
        self.entries: list[ttk.Entry] = []
        self.browse_buttons: list[ttk.Button] = []
        self.logo_image: Optional[tk.PhotoImage] = None
        self._styles()
        self._widgets()
        self.source_var.trace_add("write", lambda *_: self.invalidate())
        self.songs_var.trace_add("write", lambda *_: self.invalidate())
        self.mode_var.trace_add("write", lambda *_: self.invalidate())
        self.after(80, self._read_jobs)

    def _styles(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Plain.TFrame", background=WHITE)
        style.configure("Bg.TFrame", background=BG)
        style.configure("TEntry", fieldbackground=WHITE, foreground=TEXT, padding=7, font=("Segoe UI", 10))
        style.configure("TCombobox", fieldbackground=WHITE, padding=7, font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI Semibold", 9), padding=(13, 9), background="#E7ECF2", foreground=TEXT,
                        bordercolor=LINE)
        style.map("TButton", background=[("active", "#DCE4EC"), ("disabled", "#F1F3F5")])
        for label, bg, fg in [("Primary", DARK, WHITE), ("Install", GREEN, WHITE)]:
            style.configure(f"{label}.TButton", background=bg, foreground=fg,
                            padding=(19, 11), font=("Segoe UI Semibold", 10), bordercolor=bg)
            style.map(f"{label}.TButton", background=[("active", "#47596F" if label == "Primary" else "#0F7B49"),
                                                         ("disabled", "#C9D1D8")],
                      foreground=[("disabled", WHITE)])
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=31, background=WHITE,
                        fieldbackground=WHITE, foreground=TEXT, borderwidth=0)
        style.map("Treeview", background=[("selected", "#DDEBFA")], foreground=[("selected", "#162738")])
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9), background="#E9EDF2",
                        foreground=DARK, borderwidth=0, padding=8)
        style.configure("CH.Horizontal.TProgressbar", troughcolor="#E1E5EA", background=GREEN,
                        borderwidth=0, thickness=5)

    def _card(self, parent: tk.Widget, pady: int = 13) -> tk.Frame:
        card = tk.Frame(parent, bg=WHITE, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x", pady=(0, pady))
        return card

    def _widgets(self) -> None:
        header = tk.Frame(self, bg=WHITE, height=112, highlightbackground=LINE, highlightthickness=1)
        header.pack(fill="x")
        header.pack_propagate(False)
        hl = tk.Frame(header, bg=WHITE)
        hl.pack(side="left", padx=(24, 12), pady=11)
        logo = ASSET_DIR / "clonehero_wordmark.png"
        if logo.is_file():
            try:
                self.logo_image = tk.PhotoImage(file=str(logo))
                tk.Label(hl, image=self.logo_image, bg=WHITE).pack(side="left")
            except tk.TclError:
                pass
        if self.logo_image is None:
            tk.Label(hl, text="CLONE\nHERO", font=("Arial Black", 19, "bold"),
                     fg=DARK, bg=WHITE, justify="left").pack(side="left")
        title = tk.Frame(header, bg=WHITE)
        title.pack(side="left", pady=23)
        tk.Label(title, text="GHXP", font=("Segoe UI Semibold", 17),
                 bg=WHITE, fg=TEXT).pack(anchor="w")
        tk.Label(title, text="ZIP archives + extracted folders  |  Unofficial community utility",
                 font=("Segoe UI", 9), bg=WHITE, fg=MUTED).pack(anchor="w", pady=(4, 0))
        frets = tk.Canvas(header, width=170, height=48, bg=WHITE, highlightthickness=0)
        frets.pack(side="right", padx=(0, 28), pady=(30, 0))
        for i, color in enumerate((GREEN, RED, YELLOW, BLUE, ORANGE)):
            x = 20 + i * 30
            frets.create_oval(x - 11, 12, x + 11, 34, fill=color, outline="")
            frets.create_oval(x - 6, 15, x + 2, 20, fill="#FFFFFF", outline="")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=22, pady=16)

        instructions = self._card(body, 12)
        inner = tk.Frame(instructions, bg=WHITE)
        inner.pack(fill="x", padx=18, pady=12)
        tk.Label(inner, text="HOW IT WORKS", font=("Segoe UI Semibold", 10),
                 bg=WHITE, fg=DARK).pack(anchor="w")
        tk.Label(inner,
                 text=("1   Put ZIPs and/or extracted folders into your chosen source folder.\n"
                       "2   Name each ZIP or folder after its song title (e.g., Shiver.zip or Shiver\\video.mp4).\n"
                       "3   Each ZIP/folder must contain exactly one video.mp4, video.webm, or another supported 'video' file.\n"
                       "4   Preview the matches, review any warnings, then install. Timestamps are removed automatically."),
                 font=("Segoe UI", 9), justify="left", bg=WHITE, fg=MUTED).pack(anchor="w", pady=(6, 0))

        paths = self._card(body, 12)
        inside = tk.Frame(paths, bg=WHITE)
        inside.pack(fill="x", padx=18, pady=12)
        inside.columnconfigure(1, weight=1)
        for r, (label, variable, kind) in enumerate((
            ("SOURCE FOLDER  ·  ZIPs and/or extracted folders", self.source_var, "src"),
            ("CLONE HERO SONGS  ·  scans all nested packs", self.songs_var, "dst"),
        )):
            tk.Label(inside, text=label, bg=WHITE, fg=TEXT,
                     font=("Segoe UI Semibold", 9)).grid(row=r, column=0, sticky="w", pady=6)
            entry = ttk.Entry(inside, textvariable=variable)
            entry.grid(row=r, column=1, sticky="ew", padx=(12, 8), pady=6)
            self.entries.append(entry)
            button = ttk.Button(inside, text="Browse...", command=lambda k=kind: self.browse(k))
            button.grid(row=r, column=2, sticky="e", pady=6)
            self.browse_buttons.append(button)
        tk.Label(inside, text="SCAN", bg=WHITE, fg=TEXT,
                 font=("Segoe UI Semibold", 9)).grid(row=2, column=0, sticky="w", pady=(8, 2))
        mode = ttk.Combobox(inside, textvariable=self.mode_var, state="readonly", width=18,
                            values=("Both", "ZIPs only", "Folders only"))
        mode.grid(row=2, column=1, sticky="w", padx=(12, 8), pady=(8, 2))
        self.mode_combo = mode
        tk.Label(inside, text="Both detects either format automatically.",
                 bg=WHITE, fg=MUTED, font=("Segoe UI", 9)).grid(row=2, column=1, sticky="w", padx=190, pady=(8, 2))

        actions = tk.Frame(body, bg=BG)
        actions.pack(fill="x", pady=(0, 10))
        self.preview_button = ttk.Button(actions, text="1   Preview matches", style="Primary.TButton", command=self.preview)
        self.preview_button.pack(side="left", padx=(0, 9))
        self.install_button = ttk.Button(actions, text="2   Install ready videos", style="Install.TButton", command=self.install)
        self.install_button.pack(side="left", padx=(0, 9))
        self.assign_button = ttk.Button(actions, text="Assign selected...", command=self.assign)
        self.assign_button.pack(side="left", padx=(0, 9))
        self.export_button = ttk.Button(actions, text="Export CSV", command=self.export)
        self.export_button.pack(side="right")

        tk.Label(body, textvariable=self.summary_var, bg=BG, fg=MUTED,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(0, 7))
        table = tk.Frame(body, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        table.pack(fill="both", expand=True)
        columns = ("source", "format", "title", "status", "destination", "details")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse", height=3)
        for col, title, width in (("source", "SOURCE ITEM", 260), ("format", "TYPE", 75),
                                  ("title", "SONG TITLE", 165), ("status", "STATUS", 112),
                                  ("destination", "MATCHED SONG FOLDER", 305), ("details", "DETAILS", 295)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, minwidth=65, stretch=(col in ("source", "destination", "details")))
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree.bind("<Double-1>", lambda _: self.assign())
        for tag, fg in (("READY", "#147B49"), ("MANUAL", "#147B49"), ("INSTALLED", "#147B49"),
                        ("REVIEW", "#A87512"), ("AMBIGUOUS", "#A87512"), ("DUPLICATE", "#A87512"),
                        ("EXISTS", "#6D7A89"), ("NO MATCH", "#A87512"),
                        ("SOURCE ISSUE", "#B5434D"), ("FAILED", "#B5434D")):
            self.tree.tag_configure(tag, foreground=fg)

        tk.Label(body, text="ACTIVITY LOG", bg=BG, fg=TEXT,
                 font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(12, 5))
        self.log = tk.Text(body, bg=WHITE, fg=MUTED, font=("Consolas", 9), height=3, wrap="word",
                           relief="flat", padx=12, pady=8, state="disabled", highlightbackground=LINE,
                           highlightthickness=1)
        self.log.pack(fill="x")
        self.progress = ttk.Progressbar(body, orient="horizontal", mode="determinate",
                                        style="CH.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(10, 0))
        self._log("Ready. Preview first; originals and existing song videos are always protected.")
        self._buttons()

    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _save(self) -> None:
        try:
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            CONFIG.write_text(json.dumps({"source": self.source_var.get(),
                                          "songs": self.songs_var.get(),
                                          "mode": self.mode_var.get()}, indent=2), encoding="utf-8")
        except OSError:
            pass

    def invalidate(self) -> None:
        self.plans = []
        self.songs = []
        self.previewed = None
        self.tree.delete(*self.tree.get_children())
        self.summary_var.set("Settings changed. Run Preview matches again.")
        self.progress.configure(value=0)
        self._buttons()

    def browse(self, kind: str) -> None:
        var = self.source_var if kind == "src" else self.songs_var
        p = Path(var.get()).expanduser()
        choice = filedialog.askdirectory(title=("Select ZIP / folders source" if kind == "src" else
                                               "Select Clone Hero Songs folder"),
                                         initialdir=str(p if p.is_dir() else Path.home()))
        if choice:
            var.set(choice)
            self._save()

    def _paths(self) -> Optional[tuple[Path, Path]]:
        try:
            source = Path(self.source_var.get().strip().strip('"')).expanduser().resolve(strict=True)
            songs = Path(self.songs_var.get().strip().strip('"')).expanduser().resolve(strict=True)
            if not source.is_dir() or not songs.is_dir():
                raise ValueError("Both selections must be existing folders.")
            if source == songs or source.is_relative_to(songs) or songs.is_relative_to(source):
                raise ValueError("Source and Songs folders must be separate, not nested within each other.")
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("Check selected folders", str(exc))
            return None
        return source, songs

    def _busy(self, busy: bool) -> None:
        self.busy = busy
        self._buttons()

    def _buttons(self) -> None:
        normal = "disabled" if self.busy else "normal"
        ready = any(plan.status in ("READY", "MANUAL") for plan in self.plans)
        self.preview_button.configure(state=normal)
        self.install_button.configure(state="normal" if not self.busy and ready else "disabled")
        self.assign_button.configure(state="normal" if not self.busy and self.previewed else "disabled")
        self.export_button.configure(state="normal" if not self.busy and self.previewed else "disabled")
        self.mode_combo.configure(state="disabled" if self.busy else "readonly")
        for entry in self.entries:
            entry.configure(state=normal)
        for btn in self.browse_buttons:
            btn.configure(state=normal)

    def preview(self) -> None:
        paths = self._paths()
        if not paths:
            return
        source, songs = paths
        self.plans, self.songs, self.previewed = [], [], None
        self.tree.delete(*self.tree.get_children())
        self._busy(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start(11)
        self.summary_var.set("Indexing chart folders and inspecting ZIPs / extracted folders...")
        self._log(f"Scanning source: {source}")
        self._log(f"Scanning song library: {songs}")
        self._save()
        threading.Thread(target=self._preview_worker, args=(source, songs, self.mode_var.get()), daemon=True).start()

    def _preview_worker(self, src: Path, songs: Path, mode: str) -> None:
        try:
            plans, indexed = plan_sources(src, songs, mode)
            self.jobs.put(("preview_done", src, songs, mode, plans, indexed))
        except Exception as exc:
            self.jobs.put(("error", "Preview", str(exc)))

    def _render(self) -> None:
        selected = self.tree.selection()
        old = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        for idx, plan in enumerate(self.plans):
            target = str(plan.destination.relative_to(self.previewed[1])) if (plan.destination and self.previewed) else "—"
            self.tree.insert("", "end", iid=str(idx), values=(plan.source.name, plan.kind,
                            plan.title, plan.status, target, plan.note), tags=(plan.status,))
        if old and old in self.tree.get_children():
            self.tree.selection_set(old)

    def _summary(self) -> None:
        counts: dict[str, int] = {}
        for plan in self.plans:
            counts[plan.status] = counts.get(plan.status, 0) + 1
        parts = [f"{len(self.songs)} songs indexed", f"{len(self.plans)} sources"]
        for name in ("READY", "MANUAL", "INSTALLED", "EXISTS", "REVIEW", "AMBIGUOUS",
                     "DUPLICATE", "NO MATCH", "SOURCE ISSUE", "FAILED"):
            if counts.get(name):
                parts.append(f"{counts[name]} {name.lower()}")
        self.summary_var.set("   •   ".join(parts) if self.plans else
                             f"{len(self.songs)} songs indexed  •  No matching ZIPs or folders in source")

    def _selected(self) -> Optional[Plan]:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Select an item", "Select a ZIP or folder row first.")
            return None
        return self.plans[int(selection[0])]

    def assign(self) -> None:
        if self.busy or not self.previewed:
            return
        plan = self._selected()
        if plan is None:
            return
        if not plan.ext or not plan.size:
            messagebox.showwarning("Source issue", "This item does not contain one usable video.")
            return
        if plan.status == "INSTALLED":
            messagebox.showinfo("Already installed", "This video has already been installed.")
            return
        popup = tk.Toplevel(self)
        popup.title(f"Choose song for: {plan.title}")
        popup.geometry("850x520")
        popup.minsize(650, 400)
        popup.configure(bg=BG)
        popup.transient(self)
        popup.grab_set()
        card = tk.Frame(popup, bg=WHITE)
        card.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(card, text=f"Assign destination for: {plan.title}", font=("Segoe UI Semibold", 13),
                 bg=WHITE, fg=TEXT).pack(anchor="w", padx=15, pady=(15, 4))
        tk.Label(card, text="Search by song title, artist, or chart folder path. Double-click a result to select.",
                 bg=WHITE, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=15, pady=(0, 10))
        query_var = tk.StringVar(value=plan.title)
        search = ttk.Entry(card, textvariable=query_var)
        search.pack(fill="x", padx=15, pady=(0, 12))
        results = tk.Listbox(card, font=("Segoe UI", 10), bg=WHITE, fg=TEXT,
                             relief="flat", selectbackground="#DDEBFA", selectforeground=TEXT,
                             highlightbackground=LINE, highlightthickness=1)
        results.pack(fill="both", expand=True, padx=15)
        result_count = tk.Label(card, bg=WHITE, fg=MUTED, font=("Segoe UI", 9))
        result_count.pack(anchor="w", padx=15, pady=9)
        visible: list[Song] = []

        def refresh(*_) -> None:
            needle = normalize(query_var.get())
            visible[:] = [s for s in self.songs if not needle or
                          needle in normalize(" ".join((s.title, s.artist, s.display)))]
            results.delete(0, "end")
            for song in visible[:300]:
                results.insert("end", song.display)
            result_count.configure(text=f"{len(visible)} song folders matched" +
                                   (" (showing first 300)" if len(visible) > 300 else ""))

        def choose() -> None:
            sel = results.curselection()
            if not sel:
                messagebox.showinfo("Select a song", "Select a chart folder first.", parent=popup)
                return
            song = visible[sel[0]]
            if has_video(song.folder):
                messagebox.showwarning("Existing video", "That song already has a video. Nothing will be overwritten.",
                                       parent=popup)
                return
            if any(other is not plan and other.status in ("READY", "MANUAL") and
                   other.destination == song.folder for other in self.plans):
                messagebox.showwarning("Already assigned", "Another item is assigned to that song. Resolve it first.",
                                       parent=popup)
                return
            plan.destination = song.folder
            plan.status = "MANUAL"
            plan.note = "You manually confirmed this destination"
            self._render()
            self._summary()
            self._buttons()
            self._log(f"Manually matched {plan.source.name} -> {song.display}")
            popup.destroy()

        query_var.trace_add("write", refresh)
        refresh()
        buttons = tk.Frame(card, bg=WHITE)
        buttons.pack(fill="x", padx=15, pady=(6, 15))
        ttk.Button(buttons, text="Use selected folder", style="Install.TButton", command=choose).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=popup.destroy).pack(side="right")
        results.bind("<Double-1>", lambda _: choose())
        search.focus_set()

    def install(self) -> None:
        if not self.previewed:
            return
        paths = self._paths()
        if not paths:
            return
        if (*paths, self.mode_var.get()) != self.previewed:
            self.invalidate()
            messagebox.showwarning("Preview again", "Selections changed. Preview again before installing.")
            return
        ready = [p for p in self.plans if p.status in ("READY", "MANUAL")]
        if not ready:
            return
        question = (f"Install {len(ready)} video(s) into matching Clone Hero song folders?\n\n"
                    "This copies videos only; your ZIPs and extracted folders will be kept.\n"
                    "Existing song videos are never overwritten.\n\n"
                    "Only exact matches and your manually confirmed matches are included.")
        if not messagebox.askyesno("Confirm video installation", question):
            return
        self._busy(True)
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=len(ready), value=0)
        self._log(f"Installing {len(ready)} videos...")
        threading.Thread(target=self._install_worker, args=(ready, paths[0], paths[1]), daemon=True).start()

    def _install_worker(self, plans: list[Plan], source: Path, root: Path) -> None:
        for plan in plans:
            try:
                result = safe_install(plan, source, root)
                self.jobs.put(("result", plan, "INSTALLED" if result == "INSTALLED" else "EXISTS", result))
            except Exception as exc:
                self.jobs.put(("result", plan, "FAILED", str(exc)))
        self.jobs.put(("install_done",))

    def export(self) -> None:
        if not self.plans:
            return
        filename = filedialog.asksaveasfilename(title="Export match and installation report",
                                                defaultextension=".csv", initialfile="CloneHero_Video_Install_Report.csv",
                                                filetypes=[("CSV files", "*.csv")])
        if not filename:
            return
        try:
            with open(filename, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(("Source", "Type", "Detected song", "Status", "Destination", "Details"))
                for plan in self.plans:
                    writer.writerow((str(plan.source), plan.kind, plan.title, plan.status,
                                     str(plan.destination or ""), plan.note))
            self._log(f"Report exported: {filename}")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    def _read_jobs(self) -> None:
        try:
            while True:
                job = self.jobs.get_nowait()
                kind = job[0]
                if kind == "preview_done":
                    _, src, root, mode, plans, songs = job
                    self.plans, self.songs = plans, songs
                    self.previewed = (src, root, mode)
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self._busy(False)
                    self._render()
                    self._summary()
                    self._log(f"Preview: {len(plans)} sources; {len(songs)} song folders; "
                              f"{sum(p.status == 'READY' for p in plans)} ready.")
                elif kind == "result":
                    _, plan, status, note = job
                    plan.status, plan.note = status, note
                    self.progress.step(1)
                    self._render()
                    self._summary()
                    self._log(f"{status}: {plan.source.name} — {note}")
                elif kind == "install_done":
                    self._busy(False)
                    self._summary()
                    installed = sum(p.status == "INSTALLED" for p in self.plans)
                    failures = sum(p.status == "FAILED" for p in self.plans)
                    self._log(f"Finished. {installed} installed, {failures} failed. Originals are untouched.")
                    messagebox.showinfo("Installation finished",
                                        f"Installed: {installed}\nFailed: {failures}\n\n"
                                        "Skipped or uncertain matches remain visible in the list.\n"
                                        "After installing, scan songs in Clone Hero and enable Song Videos in settings.")
                elif kind == "error":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self._busy(False)
                    self._log(f"{job[1]} error: {job[2]}")
                    messagebox.showerror(f"{job[1]} failed", job[2])
        except queue.Empty:
            pass
        self.after(80, self._read_jobs)


def main() -> None:
    app = UniversalUI()
    try:
        icon = ASSET_DIR / "clonehero_installer_icon.ico"
        if icon.is_file():
            app.iconbitmap(str(icon))
    except (OSError, tk.TclError):
        pass
    app.mainloop()


if __name__ == "__main__":
    main()