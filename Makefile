PYTHON ?= python3
SRC = src

DOCS = docs
PAGES_URL = https://kejspr.github.io/nominace-mcr-beginner-lske-2026/
PUBLISH_MSG ?= Aktualizace vysledku

.PHONY: help all validate fix aggregate excel verify-nominations presentation pages publish

help:
	@echo "Nominace MCR Beginner - LSKe"
	@echo ""
	@echo "  make                  validate + fix + aggregate + excel + presentation"
	@echo ""
	@echo "Jednotlive kroky:"
	@echo "  make validate             kontrola original/"
	@echo "  make fix                  original/ -> pracovni/"
	@echo "  make aggregate            pracovni/ -> aggregated-results.xml + nomination templates"
	@echo "  make excel                CSV export + Postupuje + nomination log"
	@echo "  make verify-nominations   kontrola nominations/*.txt"
	@echo "  make presentation         HTML prezentace"
	@echo "  make pages                HTML -> docs/index.html (GitHub Pages)"
	@echo "  make publish              all + verify + pages + git push (GitHub Pages)"
	@echo ""
	@echo "Adresare:"
	@echo "  src/                    python skripty"
	@echo "  original/               surova XML"
	@echo "  pracovni/               opravene XML + logy"
	@echo "  nominations/            potvrzene nominace klubu (.txt)"
	@echo "  nominations-declined/   klub nenominuje (.txt)"

all: validate fix aggregate excel presentation
	@echo ""
	@echo "Hotovo: validate + pracovni/ + aggregated-results.xml + CSV + HTML"

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

presentation:
	$(PYTHON) $(SRC)/generate_presentation.py

pages: presentation
	mkdir -p $(DOCS)
	cp results-presentation.html $(DOCS)/index.html
	@echo "GitHub Pages: $(DOCS)/index.html"

publish: all verify-nominations pages
	@if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
		echo "Chyba: neni git repo"; exit 1; \
	fi
	git add original/ nominations/ nominations-declined/ docs/index.html
	@if git diff --staged --quiet; then \
		echo "Nic k publikovani - zadne zmeny"; \
	else \
		git commit -m "$(PUBLISH_MSG)"; \
		git push origin HEAD; \
		echo ""; \
		echo "Odeslano na GitHub. Po dokonceni Actions:"; \
		echo "  $(PAGES_URL)"; \
	fi

.DEFAULT_GOAL := all
