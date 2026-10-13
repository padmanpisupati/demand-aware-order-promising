PY ?= python
.PHONY: demo test samples clean
demo:
	PYTHONPATH=src $(PY) -m dop.demo
test:
	$(PY) -m pytest -q
samples:
	$(PY) scripts/generate_samples.py
clean:
	rm -rf out .pytest_cache **/__pycache__
