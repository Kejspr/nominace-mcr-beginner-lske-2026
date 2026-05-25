PYTHON ?= python3
SRC = src

DOCS = docs
WORKERS_SITE = workers-site
PRIVATE_HTML = results-presentation.html
PAGES_URL = https://kejspr.github.io/nominace-mcr-beginner-lske-2026/
WORKERS_URL = https://nominace-mcr-beginner-lske-2026.jan-kaspar.workers.dev
PUBLISH_MSG ?= Aktualizace vysledku

.PHONY: help \
	build build-public build-private \
	validate fix aggregate excel verify-nominations presentation pages \
	deploy deploy-pages deploy-workers workers-upload deploy-api \
	git-push git-push-pages git-push-api git-push-all git-push-internal \
	sync-trainers trainers-init \
	all publish workers vse

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

help:
	@echo "Nominace MCR Beginner - LSKe"
	@echo ""
	@echo "BUILD (lokalne, bez deploy):"
	@echo "  make build            data: validate + fix + aggregate + excel"
	@echo "  make build-public     build + verejny HTML -> docs/index.html"
	@echo "  make build-private    build + privatni HTML -> results-presentation.html"
	@echo ""
	@echo "DEPLOY staticky web:"
	@echo "  make deploy-pages     build-public + git push (GitHub Pages)"
	@echo "  make deploy-workers   build-private + wrangler (Cloudflare, bez gitu)"
	@echo ""
	@echo "DEPLOY API + infra:"
	@echo "  make deploy-api       git push dat pro Render (nominace, XML, api/)"
	@echo "  make sync-trainers    trainers.yaml -> Cloudflare Access + Render env"
	@echo ""
	@echo "DEPLOY vse:"
	@echo "  make deploy           build + Workers + jeden git push (Pages + Render)"
	@echo ""
	@echo "Jednotlive kroky dat:"
	@echo "  make validate             kontrola original/"
	@echo "  make fix                  original/ -> pracovni/"
	@echo "  make aggregate            pracovni/ -> aggregated-results.xml"
	@echo "  make excel                CSV + Postupuje + nomination log"
	@echo "  make verify-nominations   kontrola nominations/*.txt"
	@echo "  make presentation         privatni HTML (Workers)"
	@echo "  make pages                verejny HTML (GitHub Pages)"
	@echo "  make trainers-init        doplni trainers.yaml o kluby z XML"
	@echo ""
	@echo "Zpetna kompatibilita:"
	@echo "  make                    = build (jen data)"
	@echo "  make all                = build-private"
	@echo "  make publish            = deploy-pages"
	@echo "  make workers            = deploy-workers"
	@echo "  make vse                = deploy"
	@echo ""
	@echo "Adresare:"
	@echo "  docs/                   verejny staticky web (GitHub Pages)"
	@echo "  workers-site/           privatni staticky web (Cloudflare Workers)"
	@echo "  api/                    backend pro nominace (Render)"

# ---------------------------------------------------------------------------
# BUILD - lokalni pipeline dat a HTML (zadne tokeny, zadny git, zadny wrangler)
# ---------------------------------------------------------------------------

build: validate fix aggregate excel
	@echo ""
	@echo "Build hotovo: pracovni/ + aggregated-results.xml + CSV"

build-public: pages
	@echo ""
	@echo "Verejny HTML: $(DOCS)/index.html"

build-private: presentation
	@echo ""
	@echo "Privatni HTML: $(PRIVATE_HTML)"

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

pages: build
	mkdir -p $(DOCS)
	$(PYTHON) $(SRC)/generate_presentation.py --mode public --output $(DOCS)/index.html

presentation: build
	$(PYTHON) $(SRC)/generate_presentation.py --mode private --output $(PRIVATE_HTML)

# ---------------------------------------------------------------------------
# DEPLOY - staticky web (GitHub Pages + Cloudflare Workers)
# ---------------------------------------------------------------------------

deploy-pages: build-public verify-nominations git-push-pages
	@echo ""
	@echo "GitHub Pages: $(PAGES_URL) (po dokonceni Actions)"

workers-upload:
	mkdir -p $(WORKERS_SITE)
	cp $(PRIVATE_HTML) $(WORKERS_SITE)/index.html
	npx wrangler deploy
	@echo ""
	@echo "Cloudflare Workers: $(WORKERS_URL)"

deploy-workers: build-private workers-upload

# ---------------------------------------------------------------------------
# DEPLOY - API (Render auto-deploy z git push)
# ---------------------------------------------------------------------------

deploy-api: verify-nominations git-push-api
	@echo ""
	@echo "Render API: redeploy z git push (~ par minut)"

# ---------------------------------------------------------------------------
# DEPLOY - vse najednou
# ---------------------------------------------------------------------------

deploy: build-public build-private verify-nominations workers-upload git-push-all
	@echo ""
	@echo "Hotovo - vse nasazeno:"
	@echo "  GitHub Pages: $(PAGES_URL)"
	@echo "  Workers:      $(WORKERS_URL)"
	@echo "  Render API:   automaticky z git push"

# ---------------------------------------------------------------------------
# Git push - oddelene soubory podle cile deploye
# ---------------------------------------------------------------------------

git-push-pages:
	@$(MAKE) git-push-internal FILES="docs/index.html original/ nominations/ nominations-declined/ src/ Makefile"

git-push-api:
	@$(MAKE) git-push-internal FILES="original/ nominations/ nominations-declined/ api/ src/ render.yaml Makefile"

git-push-all:
	@$(MAKE) git-push-internal FILES="docs/index.html original/ nominations/ nominations-declined/ api/ src/ render.yaml Makefile"

git-push-internal:
	@if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
		echo "Chyba: neni git repo"; exit 1; \
	fi
	git add $(FILES)
	@if git diff --staged --quiet; then \
		echo "Nic k publikovani - zadne zmeny"; \
	else \
		git commit -m "$(PUBLISH_MSG)"; \
		git push origin HEAD; \
		echo "Odeslano na GitHub."; \
	fi

# ---------------------------------------------------------------------------
# INFRA - Cloudflare Access + Render env (mimo git push dat)
# ---------------------------------------------------------------------------

sync-trainers:
	$(PYTHON) -m pip install -q certifi 2>/dev/null || true
	$(PYTHON) tools/sync_trainers.py

trainers-init:
	$(PYTHON) tools/generate_trainers_yaml.py

# ---------------------------------------------------------------------------
# Zpetna kompatibilita
# ---------------------------------------------------------------------------

all: build-private

publish: deploy-pages

workers: deploy-workers

vse: deploy

git-push: git-push-all

.DEFAULT_GOAL := build
