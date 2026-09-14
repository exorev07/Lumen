"""Write THIRD-PARTY-LICENSES.txt for the files the exe actually bundles.

MIT, BSD and Apache-2.0 all require their licence text to accompany a
*binary* redistribution, and lumen.exe is exactly that - one file with
seventeen third-party libraries inside it. Shipping the exe without this
file alongside it is a licence violation, so this runs as part of making a
release.

The package list is derived from PyInstaller's own TOC files rather than
written by hand: a hand-kept list silently goes stale the moment a
dependency is added, which is the failure mode worth designing out. Run
it against the same environment the exe was built from, after the build:

    python packaging/gen_licenses.py build/lumen > release/THIRD-PARTY-LICENSES.txt
"""

import ast
import pathlib
import sys
import importlib.metadata as md

# Present at build time but not redistributed inside the binary.
BUILD_ONLY = {
    "pyinstaller", "pyinstaller-hooks-contrib", "setuptools", "pip",
    "altgraph", "pefile", "pywin32-ctypes", "wheel", "lumen-control",
}


def bundled(build_dir):
    """Top-level distributions named anywhere in the build's TOC files."""
    names = set()
    for toc in ("PKG-00.toc", "PYZ-00.toc", "Analysis-00.toc"):
        p = build_dir / toc
        if not p.exists():
            continue
        obj = ast.literal_eval(p.read_text(encoding="utf-8",
                                           errors="replace").strip())

        def walk(o):
            if isinstance(o, (list, tuple)):
                flat = (o and isinstance(o[0], str) and len(o) in (2, 3)
                        and all(isinstance(x, (str, type(None))) for x in o))
                if flat:
                    names.add(o[0].replace("\\", "/").split("/")[0].split(".")[0])
                else:
                    for x in o:
                        walk(x)
        walk(obj)

    roots = {}
    for dist in md.distributions():
        dn = dist.metadata.get("Name")
        if not dn:
            continue
        found = set()
        t = dist.read_text("top_level.txt")
        if t:
            found |= {l.strip() for l in t.splitlines() if l.strip()}
        for f in dist.files or []:
            s = str(f).replace("\\", "/")
            if "/" in s and not s.startswith("..") and "dist-info" not in s:
                found.add(s.split("/")[0].split(".")[0])
        for r in found:
            if r:
                roots.setdefault(r, dn)

    out = {}
    for n in names:
        d = roots.get(n)
        if d and d.lower() not in BUILD_ONLY:
            out[d] = n
    return out


def licence_text(dist):
    """The licence file the distribution ships, if it ships one.

    Read from the dist-info directory on disk rather than via
    `dist.read_text`, which resolves relative to site-packages and returns
    None for the `dist-info/licenses/LICENSE` layout that modern wheels
    use - i.e. for essentially every dependency here.
    """
    root = pathlib.Path(str(getattr(dist, "_path", "") or ""))
    candidates = []
    if root.is_dir():
        candidates += sorted(root.rglob("*"))
    for f in dist.files or []:
        candidates.append(pathlib.Path(str(dist.locate_file(f))))

    for c in candidates:
        base = c.name.lower()
        if (("licen" in base or base.startswith("copying")
             or base.startswith("notice"))
                and c.is_file() and not base.endswith(".py")):
            try:
                t = c.read_text(encoding="utf-8", errors="replace").strip()
                if len(t) > 40:
                    return t
            except OSError:
                pass
    return None


def describe(meta):
    lic = meta.get("License-Expression")
    if lic:
        return lic
    for c in meta.get_all("Classifier") or []:
        if c.startswith("License ::"):
            return c.split("::")[-1].strip()
    raw = (meta.get("License") or "").strip()
    return raw.splitlines()[0][:60] if raw else "see text below"


def main():
    build_dir = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                             else "build/lumen")
    if not build_dir.exists():
        sys.exit("no build directory at %s - build the exe first" % build_dir)

    found = bundled(build_dir)
    if not found:
        sys.exit("no bundled distributions found - is %s a PyInstaller "
                 "build directory?" % build_dir)

    w = sys.stdout.write
    w("Third-party licences bundled in lumen.exe\n")
    w("=" * 70 + "\n\n")
    w("lumen.exe is a single file containing the Python runtime and the\n")
    w("libraries listed below. Lumen itself is MIT licensed - see LICENSE.\n")
    w("Each library keeps its own licence, reproduced in full below as\n")
    w("those licences require.\n\n")
    w("Generated from the build that produced the binary, so this list is\n")
    w("what is actually inside it.\n\n")

    w("Contents\n" + "-" * 70 + "\n")
    for name in sorted(found, key=str.lower):
        w("  %-24s %s\n" % (name, describe(md.metadata(name))))
    w("\n")

    nolicence = []
    for name in sorted(found, key=str.lower):
        dist = md.distribution(name)
        meta = dist.metadata
        w("\n" + "=" * 70 + "\n")
        w("%s %s\n" % (meta.get("Name"), meta.get("Version")))
        w("Licence: %s\n" % describe(meta))
        for key in ("Home-page", "Project-URL"):
            for v in (meta.get_all(key) or []):
                if "ome" in v or key == "Home-page":
                    w("Homepage: %s\n" % v.split(",", 1)[-1].strip())
                    break
            else:
                continue
            break
        w("=" * 70 + "\n\n")
        t = licence_text(dist)
        if t:
            w(t + "\n")
        else:
            nolicence.append(name)
            w("    This distribution ships no licence file. Its declared\n"
              "    licence is %s; the full text is on its project page.\n"
              % describe(meta))
        w("\n")

    if nolicence:
        sys.stderr.write("no licence file shipped by: %s\n"
                         % ", ".join(nolicence))


if __name__ == "__main__":
    main()
