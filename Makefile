PYTHON ?= python3
SRC = src

DOCS = docs
PAGES_URL = https://kejspr.github.io/nominace-mcr-beginner-lske-2026/
PUBLISH_MSG ?= Aktualizace vysledku

.PHONY: help build pages deploy deploy-pages validate fix aggregate excel verify-nominations git-push publish all vse

help:
	@echo "Nominace MCR Beginner - LSKe (GitHub Pages)"
	@echo ""
	@echo "  make build          data: validate + fix + aggregate + excel"
	@echo "  make pages          build + HTML -> docs/index.html"
	@echo "  make deploy         alias pro deploy-pages"
	@echo "  make deploy-pages   build + git push -> GitHub Pages"
	@echo ""
	@echo "Jednotlive kroky:"
	@echo "  make validate             kontrola original/"
	@echo "  make fix                  original/ -> pracovni/"
	@echo "  make aggregate            pracovni/ -> aggregated-results.xml"
	@echo "  make excel                CSV + Postupuje + nomination log"
	@echo "  make verify-nominations   kontrola nominations/*.txt"
	@echo ""
	@echo "Zpetna kompatibilita:"
	@echo "  make publish = make deploy-pages"
	@echo "  make vse     = make deploy-pages"
	@echo "  make all     = make pages"

build: validate fix aggregate excel
	@echo ""
	@echo "Build hotovo: pracovni/ + aggregated-results.xml + CSV"

pages: build
	mkdir -p $(DOCS)
	$(PYTHON) $(SRC)/generate_presentation.py --output $(DOCS)/index.html
	@echo ""
	@echo "HTML: $(DOCS)/index.html"

validate:
	$(PYTHON) $(SRC)/validate_data.py

fix:
	$(PYTHON) $(SRC)/fix_xml_data.py

aggregate:
	$(PYTHON) $(SRC)/aggregate_results.py

excel:
	$(PYTHON) $(SRC)/generate_excel_export.py

verify-nominations:
	$(PYTHON) $(SRC)/verify_categories.py

deploy-pages: pages verify-nominations git-push
	@echo ""
	@echo "GitHub Pages: $(PAGES_URL) (po dokonceni Actions)"

deploy: deploy-pages

git-push:
	@if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
		echo "Chyba: neni git repo"; exit 1; \
	fi
	git add docs/index.html original/ nominations/ nominations-declined/ src/ Makefile .github/
	@if git diff --staged --quiet; then \
		echo "Nic k publikovani - zadne zmeny"; \
	else \
		git commit -m "$(PUBLISH_MSG)"; \
		git push origin HEAD; \
		echo "Odeslano na GitHub."; \
	fi

publish: deploy-pages

vse: deploy-pages

all: pages

.DEFAULT_GOAL := build
