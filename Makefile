.PHONY: install run doctor test lint clean

install:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --reload

doctor:
	python -m app.doctor

test:
	python -m pytest -q

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
