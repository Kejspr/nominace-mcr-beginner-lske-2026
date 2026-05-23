PYTHON ?= python3
SRC = src

DOCS = docs

.PHONY: help all validate fix aggregate excel verify-nominations presentation pages

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

.DEFAULT_GOAL := all
