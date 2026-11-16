"""No secret, id, host name or server code in the public page or the repository.

The values in .env (signup code, D1 id, host names) must stay there.  When
.env exists, every value of it is searched in the built page and in every file
that git tracks or would track.  Without .env (CI) the static checks still run.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "site" / "calib_site.html"
ENV = ROOT / ".env"
GIT = shutil.which("git")

# Text that only the server has: it must never reach the browser.
SERVER_ONLY = ["CREATE TABLE", "deriveBits", "SIGNUP_CODE", "database_id", "workspace_id", "PBKDF2"]


def env_values() -> dict[str, str]:
    if not ENV.exists():
        return {}
    out = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if m and len(m.group(2)) >= 8:
            v = m.group(2).strip("\"'")
            out[m.group(1)] = re.sub(r"^https?://", "", v).rstrip("/")
    return out


def repo_files() -> list[Path]:
    out = subprocess.run(  # noqa: S603
        [GIT, "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return [ROOT / p for p in out.stdout.splitlines() if (ROOT / p).is_file()]


class TestNoLeaks(unittest.TestCase):
    def test_page_holds_no_server_code(self):
        page = PAGE.read_text(encoding="utf-8")
        for s in SERVER_ONLY:
            self.assertNotIn(s, page, f"server text in the public page: {s}")

    def test_wrangler_config_holds_no_id(self):
        cfg = (ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", cfg),
            "a database id in wrangler.jsonc: keep it in .env",
        )

    @unittest.skipUnless(ENV.exists(), "no .env")
    def test_env_values_stay_in_env(self):
        values = env_values()
        page = PAGE.read_text(encoding="utf-8")
        public = ROOT / "site" / "public" / "index.html"
        pub = public.read_text(encoding="utf-8") if public.exists() else ""
        for k, v in values.items():
            self.assertNotIn(v, page, f"{k} is in site/calib_site.html")
            self.assertNotIn(v, pub, f"{k} is in site/public/index.html")

    @unittest.skipUnless(ENV.exists() and GIT, "no .env or no git")
    def test_env_values_not_in_tracked_files(self):
        values = env_values()
        found = []
        for f in repo_files():
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            found += [f"{k} in {f.relative_to(ROOT)}" for k, v in values.items() if v in text]
        self.assertEqual(found, [], "values from .env in files that git tracks")

    @unittest.skipUnless(GIT, "git is not installed")
    def test_env_is_ignored(self):
        out = subprocess.run(  # noqa: S603
            [GIT, "check-ignore", ".env", "wrangler.deploy.jsonc", "site/public/index.html"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(len(out.stdout.split()), 3, "these files must stay out of git")


if __name__ == "__main__":
    unittest.main()
