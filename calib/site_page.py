"""Build the offline on-site page (§10a).

The live dip check runs in a browser on site: a phone or tablet, no network,
no install.  Its logic lives in one file, ``site/site_core.js``; the Node tests
run that file, and the build inlines the same file into the page.  So the page
and the tests can never carry two versions of the rules.

    site/site_core.js   rules and maths (one source)
    site/i18n.js        the page translator and its dictionaries (Vietnamese)
    site/page.html      page template with a /*@CORE@*/ and an /*@I18N@*/ marker
    site/calib_site.html  the built page: copy this one file to the device
"""

from __future__ import annotations

from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
MARKER = "/*@CORE@*/"
I18N_MARKER = "/*@I18N@*/"


def build_page(site: Path = SITE) -> str:
    template = (site / "page.html").read_text(encoding="utf-8")
    parts = {
        MARKER: (site / "site_core.js").read_text(encoding="utf-8"),
        I18N_MARKER: (site / "i18n.js").read_text(encoding="utf-8"),
    }
    for marker, text in parts.items():
        if template.count(marker) != 1:
            raise ValueError(f"{site / 'page.html'}: expected one {marker} marker")
        if "</script" in text.lower():
            raise ValueError(f"the file for {marker} must not contain a closing script tag")
    for marker, text in parts.items():
        template = template.replace(marker, text.rstrip("\n"))
    return template


def write_page(out: Path | None = None, site: Path = SITE) -> Path:
    out = Path(out) if out else site / "calib_site.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_page(site), encoding="utf-8", newline="\n")
    return out


def page_is_current(site: Path = SITE) -> bool:
    built = site / "calib_site.html"
    return built.exists() and built.read_text(encoding="utf-8") == build_page(site)
