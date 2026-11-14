.PHONY: test lint coverage demo gate site deploy deploy-dry clean

PY ?= uv run python

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

gate:
	$(PY) -m calib gate out/demo/demo_workbook.xlsx

site:
	$(PY) -m calib site-page

# Publish the on-site page as a Cloudflare Worker with static assets.
# Needs a Cloudflare login: `npx wrangler login`, or CLOUDFLARE_API_TOKEN.
deploy:
	$(PY) -m calib site-page --check
	$(PY) -m calib site-page -o site/public/index.html
	npx wrangler@4 deploy

deploy-dry:
	$(PY) -m calib site-page --check
	$(PY) -m calib site-page -o site/public/index.html
	npx wrangler@4 deploy --dry-run

clean:
	rm -rf out
