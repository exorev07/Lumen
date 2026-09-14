# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows build (onedir).

Build with (from the repo root, in an environment that has lumen and
PyInstaller installed):

    pyinstaller packaging/lumen.spec --noconfirm

Two things here are load-bearing rather than boilerplate:

* `console=True`. Textual needs a real terminal, and a windowed build has
  none - a double-clicked GUI-subsystem binary would flash and die with no
  way to see why. This must stay a console-subsystem build.
* `collect_all("textual")`. Textual loads its own `.tcss` stylesheets and
  its widget modules at runtime; the stylesheets are data files PyInstaller
  cannot see by following imports, and losing them gives an app that starts
  and then renders unstyled or raises on mount.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

# The licence travels INSIDE the binary as well as beside it. A single
# file that someone copies to another machine leaves a loose
# THIRD-PARTY-LICENSES.txt behind; embedding it means the obligation is
# met by the artifact itself, and `lumen --licence` can print it.
datas = [("../LICENSE", "."), ("../release/THIRD-PARTY-LICENSES.txt", ".")]
binaries, hiddenimports = [], []

# Stylesheets and lazily-imported widgets - not reachable by import analysis.
for pkg in ("textual", "tinytuya"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Rich resolves some of these by name at runtime rather than importing them.
hiddenimports += collect_submodules("rich")

a = Analysis(
    ["lumen_entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Pulled in by the dependency tree but never used by Lumen. Dropping
    # them is worth several MB in a binary people download.
    excludes=["tkinter", "unittest", "pydoc_data", "test"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# onedir, not onefile. Two reasons, both practical rather than aesthetic:
# a onefile binary unpacks itself to a temp directory on every run, which
# costs about a second of startup and is exactly the behaviour antivirus
# heuristics flag on an unsigned executable. A folder of DLLs next to the
# exe does neither. The folder is shipped as a zip - see make_release.py.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="lumen",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # See the module docstring: Textual has to have a terminal.
    console=True,
    # Puts the copyright and MIT notice on the binary itself, visible in
    # Explorer's Properties > Details. See packaging/version_info.txt.
    version="version_info.txt",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="lumen",
)
