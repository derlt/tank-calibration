.PHONY: test demo gate clean

PY ?= python3

test:
	$(PY) -m unittest discover -s tests -v

demo:
	$(PY) examples/make_demo.py
	$(PY) -m calib fit examples/demo.json -o out/demo
	$(PY) -m calib gate out/demo/demo_workbook.xlsx


gate:
	$(PY) -m calib gate out/demo/demo_workbook.xlsx

clean:
	rm -rf out
