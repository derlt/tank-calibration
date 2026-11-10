.PHONY: test lint coverage demo gate clean

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

clean:
	rm -rf out
