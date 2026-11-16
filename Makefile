.PHONY: test lint coverage demo demo-drain gate site deploy deploy-dry deploy-config db-schema clean

PY ?= uv run python

# Ids and host names live in .env (not committed), never in tracked files.
-include .env
DEPLOY_CFG := wrangler.deploy.jsonc

test:
	$(PY) -m unittest discover -s tests -v

lint:
	uv run ruff check .

coverage:
	$(PY) -m coverage run -m unittest discover -s tests
	$(PY) -m coverage report -m

demo:
	$(PY) examples/make_demo.py
	$(PY) -m calib fit examples/demo.json -o out/demo
	$(PY) -m calib gate out/demo/demo_workbook.xlsx

demo-drain:
	$(PY) examples/make_demo_drain.py
	$(PY) -m calib fit examples/demo_drain.json -o out/demo_drain
	$(PY) -m calib gate out/demo_drain/demo_drain_workbook.xlsx

gate:
	$(PY) -m calib gate out/demo/demo_workbook.xlsx

site:
	$(PY) -m calib site-page

# Create the cloud tables in D1 (once; running it again changes nothing).
db-schema: deploy-config
	npx wrangler@4 d1 execute tank-calibration --remote --config $(DEPLOY_CFG) --file worker/schema.sql

# wrangler.jsonc with the D1 id from .env.  Not committed (.gitignore).
deploy-config:
	@test -n "$(D1_DATABASE_ID)" || { echo "Set D1_DATABASE_ID in .env"; exit 1; }
	@test -n "$(API_HOSTS)" || { echo "Set API_HOSTS in .env (the main host name of the page)"; exit 1; }
	@sed 's/"D1_DATABASE_ID"/"$(D1_DATABASE_ID)"/' wrangler.jsonc > $(DEPLOY_CFG)

# Publish the on-site page as a Cloudflare Worker with static assets.
# Needs a Cloudflare login: `npx wrangler login`, or CLOUDFLARE_API_TOKEN.
deploy:
	$(PY) -m calib site-page --check
	$(PY) -m calib site-page -o site/public/index.html
	cp site/_headers site/public/_headers
	$(MAKE) deploy-config
	npx wrangler@4 deploy --config $(DEPLOY_CFG) --var API_HOSTS:$(API_HOSTS)

deploy-dry:
	$(PY) -m calib site-page --check
	$(PY) -m calib site-page -o site/public/index.html
	cp site/_headers site/public/_headers
	$(MAKE) deploy-config
	npx wrangler@4 deploy --config $(DEPLOY_CFG) --var API_HOSTS:$(API_HOSTS) --dry-run

clean:
	rm -rf out
