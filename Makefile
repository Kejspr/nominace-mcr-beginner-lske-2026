PYTHON ?= python3
SRC = src

DOCS = docs
PAGES_URL = https://kejspr.github.io/nominace-mcr-beginner-lske-2026/
PUBLISH_MSG ?= Aktualizace vysledku

.PHONY: help deploy deploy-site build pages validate fix aggregate excel verify-nominations final-export git-push publish all vse deploy-pages

help:
	@echo "Nominace MCR Beginner - LSKe (GitHub Pages)"
	@echo ""
	@echo "  make deploy         kompletni WF: validate -> fix -> aggregate -> deploy-site + push"
	@echo "  make deploy-site    excel + HTML + verify-nominations (bez git push)"
	@echo ""
	@echo "Jednotlive kroky:"
	@echo "  make validate             kontrola original/"
	@echo "  make fix                  original/ -> pracovni/"
	@echo "  make aggregate            pracovni/ -> aggregated-results.xml"
	@echo "  make excel                CSV + Postupuje + nomination log"
	@echo "  make final-export         konecny seznam postupujicich (CSV, TSV, TXT, HTML)"
	@echo "  make pages                HTML -> docs/index.html (vyzaduje excel)"
	@echo "  make verify-nominations   kontrola nominations/*.txt"
	@echo ""
	@echo "Volitelne:"
	@echo "  make build          jen data: validate + fix + aggregate + excel"
	@echo ""
	@echo "Zpetna kompatibilita:"
	@echo "  make deploy-pages = make deploy"
	@echo "  make publish      = make deploy"
	@echo "  make vse          = make deploy"

deploy: validate fix aggregate deploy-site git-push
	@echo ""
	@echo "Deploy hotovo: $(PAGES_URL) (po dokonceni Actions)"

deploy-site: excel pages verify-nominations

build: validate fix aggregate excel
	@echo ""
	@echo "Build hotovo: pracovni/ + aggregated-results.xml + CSV"

pages:
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

final-export: excel
	$(PYTHON) $(SRC)/generate_final_export.py

verify-nominations:
	$(PYTHON) $(SRC)/verify_categories.py

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

deploy-pages: deploy

publish: deploy

vse: deploy

all: build pages

.DEFAULT_GOAL := help
