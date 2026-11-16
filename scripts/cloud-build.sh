#!/bin/sh
# Build the Worker's static assets from the committed page.
#
# site/public/ is built, not committed: a fresh git checkout has no such
# directory, and a Cloudflare Workers Build that deploys the repository
# straight away fails with
#   The directory specified by the "assets.directory" field ... does not exist
# The built page is committed as site/calib_site.html (tests/test_site.py
# fails when it is stale), so this build is a copy and needs no Python.
#
#   sh scripts/cloud-build.sh [out-dir]        default out-dir: site/public
#
# This is the build command of the Workers Build in the Cloudflare
# dashboard (docs/cloud.md): it refreshes site/public from the committed page
# and writes the deploy config with the D1 id from the build variables.
#
# With D1_DATABASE_ID set (a Workers Build variable), it also writes
# wrangler.deploy.jsonc with the real database id.  The committed
# wrangler.jsonc keeps the placeholder "D1_DATABASE_ID", so no id goes into
# git; the deploy command then uses --config wrangler.deploy.jsonc.
set -eu
out=${1:-site/public}
mkdir -p "$out"
cp site/calib_site.html "$out/index.html"
cp site/_headers "$out/_headers"
if [ -n "${D1_DATABASE_ID:-}" ]; then
  sed "s|\"D1_DATABASE_ID\"|\"$D1_DATABASE_ID\"|" wrangler.jsonc > wrangler.deploy.jsonc
fi
