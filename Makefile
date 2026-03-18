# Makefile for Pi Photo Display
# Usage: make [target]
#
# Run on the Raspberry Pi where the project is cloned.

SHELL := /bin/bash
INSTALL_DIR := /opt/pi-photo-display
REPO_DIR := $(shell pwd)
SERVICES := slideshow photo-upload wifi-manager

.PHONY: install uninstall update status logs test help

help: ## Show this help message
	@echo "Pi Photo Display - Available targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  make %-12s %s\n", $$1, $$2}'
	@echo ""

install: ## Run the installer (requires sudo)
	@if [ "$$(id -u)" -ne 0 ]; then \
		echo "ERROR: Run with sudo: sudo make install"; \
		exit 1; \
	fi
	bash $(REPO_DIR)/install.sh

uninstall: ## Remove services, sudoers, cron entries, install dir (preserves media)
	@if [ "$$(id -u)" -ne 0 ]; then \
		echo "ERROR: Run with sudo: sudo make uninstall"; \
		exit 1; \
	fi
	@echo "========================================"
	@echo "  Pi Photo Display - Uninstall"
	@echo "========================================"
	@echo ""
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
	@rm -f /etc/sudoers.d/pi-photo-display
	@echo ""
	@# Remove cron entries for HDMI schedule
	@echo "Removing cron entries..."
	@PI_USER=$${SUDO_USER:-$$(logname 2>/dev/null || true)}; \
	if [ -n "$$PI_USER" ] && [ "$$PI_USER" != "root" ]; then \
		crontab -u "$$PI_USER" -l 2>/dev/null | grep -v "hdmi-control" | crontab -u "$$PI_USER" - 2>/dev/null || true; \
	fi
	@echo ""
	@# Remove avahi service
	@echo "Removing mDNS service advertisement..."
	@rm -f /etc/avahi/services/pi-photo-display.service
	@systemctl restart avahi-daemon 2>/dev/null || true
	@echo ""
	@# Remove journald config
	@echo "Removing journald overrides..."
	@rm -f /etc/systemd/journald.conf.d/pi-photo-display.conf
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
	@echo "  Pi Photo Display - Update"
	@echo "========================================"
	@echo ""
	@echo "Pulling latest changes..."
	@cd $(REPO_DIR) && sudo -u $${SUDO_USER:-$$(logname 2>/dev/null)} git pull --ff-only || \
		{ echo "ERROR: git pull failed. Resolve conflicts manually."; exit 1; }
	@echo ""
	@echo "Re-running installer (config will be preserved)..."
	@bash $(REPO_DIR)/install.sh

status: ## Show status of all services
	@echo "========================================"
	@echo "  Pi Photo Display - Service Status"
	@echo "========================================"
	@echo ""
	@for svc in $(SERVICES); do \
		printf "%-20s " "$$svc:"; \
		systemctl is-active $$svc 2>/dev/null || echo "not found"; \
	done
	@echo ""
	@echo "--- VLC Process ---"
	@pgrep -a vlc 2>/dev/null || echo "  VLC is not running"
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
	@echo "--- Hardware Watchdog ---"
	@systemctl is-active watchdog 2>/dev/null && echo "  Watchdog: active" || echo "  Watchdog: inactive"
	@echo ""
	@echo "--- Disk Usage ---"
	@df -h / 2>/dev/null | tail -1 | awk '{printf "  Root filesystem: %s used of %s (%s)\n", $$3, $$2, $$5}'
	@echo ""

logs: ## Show recent logs from all services
	@echo "========================================"
	@echo "  Pi Photo Display - Recent Logs"
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
