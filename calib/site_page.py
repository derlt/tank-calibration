"""Build the offline on-site page (§10a).

The live dip check runs in a browser on site: a phone or tablet, no network,
no install.  Its logic lives in one file, ``site/site_core.js``; the Node tests
run that file, and the build inlines the same file into the page.  So the page
and the tests can never carry two versions of the rules.

    site/site_core.js   rules and maths (one source)
    site/i18n.js        the page translator and its dictionaries (Vietnamese)
    site/cloud.js       the optional cloud client (worker/index.js is its server)
    site/page.html      page template with /*@CORE@*/, /*@I18N@*/ and /*@CLOUD@*/ markers
    site/calib_site.html  the built page: copy this one file to the device
    site/_headers       the hosted page's security headers; the build writes the
                        hashes of the page's inline scripts into its CSP

The CSP allows only the page's own inline scripts, by their SHA-256 hash, not
'unsafe-inline': a script that gets into the page some other way (an
injection) does not run.  A change to any script changes its hash, so the
build writes the headers again with the page.
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
MARKER = "/*@CORE@*/"
I18N_MARKER = "/*@I18N@*/"
CLOUD_MARKER = "/*@CLOUD@*/"


def build_page(site: Path = SITE) -> str:
    template = (site / "page.html").read_text(encoding="utf-8")
    parts = {
        MARKER: (site / "site_core.js").read_text(encoding="utf-8"),
        I18N_MARKER: (site / "i18n.js").read_text(encoding="utf-8"),
        CLOUD_MARKER: (site / "cloud.js").read_text(encoding="utf-8"),
    }
    for marker, text in parts.items():
        if template.count(marker) != 1:
            raise ValueError(f"{site / 'page.html'}: expected one {marker} marker")
        if "</script" in text.lower():
            raise ValueError(f"the file for {marker} must not contain a closing script tag")
    for marker, text in parts.items():
        template = template.replace(marker, text.rstrip("\n"))
    return template


SCRIPT = re.compile(r"<script(?:\s[^>]*)?>(.*?)</script>", re.S | re.I)
SCRIPT_SRC = re.compile(r"script-src [^;]*;")


def script_hashes(page: str) -> list[str]:
    """The CSP source of each inline script of the page: 'sha256-<base64>'."""
    out = []
    for m in SCRIPT.finditer(page):
        digest = hashlib.sha256(m.group(1).encode("utf-8")).digest()
        out.append("'sha256-" + base64.b64encode(digest).decode("ascii") + "'")
    return out


def build_headers(site: Path = SITE, page: str | None = None) -> str:
    """site/_headers with the script-src of the current page's inline scripts."""
    text = (site / "_headers").read_text(encoding="utf-8")
    lines = text.split("\n")
    csp = [i for i, ln in enumerate(lines) if ln.strip().startswith("Content-Security-Policy:")]
    if len(csp) != 1 or len(SCRIPT_SRC.findall(lines[csp[0]])) != 1:
        raise ValueError(f"{site / '_headers'}: expected one CSP line with one script-src directive")
    hashes = script_hashes(build_page(site) if page is None else page)
    i = csp[0]
    lines[i] = SCRIPT_SRC.sub(lambda _m: "script-src " + " ".join(hashes) + ";", lines[i])
    return "\n".join(lines)


def write_page(out: Path | None = None, site: Path = SITE) -> Path:
    out = Path(out) if out else site / "calib_site.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    page = build_page(site)
    out.write_text(page, encoding="utf-8", newline="\n")
    headers = build_headers(site, page)
    if (site / "_headers").read_text(encoding="utf-8") != headers:
        (site / "_headers").write_text(headers, encoding="utf-8", newline="\n")
    return out


def page_is_current(site: Path = SITE) -> bool:
    built = site / "calib_site.html"
    if not built.exists():
        return False
    page = build_page(site)
    return built.read_text(encoding="utf-8") == page and headers_are_current(site, page)


def headers_are_current(site: Path = SITE, page: str | None = None) -> bool:
    return (site / "_headers").read_text(encoding="utf-8") == build_headers(site, page)
