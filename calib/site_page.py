"""Build the offline on-site page (§10a).

The live dip check runs in a browser on site: a phone or tablet, no network,
no install.  Its logic lives in one file, ``site/site_core.js``; the Node tests
run that file, and the build inlines the same file into the page.  So the page
and the tests can never carry two versions of the rules.

    site/site_core.js   rules and maths (one source)
    site/page.html      page template with a /*@CORE@*/ marker
    site/calib_site.html  the built page: copy this one file to the device
"""

from __future__ import annotations

from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
MARKER = "/*@CORE@*/"


def build_page(site: Path = SITE) -> str:
    template = (site / "page.html").read_text(encoding="utf-8")
    core = (site / "site_core.js").read_text(encoding="utf-8")
    if template.count(MARKER) != 1:
        raise ValueError(f"{site / 'page.html'}: expected one {MARKER} marker")
    if "</script" in core.lower():
        raise ValueError("site_core.js must not contain a closing script tag")
    return template.replace(MARKER, core.rstrip("\n"))


def write_page(out: Path | None = None, site: Path = SITE) -> Path:
    out = Path(out) if out else site / "calib_site.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_page(site), encoding="utf-8", newline="\n")
    return out


def page_is_current(site: Path = SITE) -> bool:
    built = site / "calib_site.html"
    return built.exists() and built.read_text(encoding="utf-8") == build_page(site)
