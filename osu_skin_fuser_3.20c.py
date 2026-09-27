#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
osu_skin_fuser.py  ---  version 3.20c
=====================================

A dependency-free TUI (curses) tool for building osu! skins out of other skins.

Two fusion modes are offered at start-up:

  1. Gameplay + Art fusion
       * Gameplay skin -> hitcircles, sliders, cursor, hitbursts, hit numbers
         (everything that affects how the game feels).
       * Art skin      -> menu, ranking screen, backgrounds, buttons, ...

  2. All-in-One mode fusion
       * Combine osu!standard / osu!mania / osu!taiko / osu!catch skins into a
         single skin.  Pick at least two modes, give each mode its own source
         skin (optionally with separate image / sound sources) and the tool
         stitches the mode-specific sprites, sounds and skin.ini sections
         together so every mode plays like its own source skin.  You can then
         optionally add a separate **Art skin** for the shared menu / ranking /
         background artwork, just like the Gameplay + Art mode.

Both modes keep full per-element / per-sound customisation and can export to a
folder and/or a ready-to-import ``.osk``.

References consulted while writing this tool:
  * https://osu.ppy.sh/wiki/en/Skinning/skin.ini
  * https://osu.ppy.sh/wiki/en/Skinning/osu%21
  * https://osu.ppy.sh/wiki/en/Skinning/osu%21mania
  * https://osu.ppy.sh/wiki/en/Skinning/osu%21taiko
  * https://osu.ppy.sh/wiki/en/Skinning/osu%21catch
  * https://skinship.xyz/guides/mixing_skins

Requires Python 3.8+ and the standard library only (``curses`` for the TUI).
"""

from __future__ import annotations

import argparse
import curses
import locale
import os
import re
import shutil
import sys
import tempfile
import textwrap
import time
import unicodedata
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "3.20c"

APP_TITLE = "osu! AIO Skin Fuser"

IMAGE_EXT = {".png", ".jpg", ".jpeg"}
SOUND_EXT = {".wav", ".ogg", ".mp3"}

MODES = OrderedDict([
    ("standard", "osu!standard"),
    ("mania", "osu!mania"),
    ("taiko", "osu!taiko"),
    ("catch", "osu!catch"),
])

MODE_SHORT = {
    "standard": "STD", "mania": "MANIA", "taiko": "TAIKO", "catch": "CATCH",
    "gameplay": "GP", "art": "ART",
}

# ---------------------------------------------------------------------------
# Element classification
# ---------------------------------------------------------------------------
# Rules match (first hit wins) against the *stem* of a file: file name without
# extension and without the HD "@2x" suffix, lowercased.

GAMEPLAY_IMAGE_RULES = [
    (r"^mania-", "Mania gameplay"),
    (r"^taiko-", "Taiko gameplay"),
    (r"^taikobigcircle", "Taiko gameplay"),
    (r"^taikohitcircle", "Taiko gameplay"),
    (r"^fruit-", "Catch gameplay"),
    (r"^comboburst-", "Comboburst"),
    (r"^hitcircle$|^hitcircleoverlay$|^hitcircleselect$", "Hitcircles"),
    (r"^sliderstartcircle(overlay)?$", "Slider start"),
    (r"^sliderendcircle(overlay)?$", "Slider end"),
    (r"^approachcircle$", "Approach circle"),
    (r"^default-\d+$", "Hitcircle numbers"),
    (r"^followpoint(-\d+)?$", "Follow points"),
    (r"^lighting(n|l)?$", "Lighting"),
    (r"^reversearrow$", "Reverse arrow"),
    (r"^sliderfollowcircle(-\d+)?$", "Slider follow circle"),
    (r"^sliderb(\d+|-nd|-spec)?$", "Slider ball"),
    (r"^sliderpoint(10|30)$", "Slider points"),
    (r"^sliderscorepoint$", "Slider score point"),
    (r"^spinner-", "Spinner"),
    (r"^particle(50|100|300)$", "Particles"),
    (r"^hit(\d+[gk]?)(-\d+)?$", "Hitbursts"),
    (r"^cursor$", "Cursor"),
    (r"^cursortrail$", "Cursor trail"),
    (r"^cursormiddle$", "Cursor middle"),
    (r"^score-(\d+|comma|dot|percent|x)$", "Score numbers"),
    (r"^scorebar", "Health bar"),
    (r"^comboburst(-\d+)?$", "Comboburst"),
    (r"^play-skip$", "Play skip"),
    (r"^play-warningarrow$", "Warning arrow (legacy)"),
    (r"^arrow-(pause|warning|generic)$", "Warning arrow"),
    (r"^inputoverlay-(background|key)$", "Input overlay"),
]

ART_IMAGE_RULES = [
    (r"^menu-", "Menu"),
    (r"^ranking-", "Ranking screen"),
    (r"^section-(pass|fail)$", "Section pass/fail"),
    (r"^pause-", "Pause screen"),
    (r"^fail-background$", "Fail background"),
    (r"^songselect-", "Song select"),
    (r"^selection-", "Selection UI"),
    (r"^mode-", "Mode icons"),
    (r"^star2?$", "Star rating"),
    (r"^button-", "Buttons"),
    (r"^scoreentry-", "Score entry"),
    (r"^play-unranked$", "Unranked banner"),
    (r"^pippidon", "PippiDon"),
    (r"^ready$|^go$", "Countdown"),
    (r"^count\d", "Countdown numbers"),
    (r"^default-percent$", "Percentage sign"),
]

# Mode-specific image elements (for All-in-One fusion).
MODE_IMAGE_RULES = [
    (r"^mania-", "mania"),
    (r"^comboburst-mania(-\d+)?$", "mania"),
    (r"^taiko-", "taiko"),
    (r"^taikobigcircle", "taiko"),
    (r"^taikohitcircle", "taiko"),
    (r"^pippidon", "taiko"),
    (r"^fruit-", "catch"),
    (r"^comboburst-fruits(-\d+)?$", "catch"),
]

HITSOUND_SOUND_RE = re.compile(
    r"^(normal|soft|softl|drum|nightcore|taiko|spinnerbonus|spinnerspin|"
    r"sliderbar|combobreak|normal-hit|soft-hit|drum-hit)"
)
INTERFACE_SOUND_HINTS = re.compile(
    r"^(menu|menuclick|menuhit|menuback|back-button|click-|key-|pause-|match-|"
    r"count\d|go$|gos$|readys$|applause|shutter|sectionpass|sectionfail|"
    r"failsound|comboburst|nightcore|softl)"
)

# ---------------------------------------------------------------------------
# Plain-language element descriptions (English, used in menus + search).
# ---------------------------------------------------------------------------

ELEMENT_DESC_RULES = [
    (r"^hitcircleoverlay$", "Hitcircle overlay (ring drawn on top)"),
    (r"^hitcircleselect$", "Hitcircle shown when selected in the editor"),
    (r"^hitcircle$", "Hitcircle body (tinted by combo colour)"),
    (r"^approachcircle$", "Approach circle (shrinks onto the hitcircle)"),
    (r"^default(-\d+)?$|^default$", "Combo numbers on hitcircles"),
    (r"^default-percent$", "Percent sign"),
    (r"^followpoint(-\d+)?$|^followpoint$", "Follow points between hitcircles"),
    (r"^lighting(n|l)?$", "Hit lighting / kiai glow"),
    (r"^reversearrow$", "Slider reverse arrow"),
    (r"^sliderstartcircleoverlay$", "Slider start circle overlay"),
    (r"^sliderstartcircle$", "Slider start circle"),
    (r"^sliderendcircleoverlay$", "Slider end circle overlay"),
    (r"^sliderendcircle$", "Slider end circle"),
    (r"^sliderfollowcircle(-\d+)?$|^sliderfollowcircle$", "Slider follow circle"),
    (r"^sliderb-spec$", "Slider ball highlight layer (does not rotate)"),
    (r"^sliderb-nd$", "Slider ball base layer (black)"),
    (r"^sliderb(\d+)?$|^sliderb$", "Slider ball (tinted by combo colour)"),
    (r"^sliderpoint(10|30)$", "Legacy slider score 10/30"),
    (r"^sliderscorepoint$", "Slider tick score point"),
    (r"^spinner-approachcircle$", "Spinner approach circle"),
    (r"^spinner-background$", "Old-style spinner background"),
    (r"^spinner-circle$", "Old-style spinner disc"),
    (r"^spinner-clear$", "Spinner clear text"),
    (r"^spinner-rpm$", "Spinner RPM readout"),
    (r"^spinner-spin$", "Spinner \"Spin!\" prompt"),
    (r"^spinner-glow$", "New spinner bottom glow"),
    (r"^spinner-bottom$", "New spinner bottom layer (slowest)"),
    (r"^spinner-top$", "New spinner middle layer"),
    (r"^spinner-middle2$", "New spinner upper layer (fastest)"),
    (r"^spinner-middle$", "New spinner top layer (time indicator)"),
    (r"^spinner-osu$", "Legacy spinner end image"),
    (r"^spinner-warning$", "Taiko spinner warning indicator"),
    (r"^particle(50|100|300)$", "Hit particles"),
    (r"^hit0(-\d+)?$|^hit0$", "Miss burst (0)"),
    (r"^hit50(-\d+)?$|^hit50$", "50 burst"),
    (r"^hit100k(-\d+)?$|^hit100k$", "100 burst (kiai)"),
    (r"^hit100(-\d+)?$|^hit100$", "100 burst"),
    (r"^hit300g(-\d+)?$|^hit300g$", "300 burst (GEKI / top)"),
    (r"^hit300k(-\d+)?$|^hit300k$", "300 burst (kiai)"),
    (r"^hit300(-\d+)?$|^hit300$", "300 burst"),
    (r"^cursor$", "Cursor body"),
    (r"^cursortrail$", "Cursor trail"),
    (r"^cursormiddle$", "Cursor centre dot"),
    (r"^score-(\d+|comma|dot|percent|x)$", "Score digits"),
    (r"^scorebar-bg$", "Health bar background"),
    (r"^scorebar-colour$", "Health bar fill colour"),
    (r"^scorebar-ki$", "Health bar KI marker"),
    (r"^scorebar-kidanger2?$", "Health bar danger marker"),
    (r"^scorebar$", "Health bar"),
    (r"^comboburst-mania(-\d+)?$", "osu!mania combo burst"),
    (r"^comboburst-fruits(-\d+)?$", "osu!catch combo burst"),
    (r"^comboburst(-\d+)?$|^comboburst$", "Combo burst image"),
    (r"^play-skip$", "Skip button"),
    (r"^play-warningarrow$", "Legacy warning arrow"),
    (r"^arrow-warning$", "Warning arrow"),
    (r"^arrow-pause$", "Pause warning arrow"),
    (r"^arrow-generic$", "Generic warning arrow"),
    (r"^inputoverlay-key$", "Input overlay key"),
    (r"^inputoverlay-background$", "Input overlay background"),
    (r"^menu-background$", "Main menu background"),
    (r"^menu-back$", "Back button"),
    (r"^menu-button-background$", "Menu button background"),
    (r"^ranking-", "Ranking / results screen element"),
    (r"^section-(pass|fail)$", "Section pass / fail text"),
    (r"^pause-", "Pause menu element"),
    (r"^fail-background$", "Fail screen background"),
    (r"^songselect-", "Song select element"),
    (r"^selection-", "Menu button / icon"),
    (r"^mode-", "Game mode icon"),
    (r"^star2?$", "Star rating icon"),
    (r"^button-", "Generic button"),
    (r"^scoreentry-", "Score entry digits"),
    (r"^play-unranked$", "Unranked banner"),
    (r"^pippidon", "Taiko mascot (PippiDon)"),
    (r"^ready$", "Countdown Ready text"),
    (r"^go$", "Countdown Go text"),
    (r"^count\d", "Countdown number"),
    (r"^taikobigcircle", "Taiko big note circle"),
    (r"^taikohitcircle", "Taiko hit circle"),
    (r"^taiko-", "osu!taiko element"),
    (r"^fruit-catcher", "osu!catch catcher"),
    (r"^fruit-", "osu!catch fruit / droplet"),
    (r"^mania-", "osu!mania element"),
]

SOUND_DESC_RULES = [
    (r"^(normal|soft|drum|softl)-hitnormal", "Hitnormal (main hit sound)"),
    (r"^(normal|soft|drum|softl)-hitclap", "Hitclap"),
    (r"^(normal|soft|drum|softl)-hitfinish", "Hitfinish (cymbal)"),
    (r"^(normal|soft|drum|softl)-hitwhistle", "Hitwhistle"),
    (r"^(normal|soft|drum|softl)-hitwistle", "Hitwhistle (misspelled variant)"),
    (r"^(normal|soft|drum)-sliderslide", "Slider slide sound"),
    (r"^(normal|soft|drum)-slidertick", "Slider tick sound"),
    (r"^(normal|soft|drum)-sliderwhistle", "Slider whistle sound"),
    (r"^nightcore-", "Nightcore mode hit sound"),
    (r"^taiko-", "Taiko mode sound"),
    (r"^spinnerbonus$", "Spinner bonus sound"),
    (r"^spinnerspin$", "Spinner spin sound"),
    (r"^sliderbar$", "Slider sound"),
    (r"^combobreak$", "Combo break sound"),
    (r"^comboburst$", "Combo burst sound"),
    (r"^menu", "Menu sound"),
    (r"^menuback$", "Back menu sound"),
    (r"^back-button", "Back button sound"),
    (r"^click-", "Click sound"),
    (r"^key-", "Keyboard press sound"),
    (r"^pause-", "Pause menu sound"),
    (r"^match-", "Multiplayer match sound"),
    (r"^count\d", "Countdown sound"),
    (r"^go$|^gos$", "Go sound"),
    (r"^readys$", "Ready sound"),
    (r"^applause$", "Applause / cheer"),
    (r"^shutter$", "Shutter sound"),
    (r"^sectionpass$", "Section pass sound"),
    (r"^sectionfail$", "Section fail sound"),
    (r"^failsound$", "Fail sound"),
]


def describe_element(logical: str) -> str:
    for rx, desc in ELEMENT_DESC_RULES:
        if re.match(rx, logical):
            return desc
    return "Other / misc"


def describe_sound(stem: str) -> str:
    for rx, desc in SOUND_DESC_RULES:
        if re.match(rx, stem):
            return desc
    return "Other sound"


# skin.ini keys that describe gameplay feel (default -> gameplay/base skin).
INI_GAMEPLAY_KEYS = {
    "version", "animationframerate", "allowsliderballtint", "comboburstrandom",
    "cursorcentre", "cursorexpand", "cursorrotate", "cursortrailrotate",
    "hitcircleoverlayabovenumber", "hitcircleoverlayabovenumer",
    "layeredhitsounds", "sliderballflip", "spinnerfadeplayfield",
    "spinnerfrequencymodulate", "spinnernoblink", "sliderstyle",
    "customcomboburstsounds",
    "hitcircleprefix", "hitcircleoverlap", "scoreprefix", "scoreoverlap",
    "comboprefix", "combooverlap",
    "combo1", "combo2", "combo3", "combo4", "combo5", "combo6", "combo7",
    "combo8", "inputoverlaytext", "sliderborder", "slidertrackoverride",
    "sliderball",
}

INI_ART_KEYS = {
    "menuglow", "songselectactivetext", "songselectinactivetext",
    "spinnerbackground", "starbreakadditive",
    "hyperdash", "hyperdashfruit", "hyperdashafterimage",
}

MANIA_PATH_KEY_RE = re.compile(
    r"^(keyimage\d+d?|noteimage\d+[hlt]?|stageleft|stageright|stagebottom|"
    r"stagehint|stagelight|lightingn|lightingl|warningarrow|"
    r"hit(0|50|100|200|300|300g))$",
    re.IGNORECASE,
)

SOUND_PRESETS = OrderedDict([
    ("hitsound_gameplay",
     "Hitsounds from Gameplay + Interface from Art  (recommended)"),
    ("hitsound_art",
     "Hitsounds from Art + Interface from Gameplay"),
    ("gameplay", "All sounds from the Gameplay skin"),
    ("art", "All sounds from the Art skin"),
])

IMAGE_PRESETS = OrderedDict([
    ("mixed", "Gameplay pieces from Gameplay  |  Art pieces from Art  (recommended)"),
    ("gameplay", "All images from the Gameplay skin"),
    ("art", "All images from the Art skin"),
])

EXPORT_MODES = OrderedDict([
    ("osk", ".osk only"),
    ("folder", "Folder only"),
    ("both", ".osk + Folder"),
])

# v1.1.0: fixed [General] being dropped from merged skin.ini; "/" search + labels
# v1.2.0: descriptions are now English
# v1.3.0: All-in-One mode fusion, directory picker in skin selection + search,
#         and "q" now navigates back to the previous wizard step.
# v1.4.0: All-in-One can now add an optional Art skin (reuse mode sources or
#         pick a separate one); the chosen skin directory is remembered across
#         all later skin pickers.
# v1.5.0: All-in-One sounds are split into gameplay (per-mode source) and
#         interface/UI (one user-chosen source, including Art).  A sound that
#         the chosen interface source does not contain is left blank instead of
#         being force-filled from another skin.
# v3.11 : Windows 98 Setup style TUI (blue background, header bar, DOS-like
#         status bar with F1=Help / F3=Exit / F5=Remove Color).  Title is now
#         "osu! AIO Skin Fuser".  All features and key bindings are unchanged.
# v3.11.1: tightened the layout to match the reference installers - no text in
#         the top-right corner, title-width underline, an extra blank line,
#         all key hints (incl. Remove Color) on the left of the status bar with
#         a small black divider, and a box around lists / input fields.
# v3.11.2: moved the title down one more line and placed the status-bar divider
#         at roughly 75% of the width.
# v3.12  : a shorter welcome screen (fits 80x25, details moved to F1 Help);
#         F3 now quits Setup immediately (ESC/q still go back); and the image /
#         sound / skin.ini editors are now Windows Setup style settings lists
#         where ENTER opens a framed value-picker dialog and the last row
#         "No Changes:  The above list matches my choice." confirms.
# v3.13  : ESC now works everywhere (the lone Escape key was arriving as the
#         string "\x1b" and only "q" was recognised); long lists keep their
#         frame inside the screen (the bottom border no longer slid under the
#         status bar) and keep the highlight centred while scrolling instead of
#         pinning it to the bottom; the "No Changes:  The above list matches my
#         choice." row was removed from the skin.ini list and the Export Details
#         screen was rebuilt in the Windows Setup "System Information" style
#         (label / value columns + a No Changes row).
# v3.14  : the header rule now starts at the very left edge and uses the double
#         line "=" glyph; the welcome page and the fusion-type page were rebuilt
#         to look like the original Windows Setup (F1 works on the welcome page,
#         ENTER = Gameplay + Art, C = All-in-One); Export Details highlights only
#         the value column; the Review screen is gone (accepting Export Details
#         starts the export after a 0.5 s pause); and the export itself now runs
#         inside the TUI as a Windows Setup "Setup is copying files..." progress
#         screen, ending on a blue "press ENTER" page.
# v3.15  : the Setup backdrop is now the intense DOS blue (#0000FF) and the
#         progress bar the intense yellow (#FFFF00), and the status bar paints
#         the lower-right corner cell as well (ncurses' special last cell was
#         left uncovered before).
# v3.16  : 3.15 tried to reach the intense colours by redefining the palette
#         with init_color(), which some terminals (Konsole) accept but ignore.
#         The progress bar now uses the ANSI *bright* yellow directly (11), so it
#         is the genuinely brighter tier on any 16+ colour terminal, while the
#         backdrop stays the normal blue.
# v3.17  : in list menus the highlighted row no longer pulls its right-hand hint
#         to the left; the hint stays right-aligned whether the row is selected
#         or not.
# v3.18  : the status bar hints are normalised to "KEY=Label" - no spaces around
#         "=", hotkeys uppercased and each label capitalised (e.g. the old
#         "Enter = select   ESC/q = back" now reads "ENTER=Select   ESC=Back").
#         The fine-tune lists (images / sounds / skin.ini) now end with a plain
#         "Done" row instead of the "No Changes:  The above list matches my
#         choice." text (that stays only on the Export Details screen).
# v3.19  : F3 now shows the Setup-style grey confirmation box (its frame, text
#         and separator line all in the darker red, narrower and a bit above
#         centre; press ENTER to continue, F3 again to really quit) instead of
#         quitting at once, and F1 opens an inverted (grey background) Setup
#         Help page.
# v3.20a : (from the user's v3.20 text tweaks) fixed the back key being ignored
#         on the two-skin "Which images should come from where?" page, and on
#         terminals wider than 90 columns the welcome / methods / export-details
#         paragraphs now re-flow to the full width instead of keeping the fixed
#         80x25 line breaks.
# v3.20b : the Export Details ".osk" toggle became a three-way list - ".osk
#         only" (default), "Folder only" and ".osk + Folder" - so you can choose
#         whether a folder is written at all.
# v3.20c : the final blue page gained "press R" to start over, so you can build
#         another skin without relaunching the program.


# ---------------------------------------------------------------------------
# skin.ini parsing
# ---------------------------------------------------------------------------

class IniDocument:
    """A tolerant skin.ini parser that preserves duplicate [Mania] sections."""

    def __init__(self, text: str = ""):
        self.sections: "OrderedDict[str, OrderedDict[str, str]]" = OrderedDict()
        self.mania: "OrderedDict[int, OrderedDict[str, str]]" = OrderedDict()
        self.identity = {"name": None, "author": None, "version": None}
        if text:
            self.parse(text)

    @staticmethod
    def _strip_inline_comment(value: str) -> str:
        m = re.search(r"(?:\s//\s?|\t//)", value)
        if m:
            value = value[:m.start()]
        return value.strip()

    def parse(self, text: str) -> None:
        cur_kind = None
        cur_name = None
        cur_map: "OrderedDict[str, str]" = OrderedDict()
        cur_keys = None

        def flush():
            nonlocal cur_map
            if cur_kind == "normal" and cur_name:
                store = self.sections.setdefault(cur_name, OrderedDict())
                for k, v in cur_map.items():
                    store[k] = v
            elif cur_kind == "mania":
                store = self.mania.get(cur_keys)
                if store is None:
                    store = OrderedDict()
                    self.mania[cur_keys] = store
                for k, v in cur_map.items():
                    store[k] = v

        for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw.strip()
            if not line or line.startswith("//") or line.startswith(";"):
                continue
            sec = re.match(r"^\[(.+?)\]$", line)
            if sec:
                flush()
                cur_name = sec.group(1).strip()
                cur_kind = "mania" if cur_name.lower() == "mania" else "normal"
                cur_map = OrderedDict()
                cur_keys = 0 if cur_kind == "mania" else None
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            if not key:
                continue
            value = self._strip_inline_comment(value)
            if cur_kind == "mania":
                if key.lower() == "keys":
                    try:
                        cur_keys = int(value.split(",")[0].strip())
                    except ValueError:
                        cur_keys = 0
                if cur_keys is not None:
                    cur_map[key] = value
            elif cur_kind == "normal":
                if cur_name and cur_name.lower() == "general" and \
                        key.lower() in ("name", "author", "version"):
                    self.identity[key.lower()] = value
                if value != "":
                    cur_map[key] = value
        flush()

    def has_any(self) -> bool:
        return bool(self.sections or self.mania)


@dataclass
class IniEntry:
    section: str
    key: str
    values: dict = field(default_factory=dict)   # source key -> value
    choice: str = "C"                             # source key | "C"
    custom: str = ""
    is_path: str = ""                             # '' | 'prefix' | 'exact'
    manual: bool = False                          # set when fine-tuned by hand


class IniMerge:
    """Union of several skin.ini files with a per-key source choice."""

    def __init__(self, skin_map: "OrderedDict[str, Skin]", base_key: str):
        self.source_skins = OrderedDict(skin_map)
        self.source_keys = list(skin_map.keys())
        self.base_key = base_key if base_key in skin_map else self.source_keys[0]
        self.sections: "OrderedDict[str, list[IniEntry]]" = OrderedDict()
        for key, skin in self.source_skins.items():
            self._build(skin.ini, key)
        self._dedupe_aliases()

    def _build(self, doc: IniDocument, src: str) -> None:
        skip = {"name", "author", "version"}
        for name, keys in doc.sections.items():
            lst = self.sections.setdefault(name, [])
            for k, v in keys.items():
                if name.lower() == "general" and k.lower() in skip:
                    continue
                existing = next((e for e in lst if e.key.lower() == k.lower()), None)
                if existing is None:
                    entry = IniEntry(section=name, key=k, is_path=self._path_kind(name, k))
                    entry.values[src] = v
                    lst.append(entry)
                else:
                    existing.values[src] = v
        for kc, keys in doc.mania.items():
            sec = f"Mania:{kc}"
            lst = self.sections.setdefault(sec, [])
            for k, v in keys.items():
                if k.lower() == "keys":
                    continue
                existing = next((e for e in lst if e.key.lower() == k.lower()), None)
                if existing is None:
                    entry = IniEntry(section=sec, key=k, is_path=self._path_kind(sec, k))
                    entry.values[src] = v
                    lst.append(entry)
                else:
                    existing.values[src] = v
        for sec in self.sections:
            self.sections[sec].sort(key=lambda e: e.key.lower())

    def _dedupe_aliases(self) -> None:
        aliases = {"hitcircleoverlayabovenumer": "hitcircleoverlayabovenumber"}
        for sec, entries in self.sections.items():
            keys = {e.key.lower() for e in entries}
            drop = {low for low, canon in aliases.items() if low in keys and canon in keys}
            if drop:
                self.sections[sec] = [e for e in entries if e.key.lower() not in drop]

    @staticmethod
    def _path_kind(sec: str, key: str) -> str:
        if sec == "Fonts" and key.lower() in (
                "hitcircleprefix", "scoreprefix", "comboprefix"):
            return "prefix"
        if sec.startswith("Mania") and MANIA_PATH_KEY_RE.match(key):
            return "exact"
        return ""

    def preferred_source(self, e: IniEntry) -> str:
        sec = e.section
        if sec.startswith("Mania") and "mania" in self.source_skins:
            return "mania"
        if sec == "CatchTheBeat" and "catch" in self.source_skins:
            return "catch"
        if ini_key_category(sec, e.key) == "art" and "art" in self.source_skins:
            return "art"
        return self.base_key

    def apply_base(self, base: str) -> None:
        for entries in self.sections.values():
            for e in entries:
                if e.manual:
                    # Never throw away a value the user fine-tuned by hand.
                    continue
                e.choice = self._default_choice(e, base)

    def _default_choice(self, e: IniEntry, base: str) -> str:
        if base == "smart":
            pref = self.preferred_source(e)
            if e.values.get(pref) is not None:
                return pref
        elif base in self.source_skins and e.values.get(base) is not None:
            return base
        for k, v in e.values.items():
            if v is not None:
                return k
        return next(iter(e.values))

    def resolve(self, e: IniEntry):
        if e.choice == "C":
            return e.custom
        return e.values.get(e.choice)

    def ordered_sections(self):
        def key(sec):
            if sec == "General":
                return (0, 0)
            if sec == "Colours":
                return (1, 0)
            if sec == "Fonts":
                return (2, 0)
            if sec.startswith("Mania:"):
                try:
                    return (3, int(sec.split(":", 1)[1]))
                except ValueError:
                    return (3, 99)
            if sec == "CatchTheBeat":
                return (4, 0)
            return (5, sec)
        return sorted(self.sections.keys(), key=key)

    def resolved_path_entries(self):
        for sec in self.ordered_sections():
            for e in self.sections[sec]:
                if e.is_path and self.resolve(e):
                    yield e

    def rename_resolved_path(self, e: IniEntry, new_value: str) -> None:
        if e.choice == "C":
            e.custom = new_value
        else:
            e.values[e.choice] = new_value

    def to_text(self, identity: dict, description: str) -> str:
        out = ["// skin.ini",
               f"// Fused by osu_skin_fuser.py v{VERSION}",
               f"// {description}",
               "",
               "[General]",
               f"Name: {identity['name']}",
               f"Author: {identity['author']}",
               f"Version: {identity['version']}"]
        for sec in self.ordered_sections():
            rows = []
            for e in self.sections[sec]:
                val = self.resolve(e)
                if val is None or val == "":
                    continue
                rows.append(f"{e.key}: {val}")
            if not rows:
                continue
            if sec == "General":
                out.extend(rows)
            elif sec.startswith("Mania:"):
                out.append("")
                out.append("[Mania]")
                out.append(f"Keys: {sec.split(':', 1)[1]}")
                out.extend(rows)
            else:
                out.append("")
                out.append(f"[{sec}]")
                out.extend(rows)
        out.append("")
        return "\n".join(out)


def ini_key_category(section: str, key: str) -> str:
    low = key.lower()
    if section.startswith("Mania"):
        return "gameplay"
    if low in INI_GAMEPLAY_KEYS:
        return "gameplay"
    if low in INI_ART_KEYS:
        return "art"
    return "gameplay"


def classify_image(stem: str):
    for rx, label in GAMEPLAY_IMAGE_RULES:
        if re.match(rx, stem):
            return "gameplay", label
    for rx, label in ART_IMAGE_RULES:
        if re.match(rx, stem):
            return "art", label
    return "art", "Other / misc"


def classify_mode_image(logical: str) -> str:
    for rx, mode in MODE_IMAGE_RULES:
        if re.match(rx, logical):
            return mode
    return "shared"


def classify_mode_sound(stem: str) -> str:
    if stem.startswith("taiko-"):
        return "taiko"
    return "shared"


def sound_kind(stem: str) -> str:
    """'mode' (mode-only), 'gameplay' (shared hitsound) or 'interface' (UI)."""
    if stem.startswith("taiko-"):
        return "mode"
    if classify_sound(stem) == "hitsound":
        return "gameplay"
    return "interface"


def classify_sound(stem: str) -> str:
    if INTERFACE_SOUND_HINTS.match(stem) and stem not in (
            "nightcore-clap", "nightcore-finish", "nightcore-hat",
            "nightcore-kick"):
        return "interface"
    if HITSOUND_SOUND_RE.match(stem):
        return "hitsound"
    return "interface"


# ---------------------------------------------------------------------------
# Skin model
# ---------------------------------------------------------------------------

@dataclass
class SkinFile:
    rel: str
    abspath: Path
    stem: str
    ext: str
    is_hd: bool
    top: bool


class Skin:
    def __init__(self, name: str, root: Path):
        self.name = name
        self.root = Path(root)
        self.files: "list[SkinFile]" = []
        self.ini_text = ""
        self.ini: IniDocument = IniDocument()
        self._scan()

    def _scan(self) -> None:
        for dirpath, _dirs, filenames in os.walk(self.root):
            for fn in filenames:
                ap = Path(dirpath) / fn
                rel = ap.relative_to(self.root).as_posix()
                name, ext = os.path.splitext(fn)
                is_hd = name.endswith("@2x")
                if is_hd:
                    name = name[:-3]
                self.files.append(SkinFile(
                    rel=rel, abspath=ap, stem=name.lower(), ext=ext.lower(),
                    is_hd=is_hd, top=("/" not in rel)))
        self.files.sort(key=lambda f: f.rel)
        ini_path = self.root / "skin.ini"
        if ini_path.is_file():
            try:
                self.ini_text = ini_path.read_text(encoding="utf-8-sig",
                                                   errors="replace")
            except OSError:
                self.ini_text = ""
            self.ini = IniDocument(self.ini_text)

    def top_images(self):
        return [f for f in self.files if f.top and f.ext in IMAGE_EXT]

    def top_sounds(self):
        return [f for f in self.files if f.top and f.ext in SOUND_EXT]

    def top_others(self):
        return [f for f in self.files
                if f.top and f.ext not in IMAGE_EXT and f.ext not in SOUND_EXT
                and f.rel != "skin.ini"]


def image_elements(skin: "Skin"):
    out: "OrderedDict[str, list[SkinFile]]" = OrderedDict()
    for f in skin.top_images():
        logical = re.sub(r"-\d+$", "", f.stem)
        logical = re.sub(r"^sliderb\d+$", "sliderb", logical)
        out.setdefault(logical, []).append(f)
    return out


def sound_elements(skin: "Skin"):
    out: "OrderedDict[str, list[SkinFile]]" = OrderedDict()
    for f in skin.top_sounds():
        out.setdefault(f.stem, []).append(f)
    return out


# ---------------------------------------------------------------------------
# Merge options + planning
# ---------------------------------------------------------------------------

@dataclass
class Plan:
    files: "OrderedDict[str, Path]" = field(default_factory=OrderedDict)
    origins: "dict[str, str]" = field(default_factory=dict)
    notes: "list[str]" = field(default_factory=list)

    def add(self, rel: str, src: Path, side: str) -> None:
        self.files[rel] = src
        self.origins[rel] = side


@dataclass
class Options:
    # ---- fusion type ----
    mode_fusion: bool = False
    modes: list = field(default_factory=list)
    separate_av: bool = False
    mode_image: dict = field(default_factory=dict)   # mode -> Skin
    mode_sound: dict = field(default_factory=dict)   # mode -> Skin
    base_mode: str = "standard"

    # ---- two-skin fusion ----
    gameplay: "Skin" = None
    art: "Skin" = None

    # ---- generic source registries: key -> Skin ----
    image_sources: "OrderedDict[str, Skin]" = field(default_factory=OrderedDict)
    sound_sources: "OrderedDict[str, Skin]" = field(default_factory=OrderedDict)

    # ---- per-item choices ----
    image_source: str = "auto"          # 'auto' or a source key
    sound_source: str = "auto"          # 'auto' or a source key (all-in-one)
    sound_preset: str = "hitsound_gameplay"  # two-skin presets
    ui_sound_source: str = ""           # all-in-one: source for interface sounds
    element_overrides: dict = field(default_factory=dict)   # logical -> key
    sound_overrides: dict = field(default_factory=dict)     # stem -> key

    ini_base: str = "smart"

    identity: dict = field(default_factory=lambda: {
        "name": {"choice": "C", "custom": ""},
        "author": {"choice": "C", "custom": "osu_skin_fuser"},
        "version": {"choice": "C", "custom": ""},
    })
    out_dir: str = "FusedSkins"
    export_mode: str = "osk"          # 'osk' | 'folder' | 'both'
    _ini_merge: object = None

    # -- helpers -----------------------------------------------------------
    def label_of(self, key: str) -> str:
        if key == "gameplay":
            return "Gameplay"
        if key == "art":
            return "Art"
        return MODES.get(key, key)

    def short_of(self, key: str) -> str:
        return MODE_SHORT.get(key, key.upper())

    def base_key(self) -> str:
        return self.base_mode if self.mode_fusion else "gameplay"

    def ui_sound_key(self) -> str:
        """Source key used for interface / UI sounds (all-in-one)."""
        if self.ui_sound_source in self.sound_sources:
            return self.ui_sound_source
        if "art" in self.sound_sources:
            return "art"
        key = self.base_key()
        if key in self.sound_sources:
            return key
        return next(iter(self.sound_sources))

    def default_image_source(self, logical: str) -> str:
        if self.mode_fusion:
            mode = classify_mode_image(logical)
            if mode in self.image_sources:
                return mode
            # shared artwork -> a dedicated Art skin, if one was added
            if classify_image(logical)[0] == "art" and "art" in self.image_sources:
                return "art"
            if self.base_mode in self.image_sources:
                return self.base_mode
            return next(iter(self.image_sources))
        return "gameplay" if classify_image(logical)[0] == "gameplay" else "art"

    def choose_image_source(self, logical: str) -> str:
        ov = self.element_overrides.get(logical)
        if ov in self.image_sources:
            return ov
        if self.image_source != "auto" and self.image_source in self.image_sources:
            return self.image_source
        return self.default_image_source(logical)

    def default_sound_source(self, stem: str) -> str:
        if self.mode_fusion:
            kind = sound_kind(stem)
            if kind == "mode":
                # mode-only sounds (e.g. taiko-*) -> that mode's own source
                if "taiko" in self.sound_sources:
                    return "taiko"
                if self.base_mode in self.sound_sources:
                    return self.base_mode
                return next(iter(self.sound_sources))
            if kind == "interface":
                return self.ui_sound_key()
            # shared gameplay hitsounds -> base gameplay source
            if self.base_mode in self.sound_sources:
                return self.base_mode
            return next(iter(self.sound_sources))
        group = classify_sound(stem)
        p = self.sound_preset
        if p == "gameplay":
            return "gameplay"
        if p == "art":
            return "art"
        if p == "hitsound_art":
            return "gameplay" if group == "interface" else "art"
        return "gameplay" if group == "hitsound" else "art"

    def choose_sound_source(self, stem: str) -> str:
        ov = self.sound_overrides.get(stem)
        if ov in self.sound_sources:
            return ov
        if self.mode_fusion and self.sound_source != "auto" and \
                self.sound_source in self.sound_sources:
            return self.sound_source
        return self.default_sound_source(stem)


def finalize_two_skin(opts: Options) -> None:
    opts.mode_fusion = False
    opts.image_sources = OrderedDict([("gameplay", opts.gameplay),
                                      ("art", opts.art)])
    opts.sound_sources = OrderedDict([("gameplay", opts.gameplay),
                                      ("art", opts.art)])
    opts.image_source = "auto"
    opts.sound_source = "auto"
    opts.element_overrides.clear()
    opts.sound_overrides.clear()
    opts._ini_merge = None


def build_source_registries(opts: Options) -> None:
    opts.image_sources = OrderedDict(
        (m, opts.mode_image[m]) for m in opts.modes)
    opts.sound_sources = OrderedDict(
        (m, opts.mode_sound.get(m, opts.mode_image[m])) for m in opts.modes)
    opts.base_mode = "standard" if "standard" in opts.modes else opts.modes[0]
    apply_art_source(opts)


def apply_art_source(opts: Options) -> None:
    """Add (or remove) the optional All-in-One Art skin as a source."""
    opts.image_sources.pop("art", None)
    opts.sound_sources.pop("art", None)
    if opts.mode_fusion and opts.art is not None:
        opts.image_sources["art"] = opts.art
        opts.sound_sources["art"] = opts.art
    opts._ini_merge = None


def build_plan(opts: Options, merge: IniMerge) -> Plan:
    plan = Plan()

    # ---- images ----
    avail: "dict[str, dict[str, list[SkinFile]]]" = {}
    logicals = []
    for key, skin in opts.image_sources.items():
        for logical, files in image_elements(skin).items():
            if logical not in avail:
                avail[logical] = {}
                logicals.append(logical)
            avail[logical][key] = files
    for logical in logicals:
        sides = avail[logical]
        desired = opts.choose_image_source(logical)
        if desired not in sides:
            desired = next(iter(sides))
            plan.notes.append(f"[{logical}] only exists in '{desired}'; used it.")
        for f in sides[desired]:
            plan.add(f.rel, f.abspath, desired)

    # ---- sounds ----
    savail: "dict[str, dict[str, list[SkinFile]]]" = {}
    stems = []
    for key, skin in opts.sound_sources.items():
        for stem, files in sound_elements(skin).items():
            if stem not in savail:
                savail[stem] = {}
                stems.append(stem)
            savail[stem][key] = files
    for stem in stems:
        sides = savail[stem]
        desired = opts.choose_sound_source(stem)
        if desired not in sides:
            if opts.mode_fusion:
                # Never force-fill a sound from an unrelated skin: leave it out
                # so osu! uses its own default sound instead.
                plan.notes.append(
                    f"[{stem}] not found in '{desired}'; left blank "
                    f"(osu! default).")
                continue
            desired = next(iter(sides))
        for f in sides[desired]:
            plan.add(f.rel, f.abspath, desired)

    # ---- other top-level files (from the primary source) ----
    primary = opts.image_sources.get(opts.base_key())
    if primary is None and opts.image_sources:
        primary = next(iter(opts.image_sources.values()))
    if primary is not None:
        for f in primary.top_others():
            if f.rel not in plan.files:
                plan.add(f.rel, f.abspath, opts.base_key())

    # ---- skin.ini referenced assets (fonts / mania images in sub folders) ----
    for entry in merge.resolved_path_entries():
        val = merge.resolve(entry)
        skin = merge.source_skins.get(entry.choice)
        key = entry.choice
        if skin is None:  # custom value: search every source
            for k, s in opts.image_sources.items():
                files, corrected = collect_referenced_files(s, val, entry.is_path)
                if files:
                    skin, key = s, k
                    break
            if skin is None:
                plan.notes.append(
                    f"[ini] {entry.section}.{entry.key} references '{val}' "
                    f"which was not found in any source skin.")
                continue
        files, corrected = collect_referenced_files(skin, val, entry.is_path)
        if files:
            for f in files:
                plan.add(f.rel, f.abspath, key)
            if corrected and corrected != val:
                merge.rename_resolved_path(entry, corrected)
        else:
            plan.notes.append(
                f"[ini] {entry.section}.{entry.key} references '{val}' "
                f"which was not found in {skin.name}.")
    return plan


def collect_referenced_files(skin: Skin, value: str, mode: str):
    if not value:
        return [], value
    norm = value.replace("\\", "/").strip()
    norm = re.sub(r"\.(png|jpg|jpeg)$", "", norm, flags=re.IGNORECASE)
    norm = re.sub(r"@2x$", "", norm, flags=re.IGNORECASE)
    low = norm.lower()
    matches = []
    for f in skin.files:
        if f.ext not in IMAGE_EXT:
            continue
        stem_rel = f.rel[:-len(f.ext)] if f.ext else f.rel
        stem_rel = re.sub(r"@2x$", "", stem_rel, flags=re.IGNORECASE)
        s = stem_rel.lower()
        if mode == "exact":
            if s == low:
                matches.append(f)
        else:
            if s == low or s.startswith(low + "-"):
                matches.append(f)
            elif s.startswith(low) and len(s) > len(low) and s[len(low)].isdigit():
                matches.append(f)
    if not matches:
        return [], value
    matches.sort(key=lambda f: f.rel)
    return matches, matches[0].rel[:len(norm)]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

INVALID_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_name(name: str) -> str:
    cleaned = INVALID_FS.sub("_", name).strip().strip(".")
    return cleaned or "FusedSkin"


def resolve_identity(opts: Options, key: str) -> str:
    spec = opts.identity[key]
    choice = spec.get("choice", "C")
    if choice != "C":
        skin = opts.image_sources.get(choice) or opts.sound_sources.get(choice)
        if skin is not None:
            val = skin.ini.identity.get(key)
            if val:
                return val
    custom = (spec.get("custom") or "").strip()
    if custom:
        return custom
    if key == "name":
        if opts.mode_fusion:
            return "All-in-One " + "+".join(opts.modes)
        if opts.gameplay and opts.art:
            return f"{opts.gameplay.name} x {opts.art.name}"
        return "Fused Skin"
    if key == "author":
        return "osu_skin_fuser"
    base = opts.image_sources.get(opts.base_key())
    if base is not None and base.ini.identity.get("version"):
        return base.ini.identity["version"]
    return "latest"


def export_skin(opts: Options, plan: Plan, ini_text: str, log=print,
                progress=None) -> Path:
    mode = getattr(opts, "export_mode", "osk")
    keep_folder = mode in ("folder", "both")
    want_osk = mode in ("osk", "both")
    out_root = Path(opts.out_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    folder_name = sanitize_name(resolve_identity(opts, "name"))
    dest = out_root / folder_name
    if keep_folder:
        if dest.exists():
            log(f"  ! {dest} already exists, merging into it.")
        dest.mkdir(parents=True, exist_ok=True)
        staging = dest
    else:
        # ".osk only": assemble in a throwaway folder, then delete it.
        staging = Path(tempfile.mkdtemp(prefix="osk_build_"))

    items = list(plan.files.items())
    steps = [rel for rel, _src in items] + ["skin.ini"]
    if want_osk:
        steps.append(f"{folder_name}.osk")
    total = max(1, len(steps))
    counter = {"step": 0}

    def advance(name: str) -> None:
        counter["step"] += 1
        if progress is not None:
            progress(counter["step"], total, name)

    copied = 0
    for rel, src in items:
        advance(rel)
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, target)
            copied += 1
        except OSError as exc:
            log(f"  ! failed to copy {rel}: {exc}")

    advance("skin.ini")
    (staging / "skin.ini").write_text(ini_text, encoding="utf-8")
    log(f"  copied {copied} files")

    osk_path = None
    if want_osk:
        advance(f"{folder_name}.osk")
        osk_path = out_root / f"{folder_name}.osk"
        log(f"  packing {osk_path.name} ...")
        with zipfile.ZipFile(osk_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(staging).as_posix())
        log(f"  wrote {osk_path}")

    if not keep_folder:
        shutil.rmtree(staging, ignore_errors=True)

    if want_osk and not keep_folder:
        return osk_path
    return dest


def summarize(opts: Options, plan: Plan) -> str:
    from collections import Counter
    origins = Counter(plan.origins.values())
    lines = []
    if opts.mode_fusion:
        lines.append("Fusion type   : All-in-One (mode fusion)")
        lines.append("Modes         : " + ", ".join(MODES[m] for m in opts.modes))
        for m in opts.modes:
            img = opts.image_sources.get(m)
            snd = opts.sound_sources.get(m)
            lines.append(f"  {MODES[m]:13s} images = {img.name if img else '-'}"
                         f"   sounds = {snd.name if snd else '-'}")
        art = opts.image_sources.get("art")
        lines.append(f"Art skin      : {art.name if art else '(reusing mode sources)'}")
        lines.append(f"UI sound src  : {opts.label_of(opts.ui_sound_key())}"
                     f"  ({opts.sound_sources[opts.ui_sound_key()].name})")
    else:
        lines.append("Fusion type   : Gameplay + Art")
        lines.append(f"Gameplay skin : {opts.gameplay.name if opts.gameplay else '-'}")
        lines.append(f"Art skin      : {opts.art.name if opts.art else '-'}")
    lines.append(f"Image source  : {opts.image_source}")
    if opts.mode_fusion:
        lines.append(f"Sound source  : {opts.sound_source}")
    else:
        lines.append(f"Sound preset  : {opts.sound_preset}")
    lines.append(f"skin.ini base : {opts.ini_base}")
    lines.append(f"Name          : {resolve_identity(opts, 'name')}")
    lines.append(f"Author        : {resolve_identity(opts, 'author')}")
    lines.append(f"Version       : {resolve_identity(opts, 'version')}")
    lines.append(f"Output        : {Path(opts.out_dir).resolve()}")
    lines.append(f"Export mode   : "
                 f"{EXPORT_MODES.get(opts.export_mode, opts.export_mode)}")
    lines.append("")
    counts = ", ".join(f"{k} {origins[k]}" for k in origins)
    lines.append(f"Files to copy : {len(plan.files)}  ({counts})")
    if plan.notes:
        lines.append("")
        lines.append("Notes:")
        lines.extend("  - " + n for n in plan.notes[:25])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Skin discovery
# ---------------------------------------------------------------------------

def default_skin_dirs() -> list:
    here = Path(__file__).resolve().parent
    cwd = Path.cwd()
    cands = []
    for base in (cwd, here, cwd / "Skins", here / "Skins"):
        if base.is_dir() and base not in cands:
            cands.append(base)
    return cands


def discover_skins(dirs) -> "list[Skin]":
    found = OrderedDict()
    for base in dirs:
        base = Path(base).expanduser()
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            has_ini = (child / "skin.ini").is_file()
            try:
                has_media = any(
                    p.suffix.lower() in IMAGE_EXT | SOUND_EXT
                    for p in child.iterdir() if p.is_file())
            except OSError:
                has_media = False
            if has_ini or has_media:
                key = str(child.resolve())
                if key not in found:
                    found[key] = Skin(child.name, child)
    return list(found.values())


def load_skin_arg(value: str, tmpdirs: list) -> Skin:
    p = Path(value).expanduser()
    if p.is_file() and p.suffix.lower() == ".osk":
        extract = Path(tempfile.mkdtemp(prefix="osk_"))
        tmpdirs.append(extract)
        with zipfile.ZipFile(p) as zf:
            zf.extractall(extract)
        children = [c for c in extract.iterdir()]
        if len(children) == 1 and children[0].is_dir():
            return Skin(p.stem, children[0])
        return Skin(p.stem, extract)
    if p.is_dir():
        return Skin(p.resolve().name, p)
    raise FileNotFoundError(f"Not a skin folder or .osk file: {value}")


# ---------------------------------------------------------------------------
# TUI (curses)
# ---------------------------------------------------------------------------

def _char_width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _display_width(text: str) -> int:
    return sum(_char_width(c) for c in text)


def _fit(text: str, width: int) -> str:
    if width <= 0:
        return ""
    out = []
    used = 0
    for ch in text:
        cw = _char_width(ch)
        if used + cw > width:
            break
        out.append(ch)
        used += cw
    return "".join(out)


def _norm_hint_key(key: str) -> str:
    """Uppercase a hotkey, dropping single-letter alternatives ("ESC/q")."""
    key = key.replace(" ", "")
    if len(key) > 1 and "/" in key:
        segs = key.split("/")
        keep = [segs[0]] + [s for s in segs[1:] if len(s) > 1]
        key = "/".join(keep)
    if key.lower() == "q":
        key = "ESC"          # ESC and q do the same thing
    return key.upper()


def _format_hints(text: str) -> str:
    """Normalise a status-bar hint line to "KEY=Label" (keys uppercase)."""
    out = []
    for part in re.split(r"\s{2,}", text.strip()):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, label = part.split("=", 1)
            key = _norm_hint_key(key)
            label = label.strip()
            if label:
                label = label[0].upper() + label[1:]
            out.append(f"{key}={label}" if label else key)
        else:
            out.append(part)
    return "   ".join(out)


def _spread(lines, w: int):
    """On wide terminals, merge runs of plain body lines into wrapped paragraphs.

    At 80x25 (``w <= 90``) the caller's hand-broken lines are returned as-is so
    the fixed layout is preserved; on wider screens the text re-flows to fill the
    screen instead of hugging the left edge.
    """
    if w <= 90:
        return lines
    wrap_w = max(20, w - 8)
    out = []
    buf = []

    def flush():
        if not buf:
            return
        para = " ".join(s.strip() for s in buf)
        for seg in (textwrap.wrap(para, wrap_w) or [""]):
            out.append((seg, "normal"))
        buf.clear()

    for text, kind in lines:
        if not text:
            flush()
            out.append(("", kind))
        elif kind != "normal" or text[:1].isspace():
            flush()
            out.append((text, kind))
        else:
            buf.append(text)
    flush()
    return out


class Cancelled(Exception):
    pass


class QuitApp(Exception):
    """Raised when the user presses F3 to quit Setup immediately."""
    pass

# Original texts generated by AI, manually changed the layouts so it fits the 80x25 screen better.

'''
HELP_TEXT = """\
osu! AIO Skin Fuser - Setup Help

NAVIGATION
  Up / Down  (K / J)      move the selection
  Home / End (G)          jump to the first / last item
  Page Up / Page Down     move ten items
  ENTER                   activate the highlighted item
  SPACE                   same as ENTER in the settings lists
  /                       search inside a list
  ESC or q                go back to the previous step
  F1                      show this help page
  F3                      ask to quit Setup (press F3 again to confirm)
  F5                      remove / restore colour

EDITING LISTS
  Images, sounds and skin.ini are shown as a settings list.  Move to a row and
  press ENTER to open a small dialog where you pick a new value, then press
  ENTER to apply it (ESC keeps the old value).  Every list ends with a single
  "Done" row - press ENTER on it to finish the list.

EXPORT DETAILS
  The final screen is laid out like the Windows Setup "System Information" page.
  Move to an item and press ENTER to change it; when everything is correct move
  to "No Changes:  The above list matches my choice." and press ENTER.

WIZARD
  1. Read the welcome page (ENTER continues; F1 works here too), then on the
     Setup-method page press ENTER for Gameplay + Art fusion or C for
     All-in-One mode fusion.
  2. Choose the source skin(s).  "Enter your osu skin directory path..." scans
     a folder once; every later picker stays in that same directory.
  3. Fine-tune images, sounds and skin.ini (see EDITING LISTS above).
  4. Set the export name / author / version on the Export Details page, then
     press ENTER on "No Changes" - Setup starts copying right away.

If a chosen source does not contain a sound or image, the item is left out so
osu! falls back to its own default instead of borrowing it from another skin.
"""
'''

HELP_TEXT = """\
osu! AIO Skin Fuser - Setup Help

NAVIGATION
  Up / Down  (K / J)      move the selection
  Home / End (G)          jump to the first / last item
  Page Up / Page Down     move ten items
  ENTER                   activate the highlighted item
  SPACE                   same as ENTER in the settings lists
  /                       search inside a list
  ESC or q                go back to the previous step
  F1                      show this help page
  F3                      ask to quit Setup (press F3 again to confirm)
  F5                      remove / restore colour

EDITING LISTS
  Images, sounds and skin.ini are shown as a settings list.  Move to a row and press ENTER to open a small dialog where you pick a new value, then press ENTER to apply it (ESC keeps the old value).  Every list ends with a single "Done" row - press ENTER on it to finish the list.

EXPORT DETAILS
  The final screen is laid out like the original Windows Setup "System Information" page. Move to an item and press ENTER to change it; when everything is correct move
  to "No Changes:  The above list matches my choice." and press ENTER.

WIZARD
  1. Read the welcome page (ENTER continues; F1 works here too), then on the Setup-method page press ENTER for Gameplay + Art fusion or C for All-in-One mode fusion.
  2. Choose the source skin(s).  "Enter your osu skin directory path..." scans a folder once; every later picker stays in that same directory.
  3. Fine-tune images, sounds and skin.ini (see EDITING LISTS above).
  4. Set the export name / author / version on the Export Details page, then press ENTER on "No Changes" - Setup starts copying right away.

If a chosen source does not contain a sound or image, the item is left out so osu! falls back to its own default instead of borrowing it from another skin.
"""


class UI:
    def __init__(self):
        self.scr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        self.scr.keypad(True)
        try:
            # Make a lone Escape key arrive promptly instead of waiting for a
            # possible function-key escape sequence.
            curses.set_escdelay(25)
        except (AttributeError, curses.error):
            pass
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.colors = False
        self.mono = False
        try:
            curses.start_color()
            try:
                curses.use_default_colors()
            except curses.error:
                pass
            # Normal blue backdrop (as before) with an intense yellow bar.
            ncol = getattr(curses, "COLORS", 8) or 8
            bg = curses.COLOR_BLUE
            bar = 11 if ncol >= 16 else curses.COLOR_YELLOW   # bright yellow
            try:
                if curses.can_change_color():
                    curses.init_color(bar, 1000, 1000, 333)   # light yellow
            except curses.error:
                pass
            curses.init_pair(1, curses.COLOR_WHITE, bg)   # normal
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)  # selected
            curses.init_pair(3, curses.COLOR_WHITE, bg)   # hint
            curses.init_pair(4, curses.COLOR_WHITE, bg)   # header
            curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_WHITE)  # status bar
            curses.init_pair(6, bar, bg)                  # accent (progress bar)
            curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE)  # inverted
            curses.init_pair(8, curses.COLOR_BLUE, curses.COLOR_WHITE)   # inverted head
            curses.init_pair(9, curses.COLOR_RED, curses.COLOR_WHITE)    # alert text
            self.colors = curses.has_colors()
        except curses.error:
            self.colors = False
        self.apply_background()

    def apply_background(self):
        try:
            self.scr.bkgdset(" ", self.a("normal"))
        except curses.error:
            pass

    def toggle_mono(self):
        self.mono = not self.mono
        self.apply_background()

    def a(self, kind):
        """Return the attribute for a UI element (respects F5 mono mode)."""
        colored = self.colors and not self.mono
        if kind == "normal":
            return curses.color_pair(1) if colored else 0
        if kind == "sel":
            return curses.color_pair(2) if colored else curses.A_REVERSE
        if kind == "hint":
            return (curses.color_pair(3) | curses.A_BOLD) if colored else curses.A_DIM
        if kind == "header":
            return (curses.color_pair(4) | curses.A_BOLD) if colored else curses.A_BOLD
        if kind == "status":
            return curses.color_pair(5) if colored else curses.A_REVERSE
        if kind == "accent":
            return curses.color_pair(6) if colored else curses.A_BOLD
        if kind == "inv":
            return curses.color_pair(7) if colored else curses.A_REVERSE
        if kind == "inv_head":
            return (curses.color_pair(8) | curses.A_BOLD) if colored \
                else (curses.A_REVERSE | curses.A_BOLD)
        if kind == "inv_red":
            return (curses.color_pair(9) | curses.A_BOLD) if colored \
                else (curses.A_REVERSE | curses.A_BOLD)
        if kind == "inv_dark_red":
            return curses.color_pair(9) if colored else curses.A_REVERSE
        return 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        self.scr.keypad(False)
        curses.echo()
        curses.nocbreak()
        curses.endwin()

    def safe(self, y, x, text, attr=0):
        h, w = self.scr.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        text = _fit(text, w - x - 1)
        if not text:
            return
        try:
            self.scr.addstr(y, x, text, attr)
        except curses.error:
            pass

    def key(self):
        try:
            k = self.scr.get_wch()
        except curses.error:
            return None
        except KeyboardInterrupt:
            raise Cancelled()
        # get_wch() reports a lone Escape as the string "\x1b", while every
        # screen tests for the integer 27.  Normalise so ESC works everywhere.
        if k == "\x1b" or k == 27:
            return 27
        return k

    def key_nonblock(self):
        """Return a key if one is waiting, otherwise None."""
        self.scr.nodelay(True)
        try:
            return self.key()
        finally:
            self.scr.nodelay(False)


def _is(k, *cands):
    return any(k == c for c in cands)


def _center_top(cursor: int, n: int, box_items: int) -> int:
    """Scroll offset that keeps the highlighted row near the middle.

    The highlight only drifts towards the top/bottom of the box once the list
    itself has reached its first/last row.
    """
    if n <= box_items or box_items <= 0:
        return 0
    half = (box_items - 1) // 2
    return max(0, min(cursor - half, n - box_items))


def draw_chrome(ui: UI):
    """Title one line down, with a double rule that touches the left edge."""
    ui.safe(1, 2, APP_TITLE, ui.a("header"))
    # The rule starts at column 0 and reaches the title's own right edge.
    ui.safe(2, 0, "═" * (2 + _display_width(APP_TITLE)), ui.a("normal"))


def _fill_row(ui: UI, y: int, attr):
    """Paint a whole row (all columns, including the special last cell)."""
    _h, w = ui.scr.getmaxyx()
    if w <= 0 or y < 0 or y >= _h:
        return
    ui.safe(y, 0, " " * max(0, w - 1), attr)
    # ncurses answers ERR when you touch the very last cell, but the virtual
    # screen still records the attribute, so the corner ends up coloured too.
    try:
        ui.scr.addch(y, w - 1, " ", attr)
    except curses.error:
        pass


def fill_screen(ui: UI, attr):
    """Flood the whole screen with one attribute (inverted help page)."""
    h, _w = ui.scr.getmaxyx()
    for y in range(h):
        _fill_row(ui, y, attr)


def _fill_status_row(ui: UI, attr):
    """Paint the whole bottom row, including the special lower-right cell."""
    _h, _w = ui.scr.getmaxyx()
    _fill_row(ui, _h - 1, attr)


def draw_status(ui: UI, left: str):
    """DOS-style status bar: every key hint on the left, then a black divider."""
    _h, w = ui.scr.getmaxyx()
    avail = max(0, w - 1)
    keys = "F1=Help   F3=Exit   F5=Remove Color"
    if left and "F1=" in left:
        text = left.strip()
    elif left and left.strip():
        text = left.strip() + "   " + keys
    else:
        text = keys
    text = _fit(_format_hints(text), max(0, avail - 3))
    _fill_status_row(ui, ui.a("status"))
    ui.safe(_h - 1, 1, text, ui.a("status"))
    text_end = 1 + _display_width(text)
    # put the small black divider at roughly 75% of the width
    bar_x = max(int(avail * 0.75), text_end + 1)
    bar_x = min(bar_x, avail - 1)
    if bar_x > text_end:
        ui.safe(_h - 1, bar_x, "│", ui.a("status"))


def render_menu(ui: UI, title, items, footer, cursor, top=None,
                subtitle="", multi=False, checked=None):
    ui.scr.erase()
    h, w = ui.scr.getmaxyx()
    draw_chrome(ui)
    if title and title != APP_TITLE:
        ui.safe(4, 2, title, ui.a("header"))
    if subtitle:
        ui.safe(5, 3, _fit(subtitle, max(0, w - 6)), ui.a("hint"))
    body_top = 7 if not subtitle else 8
    # Leave the last row free for the status bar so the bottom border of the
    # box always stays on screen.
    max_items = max(1, (h - 2) - body_top)
    n = len(items)
    box_items = min(max_items, max(1, n))
    top = _center_top(cursor, n, box_items)

    box_left = 2
    box_right = w - 3
    if box_right <= box_left + 1:
        draw_status(ui, footer)
        ui.scr.refresh()
        return
    inner = box_right - box_left - 1
    box_top = body_top - 1
    box_bottom = box_top + box_items + 1
    ui.safe(box_top, box_left, "┌" + "─" * inner + "┐", ui.a("normal"))
    ui.safe(box_bottom, box_left, "└" + "─" * inner + "┘", ui.a("normal"))
    for r in range(box_top + 1, box_bottom):
        ui.safe(r, box_left, "│", ui.a("normal"))
        ui.safe(r, box_right, "│", ui.a("normal"))

    for idx in range(box_items):
        i = top + idx
        if i >= n:
            break
        y = box_top + 1 + idx
        label, hint = items[i]
        mark = ""
        if multi and checked is not None:
            mark = "[x] " if i in checked else "[ ] "
        lab = " " + mark + label
        if i == cursor:
            # Fill the row with the highlight, but keep the label on the left
            # and the hint right-aligned exactly like the unselected rows.
            ui.safe(y, box_left + 1, " " * inner, ui.a("sel"))
            lab_fit = _fit(lab, inner)
            ui.safe(y, box_left + 1, lab_fit, ui.a("sel"))
            if hint:
                lab_w = _display_width(lab_fit)
                hx = box_right - _display_width(hint) - 2
                if hx > box_left + 1 + lab_w + 1:
                    ui.safe(y, hx, hint, ui.a("sel"))
                else:
                    # No room to right-align; show it just after the label.
                    tail_x = box_left + 1 + lab_w + 3
                    if tail_x < box_right - 1:
                        ui.safe(y, tail_x,
                                _fit(hint, box_right - 1 - tail_x),
                                ui.a("sel"))
        else:
            ui.safe(y, box_left + 1, _fit(lab, inner), ui.a("normal"))
            if hint:
                hx = box_right - _display_width(hint) - 2
                if hx > box_left + 1 + _display_width(lab) + 1:
                    ui.safe(y, hx, hint, ui.a("hint"))
    if n > box_items:
        ind = f"[{cursor + 1}/{n}]"
        ui.safe(4, max(0, w - _display_width(ind) - 3), ind, ui.a("hint"))
    draw_status(ui, footer)
    ui.scr.refresh()


def menu(ui: UI, title, items, footer, multi=False, checked=None, subtitle=""):
    if not items:
        return []
    cursor = 0
    top = 0
    checked = set(checked or [])
    while True:
        render_menu(ui, title, items, footer, cursor, top, subtitle=subtitle,
                    multi=multi, checked=checked if multi else None)
        k = ui.key()
        if k is None:
            continue
        if k == curses.KEY_F1:
            show_help(ui)
            continue
        if k == curses.KEY_F5:
            ui.toggle_mono()
            continue
        if k == curses.KEY_F3:
            confirm_quit(ui)
        if _is(k, curses.KEY_UP, "k"):
            cursor = (cursor - 1) % len(items)
        elif _is(k, curses.KEY_DOWN, "j"):
            cursor = (cursor + 1) % len(items)
        elif k == curses.KEY_HOME or _is(k, "g"):
            cursor = 0
        elif k == curses.KEY_END or _is(k, "G"):
            cursor = len(items) - 1
        elif k == curses.KEY_PPAGE:
            cursor = max(0, cursor - 10)
        elif k == curses.KEY_NPAGE:
            cursor = min(len(items) - 1, cursor + 10)
        elif k == " " and multi:
            checked.discard(cursor) if cursor in checked else checked.add(cursor)
        elif k == "a" and multi:
            checked = set(range(len(items)))
        elif k == "n" and multi:
            checked = set()
        elif k in (curses.KEY_ENTER, "\n", "\r", curses.KEY_RIGHT):
            return sorted(checked) if multi else [cursor]
        elif k in (27, "q", curses.KEY_LEFT):
            return None


def menu_cursor(ui: UI, title, items, subtitle, cursor, footer,
                search_allowed=False):
    top = 0
    cursor = max(0, min(cursor, len(items) - 1)) if items else 0
    while True:
        render_menu(ui, title, items, footer, cursor, top, subtitle=subtitle)
        k = ui.key()
        if k is None:
            continue
        if k == curses.KEY_F1:
            show_help(ui)
            continue
        if k == curses.KEY_F5:
            ui.toggle_mono()
            continue
        if k == curses.KEY_F3:
            confirm_quit(ui)
        if k == curses.KEY_UP or _is(k, "k"):
            cursor = (cursor - 1) % len(items)
        elif k == curses.KEY_DOWN or _is(k, "j"):
            cursor = (cursor + 1) % len(items)
        elif k == curses.KEY_HOME or _is(k, "g"):
            cursor = 0
        elif k == curses.KEY_END or _is(k, "G"):
            cursor = len(items) - 1
        elif k == "/" and search_allowed:
            return {"action": "search", "cursor": cursor}
        elif k == " ":
            return {"action": "space", "cursor": cursor}
        elif k in (curses.KEY_ENTER, "\n", "\r"):
            return {"action": "done", "cursor": cursor}
        elif k in (27, "q"):
            return {"action": "cancel", "cursor": cursor}


def dialog_select(ui: UI, title, prompt_lines, options, cursor=0):
    """A modal framed list, like the Windows Setup option dialogs.

    Returns the chosen index, or None if cancelled with ESC / q.
    """
    top = 0
    cursor = max(0, min(cursor, len(options) - 1)) if options else 0
    while True:
        ui.scr.erase()
        h, w = ui.scr.getmaxyx()
        draw_chrome(ui)
        row = 4
        if title and title != APP_TITLE:
            ui.safe(row, 2, _fit(title, max(0, w - 4)), ui.a("header"))
            row += 1
        row += 1
        for line in (prompt_lines or []):
            for wrapped in (textwrap.wrap(line, max(20, w - 7)) or [""]):
                ui.safe(row, 3, wrapped, ui.a("normal"))
                row += 1
        row += 1
        box_top = row
        box_left = 2
        box_right = w - 3
        n = len(options)
        if box_right <= box_left + 1 or box_top + 1 >= h - 1 or n == 0:
            draw_status(ui, "ENTER=Continue   ESC=Cancel")
            ui.scr.refresh()
            k = ui.key()
            if k == curses.KEY_F3:
                confirm_quit(ui)
            if k in (27, "q"):
                return None
            if k in (curses.KEY_ENTER, "\n", "\r") and n:
                return cursor
            continue
        inner = box_right - box_left - 1
        max_items = max(1, (h - 2) - box_top - 1)
        box_items = min(max_items, max(1, n))
        top = _center_top(cursor, n, box_items)
        box_bottom = box_top + box_items + 1
        ui.safe(box_top, box_left, "┌" + "─" * inner + "┐", ui.a("normal"))
        ui.safe(box_bottom, box_left, "└" + "─" * inner + "┘", ui.a("normal"))
        for r in range(box_top + 1, box_bottom):
            ui.safe(r, box_left, "│", ui.a("normal"))
            ui.safe(r, box_right, "│", ui.a("normal"))
        for idx in range(box_items):
            i = top + idx
            if i >= n:
                break
            y = box_top + 1 + idx
            label, _hint = options[i]
            if i == cursor:
                seg = _fit(" " + label, inner)
                ui.safe(y, box_left + 1, seg, ui.a("sel"))
                pad = inner - _display_width(seg)
                if pad > 0:
                    ui.safe(y, box_left + 1 + _display_width(seg), " " * pad,
                            ui.a("sel"))
            else:
                ui.safe(y, box_left + 1, _fit(" " + label, inner), ui.a("normal"))
        if n > box_items:
            ind = f"[{cursor + 1}/{n}]"
            ui.safe(box_top, max(box_left + 2,
                                 box_right - _display_width(ind) - 1),
                    ind, ui.a("hint"))
        draw_status(ui, "ENTER=Continue   ESC=Cancel")
        ui.scr.refresh()
        k = ui.key()
        if k is None:
            continue
        if k == curses.KEY_F1:
            show_help(ui)
            continue
        if k == curses.KEY_F5:
            ui.toggle_mono()
            continue
        if k == curses.KEY_F3:
            confirm_quit(ui)
        if k in (curses.KEY_UP, "k"):
            cursor = (cursor - 1) % n
        elif k in (curses.KEY_DOWN, "j"):
            cursor = (cursor + 1) % n
        elif k in (curses.KEY_HOME, "g"):
            cursor = 0
        elif k in (curses.KEY_END, "G"):
            cursor = n - 1
        elif k == curses.KEY_PPAGE:
            cursor = max(0, cursor - 10)
        elif k == curses.KEY_NPAGE:
            cursor = min(n - 1, cursor + 10)
        elif k in (curses.KEY_ENTER, "\n", "\r"):
            return cursor
        elif k in (27, "q"):
            return None


def work_list(ui: UI, title, items, subtitle, cursor, footer,
              search_allowed=False):
    """Like menu_cursor, but ENTER/SPACE *activate* the row instead of ending."""
    top = 0
    if not items:
        return {"action": "cancel", "cursor": 0}
    cursor = max(0, min(cursor, len(items) - 1))
    while True:
        render_menu(ui, title, items, footer, cursor, top, subtitle=subtitle)
        k = ui.key()
        if k is None:
            continue
        if k == curses.KEY_F1:
            show_help(ui)
            continue
        if k == curses.KEY_F5:
            ui.toggle_mono()
            continue
        if k == curses.KEY_F3:
            confirm_quit(ui)
        if k == curses.KEY_UP or _is(k, "k"):
            cursor = (cursor - 1) % len(items)
        elif k == curses.KEY_DOWN or _is(k, "j"):
            cursor = (cursor + 1) % len(items)
        elif k == curses.KEY_HOME or _is(k, "g"):
            cursor = 0
        elif k == curses.KEY_END or _is(k, "G"):
            cursor = len(items) - 1
        elif k == curses.KEY_PPAGE:
            cursor = max(0, cursor - 10)
        elif k == curses.KEY_NPAGE:
            cursor = min(len(items) - 1, cursor + 10)
        elif k == "/" and search_allowed:
            return {"action": "search", "cursor": cursor}
        elif k in (" ", curses.KEY_ENTER, "\n", "\r"):
            return {"action": "activate", "cursor": cursor}
        elif k in (27, "q", curses.KEY_LEFT):
            return {"action": "cancel", "cursor": cursor}


def text_input(ui: UI, title, prompt, default="", allow_empty=True):
    buf = list(default)
    pos = len(buf)
    while True:
        ui.scr.erase()
        h, w = ui.scr.getmaxyx()
        draw_chrome(ui)
        if title and title != APP_TITLE:
            ui.safe(4, 2, title, ui.a("header"))
        ui.safe(6, 3, _fit(prompt, max(0, w - 6)), ui.a("normal"))
        box_left = 2
        box_right = w - 3
        box_top = 8
        if box_right > box_left + 1 and box_top + 1 < h - 1:
            inner = box_right - box_left - 1
            ui.safe(box_top, box_left, "┌" + "─" * inner + "┐", ui.a("normal"))
            ui.safe(box_top + 2, box_left, "└" + "─" * inner + "┘",
                    ui.a("normal"))
            ui.safe(box_top + 1, box_left, "│", ui.a("normal"))
            ui.safe(box_top + 1, box_right, "│", ui.a("normal"))
            seg = _fit(" " + "".join(buf), inner)
            ui.safe(box_top + 1, box_left + 1, seg, ui.a("sel"))
            pad = inner - _display_width(seg)
            if pad > 0:
                ui.safe(box_top + 1, box_left + 1 + _display_width(seg),
                        " " * pad, ui.a("sel"))
        draw_status(ui, "ENTER=Continue   ESC=Cancel")
        try:
            ui.scr.move(box_top + 1, box_left + 2 + min(pos, max(0, w - 8)))
            curses.curs_set(1)
        except curses.error:
            pass
        ui.scr.refresh()
        k = ui.key()
        if k is None:
            continue
        if k == curses.KEY_F1:
            show_help(ui)
            continue
        if k == curses.KEY_F5:
            ui.toggle_mono()
            continue
        if k == curses.KEY_F3:
            confirm_quit(ui)
        if k in (curses.KEY_ENTER, "\n", "\r"):
            if buf or allow_empty:
                return "".join(buf)
        elif k == 27:
            return None
        elif k in (curses.KEY_BACKSPACE, "\b", "\x7f"):
            if pos > 0:
                del buf[pos - 1]
                pos -= 1
        elif k == curses.KEY_DC:
            if pos < len(buf):
                del buf[pos]
        elif k == curses.KEY_LEFT:
            pos = max(0, pos - 1)
        elif k == curses.KEY_RIGHT:
            pos = min(len(buf), pos + 1)
        elif isinstance(k, str) and k.isprintable():
            buf.insert(pos, k)
            pos += 1


def info(ui: UI, title, text, inverted=False):
    lines = []
    h, w = ui.scr.getmaxyx()
    wrap_w = max(20, w - (9 if inverted else 7))
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(para, wrap_w) or [""])
    top = 0
    while True:
        ui.scr.erase()
        h, w = ui.scr.getmaxyx()
        if inverted:
            fill_screen(ui, ui.a("inv"))
            head = _fit(title or "Help", max(0, w - 2))
            ui.safe(0, 0, head, ui.a("inv_head"))
            ui.safe(1, 0, "═" * (2 + _display_width(head)), ui.a("inv"))
            body_top = 3
            x = 2
        else:
            draw_chrome(ui)
            body_top = 4
            if title and title != APP_TITLE:
                ui.safe(4, 2, title, ui.a("header"))
                body_top = 5
            x = 3
        visible = max(1, (h - 1) - body_top)
        for i in range(visible):
            if top + i < len(lines):
                line = lines[top + i]
                if inverted:
                    line = _fit(line, max(0, w - x - 2))
                ui.safe(body_top + i, x, line,
                        ui.a("inv" if inverted else "normal"))
        if inverted:
            _draw_help_status(ui)
        else:
            draw_status(ui, "Up/Down=Scroll   ENTER=Continue")
        ui.scr.refresh()
        k = ui.key()
        if k is None:
            continue
        if k == curses.KEY_F5:
            ui.toggle_mono()
            continue
        if k == curses.KEY_F3:
            confirm_quit(ui)
        if k == curses.KEY_F1:
            continue
        if k == curses.KEY_UP:
            top = max(0, top - 1)
        elif k == curses.KEY_DOWN:
            top = min(max(0, len(lines) - visible), top + 1)
        elif k in (curses.KEY_ENTER, "\n", "\r", 27, "q"):
            return


def _draw_help_status(ui: UI):
    """Blue bar at the bottom of the inverted help page."""
    h, _w = ui.scr.getmaxyx()
    _fill_row(ui, h - 1, ui.a("normal"))
    ui.safe(h - 1, 1,
            _format_hints("ENTER=Close Help"),
            ui.a("normal"))


def show_help(ui: UI):
    """F1: the inverted (grey) Setup Help page."""
    info(ui, "Setup Help", HELP_TEXT, inverted=True)


def modal_box(ui: UI, lines, footer):
    """Draw a light-grey Setup dialog in the middle of the screen."""
    h, w = ui.scr.getmaxyx()
    box_w = min(w - 6, max(30, int(w * 0.62)))   # narrower, like Setup
    left = max(0, (w - box_w) // 2)
    right = min(w - 1, left + box_w - 1)
    inner = right - left - 1
    text_w = max(8, inner - 3)
    wrapped = []
    for line in lines:
        if not line.strip():
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, text_w) or [""])
    box_h = len(wrapped) + 4
    top = max(1, (h - box_h) // 2 - 3)      # sit a little above centre
    bottom = min(h - 2, top + box_h - 1)
    if bottom - top + 1 < box_h:
        top = max(0, bottom - box_h + 1)
    for y in range(top, bottom + 1):
        ui.safe(y, left, " " * (right - left + 1), ui.a("inv"))
    ui.safe(top, left, "╔" + "═" * inner + "╗", ui.a("inv_dark_red"))
    ui.safe(bottom, left, "╚" + "═" * inner + "╝", ui.a("inv_dark_red"))
    for y in range(top + 1, bottom):
        ui.safe(y, left, "║", ui.a("inv_dark_red"))
        ui.safe(y, right, "║", ui.a("inv_dark_red"))
    y = top + 1
    for line in wrapped:
        ui.safe(y, left + 2, _fit(line, text_w), ui.a("inv_dark_red"))
        y += 1
    # Separator line above the footer, like the original Setup dialog.
    ui.safe(y, left + 1, "─" * inner, ui.a("inv_dark_red"))
    y += 1
    ui.safe(y, left + 2, _fit(_format_hints(footer), text_w),
            ui.a("inv_dark_red"))
    ui.scr.refresh()


def confirm_quit(ui: UI):
    """F3 confirmation box: ENTER keeps going, F3 again really quits."""
    lines = [
        "This skin is not completely set up on your system. If you quit "
        "Setup now, you will need to run Setup again to build the skin.",
        "",
        "  • Press ENTER to continue Setup.",
        "  • Press F3 to quit Setup.",
    ]
    footer = "F3=Exit    ENTER=Continue"
    modal_box(ui, lines, footer)
    while True:
        k = ui.key()
        if k is None:
            continue
        if k == curses.KEY_F5:
            ui.toggle_mono()
            modal_box(ui, lines, footer)
            continue
        if k == curses.KEY_F3:
            raise QuitApp()
        return


def confirm(ui: UI, title, question):
    res = menu(ui, title, [("Yes", ""), ("No", "")],
               "Enter = select   q = back")
    return bool(res) and res[0] == 0


def text_page(ui: UI, title, lines, footer, chars=""):
    """A static Windows Setup style page.

    ``lines`` is a list of ``(text, kind)`` pairs; an empty text is a blank
    line.  Returns "enter", a key from ``chars`` (lower-cased) or "back".
    """
    while True:
        ui.scr.erase()
        h, w = ui.scr.getmaxyx()
        draw_chrome(ui)
        row = 4
        if title and title != APP_TITLE:
            ui.safe(row, 2, title, ui.a("header"))
            row += 1
        row += 1
        for text, kind in _spread(lines, w):
            if not text:
                row += 1
                continue
            for wrapped in (textwrap.wrap(text, max(20, w - 8)) or [""]):
                ui.safe(row, 4, wrapped, ui.a(kind))
                row += 1
        draw_status(ui, footer)
        ui.scr.refresh()
        k = ui.key()
        if k is None:
            continue
        if k == curses.KEY_F5:
            ui.toggle_mono()
            continue
        if k == curses.KEY_F1:
            show_help(ui)
            continue
        if k == curses.KEY_F3:
            confirm_quit(ui)
        if k in (curses.KEY_ENTER, "\n", "\r"):
            return "enter"
        if k in (27, "q"):
            return "back"
        if isinstance(k, str) and len(k) == 1 and k.lower() in chars.lower():
            return k.lower()


def draw_status2(ui: UI, left: str, right: str = ""):
    """Status bar with independent left and right text (progress screen)."""
    _h, w = ui.scr.getmaxyx()
    avail = max(0, w - 1)
    _fill_status_row(ui, ui.a("status"))
    if left:
        ui.safe(_h - 1, 1, _fit(left, max(0, avail - 2)), ui.a("status"))
    if right:
        rx = avail - _display_width(right) - 1
        if rx < 1:
            rx = 1
        ui.safe(_h - 1, rx, _fit(right, max(0, avail - rx)), ui.a("status"))


def _short_name(name: str, width: int = 42) -> str:
    base = os.path.basename(name) or name
    if _display_width(base) > width:
        base = "…" + base[-(width - 1):]
    return base


def draw_progress_frame(ui: UI):
    """Draw the static parts of "Setup is copying files..." and return geometry."""
    h, w = ui.scr.getmaxyx()
    ui.scr.erase()
    draw_chrome(ui)
    ui.safe(4, 4, "Please wait while Setup copies files to your hard disk.",
            ui.a("normal"))
    ui.safe(6, 8, "• To quit Setup without installing a skin, press F3.",
            ui.a("normal"))
    ui.safe(8, 4, "For more information on setting up and using this skin,",
            ui.a("normal"))
    ui.safe(9, 4, "see the osu! skinning documentation.", ui.a("normal"))
    box_left = 3
    box_right = max(box_left + 8, w - 4)
    inner = box_right - box_left - 1
    box_top = 12
    if box_top + 6 >= h - 1:
        box_top = max(4, h - 8)
    ui.safe(box_top, box_left, "╔" + "═" * inner + "╗", ui.a("normal"))
    ui.safe(box_top + 6, box_left, "╚" + "═" * inner + "╝", ui.a("normal"))
    for r in range(box_top + 1, box_top + 6):
        ui.safe(r, box_left, "║", ui.a("normal"))
        ui.safe(r, box_right, "║", ui.a("normal"))
    ui.safe(box_top + 1, box_left + 2, "Setup is copying files...",
            ui.a("normal"))
    bar_left = box_left + 4
    bar_right = box_right - 4
    bar_inner = max(1, bar_right - bar_left - 1)
    ui.safe(box_top + 3, bar_left, "┌" + "─" * bar_inner + "┐", ui.a("normal"))
    ui.safe(box_top + 5, bar_left, "└" + "─" * bar_inner + "┘", ui.a("normal"))
    ui.scr.refresh()
    return (box_top, box_left, box_right, bar_left, bar_right, bar_inner)


def draw_progress_update(ui: UI, geom, percent, copying: str):
    box_top, box_left, box_right, bar_left, bar_right, bar_inner = geom
    percent = max(0, min(100, int(percent)))
    pct = f"{percent}%"
    ui.safe(box_top + 2, box_left + 1, " " * max(0, box_right - box_left - 1),
            ui.a("normal"))
    ui.safe(box_top + 2, (box_left + box_right - len(pct)) // 2, pct,
            ui.a("normal"))
    fill = int(bar_inner * percent / 100)
    ui.safe(box_top + 4, bar_left, "│", ui.a("normal"))
    ui.safe(box_top + 4, bar_right, "│", ui.a("normal"))
    ui.safe(box_top + 4, bar_left + 1,
            "█" * fill + " " * max(0, bar_inner - fill), ui.a("accent"))
    draw_status2(ui, "F3=Exit", f"Copying : {copying}" if copying else "")
    ui.scr.refresh()


def final_screen(ui: UI, dest):
    """The full blue page shown after a successful export.

    Returns "again" when the user presses R (start over) or "exit" otherwise.
    """
    lines = [
        "Setup is preparing to export your osu! skin.",
        "",
        "Please wait while Setup initializes.",
        "",
        "Setup has finished writing your skin to:",
        str(dest),
        "",
        "",
        "Press ENTER to quit osu! Skin Fuser",
        "Press R to build another osu! skin...",
    ]
    ui.scr.timeout(450)
    on = True
    try:
        while True:
            ui.scr.erase()
            h, w = ui.scr.getmaxyx()
            row = 0
            for line in lines:
                ui.safe(row, 0, line, ui.a("normal"))
                row += 1
            cx = min(_display_width(lines[-1]) + 1, max(1, w - 2))
            if on:
                try:
                    ui.scr.addstr(row - 1, cx, " ", curses.A_REVERSE)
                except curses.error:
                    pass
            ui.scr.refresh()
            k = ui.key()
            if k is None:
                on = not on
                continue
            if k == curses.KEY_F5:
                ui.toggle_mono()
                continue
            if k == curses.KEY_F3:
                confirm_quit(ui)
                continue
            if k in ("r", "R"):
                return "again"
            return "exit"
    finally:
        ui.scr.timeout(-1)


def _matches(query: str, *fields) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return True
    hay = " ".join(f or "" for f in fields).lower()
    return all(tok in hay for tok in q.split())


def _search(ui: UI, title, current: str) -> str:
    new = text_input(ui, title,
                     "Search text (Enter = apply, empty = clear):",
                     default=current)
    return current if new is None else new


# ---------------------------------------------------------------------------
# Editor screens (return "done" / "back")
# ---------------------------------------------------------------------------

ACCEPT_ROW = "Done"


def edit_images(ui: UI, opts: Options) -> str:
    files: "dict[str, dict[str, list[SkinFile]]]" = {}
    order = []
    for key, skin in opts.image_sources.items():
        for logical, fl in image_elements(skin).items():
            if logical not in files:
                files[logical] = {}
                order.append(logical)
            files[logical][key] = fl
    query = ""
    cursor = 0
    while True:
        view = [l for l in order
                if _matches(query, l, describe_element(l),
                            classify_image(l)[1], opts.label_of(l))]
        items = []
        for logical in view:
            sides = files[logical]
            cur = opts.choose_image_source(logical)
            if cur not in sides:
                cur = next(iter(sides))
            items.append((f"{logical}  ·  {describe_element(logical)}",
                          f"[{opts.short_of(cur)}]"))
        items.append((ACCEPT_ROW, ""))
        subtitle = "Sources: " + "  ".join(
            f"{opts.short_of(k)}={v.name}" for k, v in opts.image_sources.items())
        if query:
            subtitle += f"   |   filter: {query}"
        res = work_list(
            ui, "Image elements", items, subtitle, min(cursor, len(items) - 1),
            "ENTER=Change source   ESC=Cancel",
            search_allowed=True)
        cursor = res["cursor"]
        action = res["action"]
        if action == "search":
            query = _search(ui, "Search image elements", query)
            cursor = 0
            continue
        if action == "cancel":
            return "back"
        if action != "activate":
            continue
        if cursor >= len(view):
            return "done"          # the "matches my choice" row
        logical = view[cursor]
        sides = files[logical]
        options = [(f"{opts.label_of(k)}: {opts.image_sources[k].name}", "")
                   for k in sides]
        choice = dialog_select(
            ui, logical,
            [f'Choose the skin that supplies "{logical}".',
             describe_element(logical),
             "ENTER to apply, ESC to keep the current source."],
            options, 0)
        if choice is None:
            continue
        opts.element_overrides[logical] = list(sides.keys())[choice]


def edit_sounds(ui: UI, opts: Options) -> str:
    files: "dict[str, dict[str, list[SkinFile]]]" = {}
    order = []
    for key, skin in opts.sound_sources.items():
        for stem, fl in sound_elements(skin).items():
            if stem not in files:
                files[stem] = {}
                order.append(stem)
            files[stem][key] = fl
    order.sort(key=lambda s: (classify_sound(s), s))
    query = ""
    cursor = 0
    while True:
        view = [s for s in order
                if _matches(query, s, describe_sound(s), classify_sound(s),
                            *[v.name for v in opts.sound_sources.values()])]
        items = []
        for stem in view:
            sides = files[stem]
            desc = f"{stem}  ·  {describe_sound(stem)}"
            if opts.mode_fusion and sound_kind(stem) == "interface":
                ov = opts.sound_overrides.get(stem)
                if ov in sides:
                    hint = f"[{opts.short_of(ov)}]"
                else:
                    ui_key = opts.ui_sound_key()
                    note = "  (blank)" if ui_key not in sides else ""
                    hint = f"Follow UI source skin{note}"
            else:
                cur = opts.choose_sound_source(stem)
                if cur not in sides:
                    cur = next(iter(sides))
                hint = f"[{opts.short_of(cur)}]"
            items.append((desc, hint))
        items.append((ACCEPT_ROW, ""))
        subtitle = "Sources: " + "  ".join(
            f"{opts.short_of(k)}={v.name}" for k, v in opts.sound_sources.items())
        if opts.mode_fusion:
            subtitle += f"   |   UI sounds <- {opts.short_of(opts.ui_sound_key())}"
        if query:
            subtitle += f"   |   filter: {query}"
        res = work_list(
            ui, "Sound files", items, subtitle, min(cursor, len(items) - 1),
            "ENTER=Change source   ESC=Cancel",
            search_allowed=True)
        cursor = res["cursor"]
        action = res["action"]
        if action == "search":
            query = _search(ui, "Search sounds", query)
            cursor = 0
            continue
        if action == "cancel":
            return "back"
        if action != "activate":
            continue
        if cursor >= len(view):
            return "done"
        stem = view[cursor]
        sides = files[stem]
        interface = opts.mode_fusion and sound_kind(stem) == "interface"
        options = []
        if interface:
            options.append(("Follow UI source skin", ""))
        for k in sides:
            options.append(
                (f"{opts.label_of(k)}: {opts.sound_sources[k].name}", ""))
        choice = dialog_select(
            ui, stem,
            [f'Choose the skin that supplies "{stem}".',
             describe_sound(stem),
             "ENTER to apply, ESC to keep the current source."],
            options, 0)
        if choice is None:
            continue
        keys = list(sides.keys())
        if interface:
            if choice == 0:
                opts.sound_overrides.pop(stem, None)
            else:
                opts.sound_overrides[stem] = keys[choice - 1]
        else:
            opts.sound_overrides[stem] = keys[choice]


def edit_ini(ui: UI, opts: Options) -> str:
    merge: IniMerge = opts._ini_merge
    flat = []
    for sec in merge.ordered_sections():
        for e in merge.sections[sec]:
            flat.append((sec, e))
    query = ""
    cursor = 0
    while True:
        view = [(sec, e) for (sec, e) in flat
                if _matches(query, sec, e.key, merge.resolve(e) or "",
                            *[opts.label_of(k) for k in merge.source_keys])]
        items = []
        for sec, e in view:
            val = merge.resolve(e)
            shown = val if val is not None else "<not set>"
            if len(shown) > 30:
                shown = shown[:27] + "..."
            tag = "custom" if e.choice == "C" else opts.short_of(e.choice)
            sec_label = sec.replace("Mania:", "Mania ") \
                if sec.startswith("Mania:") else sec
            items.append((f"{sec_label}.{e.key}", f"[{tag}] {shown}"))
        items.append((ACCEPT_ROW, ""))
        subtitle = "Sources: " + "  ".join(
            f"{opts.short_of(k)}={v.name}" for k, v in merge.source_skins.items())
        if query:
            subtitle += f"   |   filter: {query}"
        res = work_list(
            ui, "skin.ini settings", items, subtitle,
            min(cursor, len(items) - 1),
            "ENTER=Change value   ESC=Cancel",
            search_allowed=True)
        cursor = res["cursor"]
        action = res["action"]
        if action == "search":
            query = _search(ui, "Search skin.ini settings", query)
            cursor = 0
            continue
        if action == "cancel":
            return "back"
        if action != "activate":
            continue
        if cursor >= len(view):
            return "done"          # the "Done" row
        sec, e = view[cursor]
        options = []
        for k in merge.source_keys:
            v = e.values.get(k)
            options.append(
                (f"{opts.label_of(k)}: {v if v is not None else '<not set>'}", ""))
        options.append(("Custom value...", ""))
        label = sec.replace("Mania:", "Mania ") if sec.startswith("Mania:") else sec
        choice = dialog_select(
            ui, f"{label}.{e.key}",
            [f'Select the value for "{e.key}".',
             "ENTER to apply, ESC to keep the current value."],
            options, 0)
        if choice is None:
            continue
        if choice == len(merge.source_keys):
            cur = e.custom or next((v for v in e.values.values() if v), "")
            new = text_input(ui, f"Custom value for {sec}.{e.key}",
                             "Value:", default=cur)
            if new is not None:
                e.choice = "C"
                e.custom = new
                e.manual = True
        else:
            e.choice = merge.source_keys[choice]
            e.manual = True


def edit_identity(ui: UI, opts: Options) -> str:
    """Export details, laid out like the Windows Setup System Information page."""
    id_keys = ["name", "author", "version"]
    labels = {"name": "Skin name:", "author": "Author:",
              "version": "skin.ini Version:"}
    fields = id_keys + ["out_dir", "export"]
    accept_idx = len(fields)
    total = accept_idx + 1
    cursor = 0
    label_x = 3
    value_x = 22
    desc_para = ("Setup has prepared this osu! skin.  If the details below are "
                 'correct, choose "No Changes".  To change an item, press '
                 "ENTER on it to see the alternatives for that item.")
    instr_para = ('If all the details are correct, press ENTER to indicate '
                  '"No Changes".  Otherwise press UP or DOWN to move the '
                  "highlight to the item you want to change, then press ENTER "
                  "to see alternatives for that item.")
    desc_fixed = [
        "Setup has prepared this osu! skin.  If the details below are correct,",
        'choose "No Changes".  To change an item, press ENTER on it to see the',
        "alternatives for that item.",
    ]
    instr_fixed = [
        'If all the details are correct, press ENTER to indicate "No Changes".',
        "Otherwise press UP or DOWN to move the highlight to the item you want",
        "to change, then press ENTER to see alternatives for that item.",
    ]

    while True:
        ui.scr.erase()
        h, w = ui.scr.getmaxyx()
        draw_chrome(ui)
        ui.safe(4, 2, "Export Details", ui.a("header"))
        subtitle = "Sources: " + "  ".join(
            opts.label_of(k) for k in opts.image_sources)
        ui.safe(5, 3, _fit(subtitle, max(0, w - 6)), ui.a("hint"))
        if w > 90:
            desc = textwrap.wrap(desc_para, max(20, w - 8))
            instructions = textwrap.wrap(instr_para, max(20, w - 8))
        else:
            desc = desc_fixed
            instructions = instr_fixed
        row = 7
        for line in desc:
            ui.safe(row, 3, _fit(line, max(0, w - 6)), ui.a("normal"))
            row += 1
        start = row + 1

        def draw_row(y, label, value, selected):
            # Like the original Setup System Information page: only the value
            # column is highlighted, the label stays plain.
            ui.safe(y, label_x, _fit(label, value_x - label_x - 1),
                    ui.a("normal"))
            if selected:
                ui.safe(y, value_x, " " * max(0, w - value_x - 1), ui.a("sel"))
            attr = ui.a("sel") if selected else ui.a("normal")
            ui.safe(y, value_x, _fit(value, max(0, w - value_x - 2)), attr)

        for i, fid in enumerate(fields):
            if fid in id_keys:
                spec = opts.identity[fid]
                ch = spec.get("choice", "C")
                if ch != "C":
                    skin = opts.image_sources.get(ch) or \
                        opts.sound_sources.get(ch)
                    shown = (skin.ini.identity.get(fid) if skin else None) \
                        or "<none>"
                    value = f"[{opts.label_of(ch)}] {shown}"
                else:
                    value = f"[Custom] {resolve_identity(opts, fid)}"
                label = labels[fid]
            elif fid == "out_dir":
                label = "Output folder:"
                value = str(Path(opts.out_dir).resolve())
            else:
                label = "Export as:"
                value = EXPORT_MODES.get(opts.export_mode, opts.export_mode)
            draw_row(start + i, label, value, cursor == i)

        accept_y = start + len(fields) + 1
        draw_row(accept_y, "No Changes:",
                 "The above list matches my choice.", cursor == accept_idx)

        irow = accept_y + 2
        for line in instructions:
            if irow < h - 1:
                ui.safe(irow, 3, _fit(line, max(0, w - 6)), ui.a("normal"))
            irow += 1

        draw_status(ui, "ENTER=Change   ESC=Cancel")
        ui.scr.refresh()
        k = ui.key()
        if k is None:
            continue
        if k == curses.KEY_F1:
            show_help(ui)
            continue
        if k == curses.KEY_F5:
            ui.toggle_mono()
            continue
        if k == curses.KEY_F3:
            confirm_quit(ui)
        if k in (curses.KEY_UP, "k"):
            cursor = (cursor - 1) % total
        elif k in (curses.KEY_DOWN, "j"):
            cursor = (cursor + 1) % total
        elif k in (curses.KEY_HOME, "g"):
            cursor = 0
        elif k in (curses.KEY_END, "G"):
            cursor = accept_idx
        elif k in (27, "q", curses.KEY_LEFT):
            return "back"
        elif k in (curses.KEY_ENTER, "\n", "\r", " "):
            if cursor == accept_idx:
                return "done"
            fid = fields[cursor]
            if fid in id_keys:
                options = []
                for src in opts.image_sources:
                    skin = opts.image_sources[src]
                    val = skin.ini.identity.get(fid) or "<none>"
                    options.append((f"{opts.label_of(src)}: {val}", ""))
                options.append(("Custom value...", ""))
                choice = dialog_select(
                    ui, labels[fid],
                    [f"Select the {fid} for the exported skin.",
                     "ENTER to apply, ESC to keep the current value."],
                    options, 0)
                if choice is None:
                    continue
                spec = opts.identity[fid]
                if choice == len(options) - 1:
                    cur = spec.get("custom") or resolve_identity(opts, fid)
                    new = text_input(ui, f"Custom {fid}", "Value:", default=cur)
                    if new is not None:
                        spec["choice"] = "C"
                        spec["custom"] = new
                else:
                    spec["choice"] = list(opts.image_sources.keys())[choice]
            elif fid == "out_dir":
                new = text_input(ui, "Output folder", "Folder:",
                                 default=opts.out_dir)
                if new:
                    opts.out_dir = new
            else:
                keys = list(EXPORT_MODES.keys())
                cur = keys.index(opts.export_mode) \
                    if opts.export_mode in keys else 0
                choice = dialog_select(
                    ui, "Export as",
                    ["Choose what Setup should write:"],
                    [(v, "") for v in EXPORT_MODES.values()], cur)
                if choice is not None:
                    opts.export_mode = keys[choice]


# ---------------------------------------------------------------------------
# Skin picker (directory path + search, remembers the chosen directory)
# ---------------------------------------------------------------------------

class PickerState:
    """Shared across pickers so the directory chosen once is remembered."""

    def __init__(self, skins):
        self.skins = list(skins)
        self.directory = None

    def set_directory(self, path, found):
        self.skins = list(found)
        self.directory = str(path)


def pick_skin(ui: UI, role: str, state: "PickerState"):
    query = ""
    cursor = 0
    while True:
        view = [s for s in state.skins if _matches(query, s.name)]
        items = [(s.name, f"{len(s.files)} files") for s in view]
        idx_dir = len(items)
        items.append(("Enter your osu skin directory path...", "scan a folder"))
        idx_file = len(items)
        items.append(("Enter a skin folder / .osk path...", "load one skin"))
        subtitle = f"{role} skin"
        if state.directory:
            subtitle += f"   |   dir: {state.directory}"
        if query:
            subtitle += f"   |   filter: {query}"
        res = menu_cursor(ui, f"Select the {role} skin   (/ = search)", items,
                          subtitle, cursor,
                          "Enter = choose   / = search   q = back",
                          search_allowed=True)
        cursor = res["cursor"]
        action = res["action"]
        if action == "search":
            query = _search(ui, f"Search {role} skins", query)
            cursor = 0
            continue
        if action == "cancel":
            return None
        if action != "done":
            continue
        if cursor < len(view):
            return view[cursor]
        if cursor == idx_dir:
            path = text_input(ui, "osu! skin directory",
                              "Directory that contains skin folders:")
            if path:
                found = discover_skins([path])
                if found:
                    state.set_directory(path, found)
                    query = ""
                    cursor = 0
                    info(ui, "Skins found",
                         "\n".join(f"- {s.name}" for s in found))
                else:
                    info(ui, "No skins found",
                         f"No skin folders were found in:\n{path}")
        elif cursor == idx_file:
            path = text_input(ui, "Load a skin", "Path to folder or .osk:")
            if path:
                try:
                    return load_skin_arg(path, [])
                except Exception as exc:  # noqa: BLE001
                    info(ui, "Error", f"Could not load skin:\n{exc}")


# ---------------------------------------------------------------------------
# Wizard steps
# ---------------------------------------------------------------------------

def run_steps(holder) -> str:
    """Run wizard steps from holder["steps"]; steps may rebuild the list."""
    i = 0
    while True:
        steps = holder["steps"]
        if i < 0 or i >= len(steps):
            return "quit"
        action = steps[i]()
        if action in ("next", "done"):
            i += 1
        elif action == "back":
            i -= 1
        elif action == "quit":
            return "quit"
        elif action == "export":
            return "export"


def step_pick_skin(ui, role, state, opts, slot):
    s = pick_skin(ui, role, state)
    if s is None:
        return "back"
    if slot == "art" and opts.gameplay is not None and \
            s.root == opts.gameplay.root:
        # Was a separate wizard step; folding it in here keeps "back" from the
        # image preset looping straight back to the image preset.
        if not confirm(ui, "Same skin selected",
                       "You picked the same skin for both sides. Continue?"):
            return "back"
    setattr(opts, slot, s)
    if slot == "art":
        finalize_two_skin(opts)
    return "next"


def step_image_preset(ui, opts):
    keys = list(IMAGE_PRESETS.keys())
    while True:
        items = [(v, "") for v in IMAGE_PRESETS.values()]
        items.append(("Fine-tune per element...", "open the settings list"))
        res = menu(ui, "Which images should come from where?", items,
                   "Enter = select   ESC/q = back")
        if res is None:
            return "back"
        if res[0] < len(keys):
            chosen = keys[res[0]]
            opts.image_source = "auto" if chosen == "mixed" else chosen
            opts.element_overrides.clear()
            return "next"
        opts.image_source = "auto"
        if edit_images(ui, opts) == "done":
            return "next"


def step_sound_preset(ui, opts):
    keys = list(SOUND_PRESETS.keys())
    while True:
        items = [(v, "") for v in SOUND_PRESETS.values()]
        items.append(("Fine-tune per sound file...", "open the settings list"))
        res = menu(ui, "Which sounds should come from where?", items,
                   "Enter = select   ESC/q = back")
        if res is None:
            return "back"
        if res[0] < len(keys):
            opts.sound_preset = keys[res[0]]
            opts.sound_overrides.clear()
            return "next"
        if edit_sounds(ui, opts) == "done":
            return "next"


def step_ini_preset(ui, opts):
    srcs = list(opts.image_sources.keys())
    while True:
        items = [("Smart merge: gameplay / mode settings first (recommended)", "")]
        items += [(f"All settings from {opts.label_of(k)}", "") for k in srcs]
        items.append(("Fine-tune per setting...", "open the settings list"))
        res = menu(ui, "skin.ini settings", items, "Enter = select   ESC/q = back",
                   subtitle="Fine-tune opens the list; Done there applies it")
        if res is None:
            return "back"
        if res[0] == len(srcs) + 1:
            # Open the settings list: its last row is "Done"; ESC returns here.
            opts.ini_base = "smart"
            if opts._ini_merge is None:
                opts._ini_merge = IniMerge(opts.image_sources, opts.base_key())
                opts._ini_merge.apply_base(opts.ini_base)
            if edit_ini(ui, opts) == "done":
                return "next"
            continue
        if res[0] == 0:
            opts.ini_base = "smart"
        else:
            opts.ini_base = srcs[res[0] - 1]
        if opts._ini_merge is None:
            opts._ini_merge = IniMerge(opts.image_sources, opts.base_key())
        opts._ini_merge.apply_base(opts.ini_base)
        return "next"


def step_identity(ui, opts):
    return "export" if edit_identity(ui, opts) == "done" else "back"


def prepare_export(opts: Options):
    if opts._ini_merge is None:
        opts._ini_merge = IniMerge(opts.image_sources, opts.base_key())
        opts._ini_merge.apply_base(opts.ini_base)
    plan = build_plan(opts, opts._ini_merge)
    identity = {
        "name": resolve_identity(opts, "name"),
        "author": resolve_identity(opts, "author"),
        "version": resolve_identity(opts, "version"),
    }
    description = (f"All-in-One: {' + '.join(MODES[m] for m in opts.modes)}"
                   if opts.mode_fusion
                   else f"Gameplay={opts.gameplay.name}, Art={opts.art.name}")
    ini_text = opts._ini_merge.to_text(identity, description)
    return plan, ini_text


# ---------------------------------------------------------------------------
# All-in-One steps
# ---------------------------------------------------------------------------

def step_modes(ui, opts):
    order = list(MODES.keys())
    items = [(MODES[m], "") for m in order]
    checked = [order.index(m) for m in opts.modes]
    while True:
        res = menu(ui, "All-in-One: choose 2+ modes to fuse", items,
                   "Space = toggle   Enter = confirm   q = back",
                   multi=True, checked=checked,
                   subtitle="Pick at least two game modes")
        if res is None:
            return "back"
        if len(res) >= 2:
            opts.modes = [order[i] for i in res]
            return "next"
        info(ui, "Pick at least two modes",
             f"An All-in-One skin needs at least two game modes.\n"
             f"You selected {len(res)}.")


def step_separate_av(ui, opts):
    res = menu(ui, "Image & sound sources", [
        ("One source skin per mode (images + sounds together)", "simpler"),
        ("Choose image and sound sources separately per mode", "more control"),
    ], "Enter = select   q = back")
    if res is None:
        return "back"
    opts.separate_av = (res[0] == 1)
    return "next"


def step_mode_sources(ui, opts, state):
    opts.mode_image = {}
    opts.mode_sound = {}
    for mode in opts.modes:
        s = pick_skin(ui, f"{MODES[mode]} IMAGE", state)
        if s is None:
            return "back"
        opts.mode_image[mode] = s
    for mode in opts.modes:
        if opts.separate_av:
            s = pick_skin(ui, f"{MODES[mode]} SOUND", state)
            if s is None:
                return "back"
            opts.mode_sound[mode] = s
        else:
            opts.mode_sound[mode] = opts.mode_image[mode]
    build_source_registries(opts)
    return "next"


def step_art_choice(ui, opts, state):
    items = [("Reuse the mode sources for the artwork too",
              "no separate art skin")]
    art_idx = None
    keep_idx = None
    if opts.art is not None:
        keep_idx = len(items)
        items.append((f"Keep the current Art skin: {opts.art.name}",
                      "already chosen"))
    art_idx = len(items)
    items.append(("Choose / change a separate Art skin...",
                  "menu / ranking / backgrounds"))
    res = menu(ui, "All-in-One artwork", items,
               "Enter = select   q = back",
               subtitle="A separate Art skin only supplies shared menu / UI art")
    if res is None:
        return "back"
    if res[0] == 0:
        opts.art = None
        apply_art_source(opts)
        return "next"
    if keep_idx is not None and res[0] == keep_idx:
        apply_art_source(opts)
        return "next"
    s = pick_skin(ui, "Art (looks)", state)
    if s is None:
        return "back"
    opts.art = s
    apply_art_source(opts)
    return "next"


def step_ui_sound_source(ui, opts):
    keys = list(opts.sound_sources.keys())
    cur = opts.ui_sound_key()
    items = []
    for k in keys:
        skin = opts.sound_sources[k]
        mark = "   (current)" if k == cur else ""
        items.append((f"{opts.label_of(k)}", f"{skin.name}{mark}"))
    res = menu(ui, "Interface / UI sound source", items,
               "Enter = select   q = back",
               subtitle="Menu clicks, applause, countdowns, ... follow this skin; "
                        "missing ones stay blank (osu! default)")
    if res is None:
        return "back"
    opts.ui_sound_source = keys[res[0]]
    return "next"


def step_image_preset_aio(ui, opts):
    while True:
        items = [("Mode-specific images (recommended)",
                  "each mode's sprites from its own skin")]
        items += [(f"All images from {opts.label_of(k)}", "")
                  for k in opts.image_sources]
        items.append(("Fine-tune per element...", "open the settings list"))
        res = menu(ui, "All-in-One images", items, "Enter = select   ESC/q = back")
        if res is None:
            return "back"
        if res[0] == 0:
            opts.image_source = "auto"
            opts.element_overrides.clear()
            return "next"
        if res[0] <= len(opts.image_sources):
            opts.image_source = list(opts.image_sources.keys())[res[0] - 1]
            opts.element_overrides.clear()
            return "next"
        opts.image_source = "auto"
        if edit_images(ui, opts) == "done":
            return "next"


def step_sound_preset_aio(ui, opts):
    while True:
        items = [("Mode-specific gameplay sounds (recommended)",
                  "hitsounds from base, mode sounds from their mode"),
                 ("(UI source: " + opts.label_of(opts.ui_sound_key()) + ")",
                  "change it in the previous step")]
        items += [(f"All sounds from {opts.label_of(k)}", "")
                  for k in opts.sound_sources]
        items.append(("Fine-tune per sound file...", "open the settings list"))
        res = menu(ui, "All-in-One sounds", items, "Enter = select   ESC/q = back")
        if res is None:
            return "back"
        if res[0] == 0:
            opts.sound_source = "auto"
            opts.sound_overrides.clear()
            return "next"
        if res[0] == 1:
            return "next"
        if res[0] <= len(opts.sound_sources) + 1:
            opts.sound_source = list(opts.sound_sources.keys())[res[0] - 2]
            opts.sound_overrides.clear()
            return "next"
        opts.sound_source = "auto"
        if edit_sounds(ui, opts) == "done":
            return "next"


def build_two_skin_steps(ui, state, opts):
    return [
        lambda: step_pick_skin(ui, "Gameplay (feel)", state, opts, "gameplay"),
        lambda: step_pick_skin(ui, "Art (looks)", state, opts, "art"),
        lambda: step_image_preset(ui, opts),
        lambda: step_sound_preset(ui, opts),
        lambda: step_ini_preset(ui, opts),
        lambda: step_identity(ui, opts),
    ]


def build_aio_steps(ui, state, opts):
    return [
        lambda: step_modes(ui, opts),
        lambda: step_separate_av(ui, opts),
        lambda: step_mode_sources(ui, opts, state),
        lambda: step_art_choice(ui, opts, state),
        lambda: step_ui_sound_source(ui, opts),
        lambda: step_image_preset_aio(ui, opts),
        lambda: step_sound_preset_aio(ui, opts),
        lambda: step_ini_preset(ui, opts),
        lambda: step_identity(ui, opts),
    ]
#Original texts generated by AI are placed as commetaries beside the actual used texts
'''
WELCOME_LINES = [
    ("Welcome to Setup.", "header"),
    ("", "normal"),
    ("The Setup program for osu! AIO Skin Fuser prepares an osu! skin",
     "normal"),
    ("to run on your computer.", "normal"),
    ("", "normal"),
    ("  • To learn more about Setup before continuing, press F1.", "normal"),
    ("", "normal"),
    ("  • To set up a skin now, press ENTER.", "normal"),
    ("", "normal"),
    ("  • To quit Setup without building a skin, press F3.", "normal"),
]
METHOD_LINES = [
    ("This Setup program can prepare the skin in two ways:", "normal"),
    ("", "normal"),
    ("Gameplay + Art fusion (Recommended)", "header"),
    ("Keep the gameplay pieces (hitcircles, sliders, cursor, hitbursts)",
     "normal"),
    ("from one skin and the artwork (menu, ranking, backgrounds) from"
     " another.", "normal"),
    ("", "normal"),
    ("    To use Gameplay + Art fusion, press ENTER.", "normal"),
    ("", "normal"),
    ("", "normal"),
    ("All-in-One mode fusion", "header"),
    ("Combine osu!standard / mania / taiko / catch skins into a single skin,",
     "normal"),
    ("with an optional Art skin and a separate interface-sound source.",
     "normal"),
    ("", "normal"),
    ("    To use All-in-One mode fusion, press C.", "normal"),
    ("", "normal"),
    ("For details about both Setup methods, press F1.", "normal"),
]
'''

WELCOME_LINES = [
    ("Welcome to osu! AIO Skin Fuser.", "header"),
    ("", "normal"),
    ("The osu! AIO Skin Fuser vibecoded by SlicedAvocado prepares an osu! skin",
     "normal"),
    ("that looks wonderful in your osu!.", "normal"),
    ("", "normal"),
    ("  • To learn more about Setup before continuing, press F1.", "normal"),
    ("", "normal"),
    ("  • To set up a skin now, press ENTER.", "normal"),
    ("", "normal"),
    ("  • To quit Skin Fuser without building a skin, press F3.", "normal"),
]

METHOD_LINES = [
    ("This Setup program can prepare the skin in two ways:", "normal"),
    ("", "normal"),
    ("Gameplay + Art fusion (Recommended)", "header"),
    ("Keep the gameplay pieces (hitcircles, sliders, cursor, hitbursts)",
     "normal"),
    ("from one skin and the artwork (menu, ranking, backgrounds) from"
     " another.", "normal"),
    ("", "normal"),
    ("    To use Gameplay + Art fusion, press ENTER.", "normal"),
    ("", "normal"),
    ("", "normal"),
    ("All-in-One mode fusion", "header"),
    ("Combine osu!standard / mania / taiko / catch skins into a single skin,",
     "normal"),
    ("with an optional Art skin and a separate interface-sound source.",
     "normal"),
    ("", "normal"),
    ("    To use All-in-One mode fusion, press C.", "normal"),
    ("", "normal"),
    ("For details about both Setup methods, press F1.", "normal"),
]


def interactive_session(skins) -> int:
    if not skins:
        print("No skins found. Pass --skins-dir <folder> or run from a folder "
              "containing your skin folders.", file=sys.stderr)
        return 2
    try:
        with UI() as ui:
            state = PickerState(skins)
            while True:
                opts = Options()
                holder = {"steps": []}

                def step_welcome():
                    act = text_page(ui, APP_TITLE, WELCOME_LINES,
                                    "Enter=Continue   F1=Help   F3=Exit")
                    return "quit" if act == "back" else "next"

                def step_methods():
                    act = text_page(ui, APP_TITLE, METHOD_LINES,
                                    "Enter=Gameplay+Art   C=AIO mode   "
                                    "F1=Help   F3=Exit", chars="c")
                    if act == "back":
                        return "back"
                    opts.mode_fusion = (act == "c")
                    rest = (build_aio_steps(ui, state, opts)
                            if opts.mode_fusion
                            else build_two_skin_steps(ui, state, opts))
                    holder["steps"] = [step_welcome, step_methods] + rest
                    return "next"

                holder["steps"] = [step_welcome, step_methods]
                result = run_steps(holder)
                if result != "export":
                    return 0

                plan, ini_text = prepare_export(opts)

                geom = {"value": None, "begun": False}

                def on_progress(step, total, name):
                    if not geom["begun"]:
                        geom["value"] = draw_progress_frame(ui)
                        geom["begun"] = True
                        draw_progress_update(ui, geom["value"], 0,
                                             _short_name(name))
                        # A short pause so the progress screen is never a blur.
                        time.sleep(0.5)
                    draw_progress_update(ui, geom["value"],
                                         step * 100.0 / max(1, total),
                                         _short_name(name))
                    if ui.key_nonblock() == curses.KEY_F3:
                        confirm_quit(ui)
                        draw_progress_update(ui, geom["value"],
                                             step * 100.0 / max(1, total),
                                             _short_name(name))

                dest = export_skin(opts, plan, ini_text,
                                   log=lambda *a, **k: None,
                                   progress=on_progress)
                if final_screen(ui, dest) != "again":
                    return 0
                # 'R' on the final page loops back to the welcome page so the
                # user can build another skin without restarting the program.
    except QuitApp:
        return 0
    except Cancelled:
        return 130


# ---------------------------------------------------------------------------
# CLI (non-interactive)
# ---------------------------------------------------------------------------

HELP_EPILOG = """\
examples:
  # interactive TUI
  python3 osu_skin_fuser.py

  # two-skin fusion
  python3 osu_skin_fuser.py --gameplay SkinA --art SkinB --name "My Mix" \\
      --output ./FusedSkins

  # All-in-One mode fusion
  python3 osu_skin_fuser.py --all-in-one \\
      --mode-skin standard=StdSkin --mode-skin mania=ManiaSkin \\
      --mode-skin taiko=TaikoSkin --name "All-in-One"

notes:
  * Without --gameplay/--art/--mode-skin the interactive TUI starts.
  * A skin may be a folder or a .osk archive.
  * Sound presets: hitsound_gameplay (default), hitsound_art, gameplay, art.
  * Image sources: mixed (default), gameplay, art.
  * ini bases: smart (default), gameplay, art; in All-in-One: smart or a mode.
  * In every editor press "/" to search and Space to cycle the source.
"""


def build_arg_parser():
    p = argparse.ArgumentParser(
        prog=APP_TITLE,
        description="Fuse the gameplay/modes of osu! skins with the art of others.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    p.add_argument("--skins-dir", action="append", default=[],
                   help="Extra folder to scan for skins (repeatable).")
    p.add_argument("--gameplay")
    p.add_argument("--art")
    p.add_argument("--all-in-one", action="store_true",
                   help="Enable All-in-One mode fusion.")
    p.add_argument("--mode-skin", action="append", default=[],
                   metavar="MODE=PATH",
                   help="Source skin for a mode (standard/mania/taiko/catch).")
    p.add_argument("--image-source", choices=["mixed", "gameplay", "art"],
                   default="mixed")
    p.add_argument("--sounds", choices=list(SOUND_PRESETS.keys()),
                   default="hitsound_gameplay")
    p.add_argument("--ini", dest="ini_base",
                   choices=["smart", "gameplay", "art"], default="smart")
    p.add_argument("--name")
    p.add_argument("--author")
    p.add_argument("--skin-version", dest="skin_version")
    p.add_argument("--output", default="FusedSkins")
    p.add_argument("--export-mode", choices=list(EXPORT_MODES.keys()),
                   default="osk",
                   help="What to write: .osk only (default), folder only, or both.")
    p.add_argument("--no-osk", action="store_true",
                   help="Alias for --export-mode folder.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--list", action="store_true")
    return p


def main(argv=None) -> int:
    locale.setlocale(locale.LC_ALL, "")
    args = build_arg_parser().parse_args(argv)
    tmpdirs: list = []
    skin_dirs = list(args.skins_dir) + [str(d) for d in default_skin_dirs()]

    if args.list:
        skins = discover_skins(skin_dirs)
        if not skins:
            print("No skins found.")
            return 1
        for s in skins:
            extra = "  [skin.ini]" if s.ini.has_any() else ""
            print(f"{s.name:30s} {s.root}{extra}")
        return 0

    if not (args.gameplay and args.art) and not args.all_in_one:
        return interactive_session(discover_skins(skin_dirs))

    opts = Options()
    opts.out_dir = args.output
    opts.export_mode = "folder" if args.no_osk else args.export_mode
    if args.name:
        opts.identity["name"] = {"choice": "C", "custom": args.name}
    if args.author:
        opts.identity["author"] = {"choice": "C", "custom": args.author}
    if args.skin_version:
        opts.identity["version"] = {"choice": "C", "custom": args.skin_version}

    try:
        if args.all_in_one:
            opts.mode_fusion = True
            for spec in args.mode_skin:
                if "=" not in spec:
                    print(f"Bad --mode-skin '{spec}', expected MODE=PATH",
                          file=sys.stderr)
                    return 2
                mode, path = spec.split("=", 1)
                mode = mode.strip().lower()
                if mode not in MODES:
                    print(f"Unknown mode '{mode}'", file=sys.stderr)
                    return 2
                opts.modes.append(mode)
                opts.mode_image[mode] = load_skin_arg(path, tmpdirs)
                opts.mode_sound[mode] = opts.mode_image[mode]
            if len(opts.modes) < 2:
                print("All-in-One needs at least two --mode-skin entries.",
                      file=sys.stderr)
                return 2
            build_source_registries(opts)
            opts.ini_base = "smart" if args.ini_base in ("smart", "gameplay") \
                else args.ini_base
        else:
            opts.gameplay = load_skin_arg(args.gameplay, tmpdirs)
            opts.art = load_skin_arg(args.art, tmpdirs)
            finalize_two_skin(opts)
            opts.image_source = "auto" if args.image_source == "mixed" \
                else args.image_source
            opts.sound_preset = args.sounds
            opts.ini_base = args.ini_base
    except Exception as exc:  # noqa: BLE001
        print(f"Error loading skins: {exc}", file=sys.stderr)
        return 2

    plan, ini_text = prepare_export(opts)
    print(summarize(opts, plan))
    if args.dry_run:
        print("\n(dry run - nothing written)")
        return 0
    print()
    dest = export_skin(opts, plan, ini_text)
    print(f"\nDone! Fused skin written to:\n  {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
