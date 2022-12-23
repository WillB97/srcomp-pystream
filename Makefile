.PHONY: run check lint type test isort build upload

PYMODULE:=sr.comp.pystream
TESTS:=tests
PYTHON?=python
COMP_API?=http://localhost:5112/comp-api

run:
	source venv/bin/activate
	$(PYTHON) -m $(PYMODULE).__main__ $(COMP_API)

check: lint type

lint:
	flake8 $(PYMODULE) $(TESTS)

type:
	mypy $(PYMODULE)

test:
	pytest --cov=$(PYMODULE) $(TESTS)

isort:
	$(PYTHON) -m isort $(PYMODULE)

build:
	$(PYTHON) -m build

upload:
	twine upload dist/*

clean:
	rm -rf dist/* build/*
