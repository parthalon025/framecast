# Makefile for FrameCast
# Usage: make [target]
#
# Run on the Raspberry Pi where the project is cloned.

SHELL := /bin/bash
INSTALL_DIR := /opt/framecast
REPO_DIR := $(shell pwd)
SERVICES := framecast framecast-kiosk
TIMERS := framecast-update

.PHONY: install uninstall update status logs test help build-frontend dev run build-image pytest typecheck benchmark mutate test-frontend test-shell test-all

help: ## Show this help message
	@echo "FrameCast - Available targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  make %-16s %s\n", $$1, $$2}'
	@echo ""

build-frontend: ## Build the Preact frontend
	cd app/frontend && npm run build

dev: ## Run gunicorn in dev mode (auto-reload)
	cd app && gunicorn -c gunicorn.conf.py --reload web_upload:app

run: ## Run gunicorn in production mode
	cd app && gunicorn -c gunicorn.conf.py web_upload:app

build-image: ## Run pi-gen build to produce SD card image
	@echo "Building FrameCast SD card image with pi-gen..."
	@if [ -d pi-gen ]; then \
		cd pi-gen && sudo ./build.sh; \
	else \
		echo "ERROR: pi-gen directory not found. Clone pi-gen first."; \
		exit 1; \
	fi

install: ## Run the installer (requires sudo)
	@if [ "$$(id -u)" -ne 0 ]; then \
		echo "ERROR: Run with sudo: sudo make install"; \
		exit 1; \
	fi
	bash $(REPO_DIR)/install.sh

uninstall: ## Remove services, timers, sudoers, install dir (preserves media)
	@if [ "$$(id -u)" -ne 0 ]; then \
		echo "ERROR: Run with sudo: sudo make uninstall"; \
		exit 1; \
	fi
	@echo "========================================"
	@echo "  FrameCast - Uninstall"
	@echo "========================================"
	@echo ""
	@# Stop and disable timers
	@for tmr in $(TIMERS); do \
		echo "Stopping timer $$tmr..."; \
		systemctl stop $$tmr.timer 2>/dev/null || true; \
		systemctl disable $$tmr.timer 2>/dev/null || true; \
		rm -f /etc/systemd/system/$$tmr.timer; \
		rm -f /etc/systemd/system/$$tmr.service; \
	done
	@# Stop and disable services
	@for svc in $(SERVICES); do \
		echo "Stopping $$svc..."; \
		systemctl stop $$svc 2>/dev/null || true; \
		systemctl disable $$svc 2>/dev/null || true; \
		rm -f /etc/systemd/system/$$svc.service; \
	done
	@systemctl daemon-reload
	@echo ""
	@# Remove sudoers entries
	@echo "Removing sudoers entries..."
	@rm -f /etc/sudoers.d/framecast
	@echo ""
	@# Remove avahi service
	@echo "Removing mDNS service advertisement..."
	@rm -f /etc/avahi/services/framecast.service
	@systemctl restart avahi-daemon 2>/dev/null || true
	@echo ""
	@# Remove journald config
	@echo "Removing journald overrides..."
	@rm -f /etc/systemd/journald.conf.d/framecast.conf
	@echo ""
	@# Remove install directory but preserve media
	@echo "Removing install directory $(INSTALL_DIR)..."
	@echo "  (Your media files are preserved in ~/media/)"
	@rm -rf $(INSTALL_DIR)
	@echo ""
	@echo "========================================"
	@echo "  Uninstall complete."
	@echo ""
	@echo "  Your photos in ~/media/ were NOT deleted."
	@echo "  To remove them: rm -rf ~/media/"
	@echo "========================================"

update: ## Pull latest changes and re-run installer (preserves config)
	@if [ "$$(id -u)" -ne 0 ]; then \
		echo "ERROR: Run with sudo: sudo make update"; \
		exit 1; \
	fi
	@echo "========================================"
	@echo "  FrameCast - Update"
	@echo "========================================"
	@echo ""
	@echo "Pulling latest changes..."
	@cd $(REPO_DIR) && sudo -u $${SUDO_USER:-$$(logname 2>/dev/null)} git pull --ff-only || \
		{ echo "ERROR: git pull failed. Resolve conflicts manually."; exit 1; }
	@echo ""
	@echo "Re-running installer (config will be preserved)..."
	@bash $(REPO_DIR)/install.sh

status: ## Show status of all services and timers
	@echo "========================================"
	@echo "  FrameCast - Service Status"
	@echo "========================================"
	@echo ""
	@echo "--- Services ---"
	@for svc in $(SERVICES); do \
		printf "  %-24s " "$$svc:"; \
		systemctl is-active $$svc 2>/dev/null || echo "not found"; \
	done
	@echo ""
	@echo "--- Timers ---"
	@for tmr in $(TIMERS); do \
		printf "  %-24s " "$$tmr:"; \
		systemctl is-active $$tmr.timer 2>/dev/null || echo "not found"; \
	done
	@echo ""
	@echo "--- Web Server ---"
	@PORT=$$(grep "^WEB_PORT=" $(INSTALL_DIR)/app/.env 2>/dev/null | cut -d= -f2 || echo "8080"); \
	if command -v curl &>/dev/null; then \
		HTTP_CODE=$$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$${PORT:-8080}/" 2>/dev/null || echo "000"); \
		if [ "$$HTTP_CODE" = "200" ]; then \
			echo "  Web UI responding on port $${PORT:-8080} (HTTP $$HTTP_CODE)"; \
		else \
			echo "  Web UI NOT responding on port $${PORT:-8080} (HTTP $$HTTP_CODE)"; \
		fi; \
	else \
		echo "  curl not installed, skipping web check"; \
	fi
	@echo ""
	@echo "--- Disk Usage ---"
	@df -h / 2>/dev/null | tail -1 | awk '{printf "  Root filesystem: %s used of %s (%s)\n", $$3, $$2, $$5}'
	@echo ""

logs: ## Show recent logs from all services
	@echo "========================================"
	@echo "  FrameCast - Recent Logs"
	@echo "========================================"
	@for svc in $(SERVICES); do \
		echo ""; \
		echo "--- $$svc (last 20 lines) ---"; \
		journalctl -u $$svc --no-pager -n 20 2>/dev/null || echo "  No logs available"; \
	done

test: ## Run smoke tests to verify installation
	@echo "Running smoke tests..."
	@if [ -x $(REPO_DIR)/scripts/smoke-test.sh ]; then \
		bash $(REPO_DIR)/scripts/smoke-test.sh; \
	else \
		echo "ERROR: scripts/smoke-test.sh not found"; \
		exit 1; \
	fi

pytest: ## Run pytest suite
	python3 -m pytest tests/ -v --timeout=120

typecheck: ## Run mypy strict type checking
	python3 -m mypy --config-file mypy.ini app/modules/ app/sse.py

benchmark: ## Run performance benchmarks
	python3 -m pytest tests/test_benchmarks.py --benchmark-only -v

mutate: ## Run mutation testing (on-demand diagnostic, config in setup.cfg)
	python3 -m mutmut run

test-frontend: ## Run frontend unit tests (vitest)
	cd app/frontend && npx vitest run

test-shell: ## Run shell script tests (bats)
	bats tests/shell/

test-all: pytest test-frontend test-shell ## Run all test suites
	@echo "All tests passed."
