"""Tests for app/modules/wifi.py — WiFi provisioning via NetworkManager.

Verifies nmcli command construction, AP lifecycle, connect-stops-AP-first,
scan parsing, and timeout handler behavior. All subprocess calls are mocked.
"""

import subprocess
import threading
from unittest.mock import MagicMock, call, patch

import pytest

from modules import wifi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_run_result(rc=0, stdout="", stderr=""):
    """Build a mock subprocess.run return value."""
    return MagicMock(returncode=rc, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# is_connected
# ---------------------------------------------------------------------------


class TestIsConnected:
    """Tests for wifi.is_connected()."""

    @patch("modules.wifi.subprocess.run")
    def test_connected_returns_true(self, mock_run):
        mock_run.return_value = _mock_run_result(
            stdout="GENERAL.STATE:100 (connected)"
        )
        assert wifi.is_connected() is True

    @patch("modules.wifi.subprocess.run")
    def test_disconnected_returns_false(self, mock_run):
        mock_run.return_value = _mock_run_result(
            stdout="GENERAL.STATE:30 (disconnected)"
        )
        assert wifi.is_connected() is False

    @patch("modules.wifi.subprocess.run")
    def test_command_failure_returns_false(self, mock_run):
        mock_run.return_value = _mock_run_result(rc=1, stderr="error")
        assert wifi.is_connected() is False

    @patch("modules.wifi.subprocess.run")
    def test_timeout_returns_false(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="nmcli", timeout=15)
        assert wifi.is_connected() is False


# ---------------------------------------------------------------------------
# is_ap_active
# ---------------------------------------------------------------------------


class TestIsApActive:
    """Tests for wifi.is_ap_active() — checks Hotspot profile on wlan0."""

    @patch("modules.wifi.subprocess.run")
    def test_hotspot_active_returns_true(self, mock_run):
        mock_run.return_value = _mock_run_result(
            stdout="GENERAL.CONNECTION:Hotspot"
        )
        assert wifi.is_ap_active() is True

    @patch("modules.wifi.subprocess.run")
    def test_normal_connection_returns_false(self, mock_run):
        mock_run.return_value = _mock_run_result(
            stdout="GENERAL.CONNECTION:MyHomeWiFi"
        )
        assert wifi.is_ap_active() is False

    @patch("modules.wifi.subprocess.run")
    def test_no_connection_returns_false(self, mock_run):
        mock_run.return_value = _mock_run_result(
            stdout="GENERAL.CONNECTION:--"
        )
        assert wifi.is_ap_active() is False

    @patch("modules.wifi.subprocess.run")
    def test_command_failure_returns_false(self, mock_run):
        mock_run.return_value = _mock_run_result(rc=1, stderr="error")
        assert wifi.is_ap_active() is False


# ---------------------------------------------------------------------------
# connect — stops AP first
# ---------------------------------------------------------------------------


class TestConnect:
    """Tests for wifi.connect() including AP-stop-before-connect behavior."""

    @patch("modules.wifi.time.sleep")
    @patch("modules.wifi.subprocess.run")
    def test_connect_success(self, mock_run, mock_sleep):
        # First call: is_ap_active check (not active)
        # Second call: actual connect
        mock_run.side_effect = [
            _mock_run_result(stdout="GENERAL.CONNECTION:--"),  # is_ap_active
            _mock_run_result(rc=0, stdout="connected"),  # connect
        ]
        success, msg = wifi.connect("TestNet", "pass123")
        assert success is True
        assert "TestNet" in msg

    @patch("modules.wifi.time.sleep")
    @patch("modules.wifi.subprocess.run")
    def test_connect_stops_ap_first(self, mock_run, mock_sleep):
        # is_ap_active returns True, then stop_ap, then connect
        mock_run.side_effect = [
            _mock_run_result(stdout="GENERAL.CONNECTION:Hotspot"),  # is_ap_active
            _mock_run_result(rc=0),  # stop_ap: nmcli connection down Hotspot
            _mock_run_result(rc=0, stdout="connected"),  # connect
        ]
        # Patch out the timer/marker internals that stop_ap touches
        with patch.object(wifi, "_cancel_ap_timer"), \
             patch.object(wifi, "_clear_ap_marker"):
            success, msg = wifi.connect("TestNet", "pass123")

        assert success is True
        # sleep(2) should have been called for the AP release delay
        mock_sleep.assert_called_with(2)

    @patch("modules.wifi.time.sleep")
    @patch("modules.wifi.subprocess.run")
    def test_connect_auth_failure(self, mock_run, mock_sleep):
        mock_run.side_effect = [
            _mock_run_result(stdout="GENERAL.CONNECTION:--"),  # is_ap_active
            _mock_run_result(rc=1, stderr="secrets were required"),  # connect
        ]
        success, msg = wifi.connect("TestNet", "wrongpass")
        assert success is False
        assert "AUTH FAILED" in msg

    @patch("modules.wifi.time.sleep")
    @patch("modules.wifi.subprocess.run")
    def test_connect_network_not_found(self, mock_run, mock_sleep):
        mock_run.side_effect = [
            _mock_run_result(stdout="GENERAL.CONNECTION:--"),  # is_ap_active
            _mock_run_result(rc=1, stderr="no network with SSID"),  # connect
        ]
        success, msg = wifi.connect("GhostNet", "pass")
        assert success is False
        assert "NOT FOUND" in msg


# ---------------------------------------------------------------------------
# start_ap
# ---------------------------------------------------------------------------


class TestStartAp:
    """Tests for wifi.start_ap() — creates hotspot via nmcli."""

    @patch.object(wifi, "_start_ap_timer")
    @patch.object(wifi, "_write_ap_marker")
    @patch("modules.wifi.subprocess.run")
    def test_start_ap_success(self, mock_run, mock_marker, mock_timer):
        # First call: get_ap_ssid MAC lookup
        # Second call: nmcli hotspot create
        mock_run.side_effect = [
            _mock_run_result(stdout="GENERAL.HWADDR:AA:BB:CC:DD:EE:FF"),
            _mock_run_result(rc=0, stdout="Connection successfully activated"),
        ]
        success, msg = wifi.start_ap()
        assert success is True
        assert "EEFF" in msg  # Last 4 hex chars of MAC
        mock_marker.assert_called_once()
        mock_timer.assert_called_once()

    @patch.object(wifi, "_start_ap_timer")
    @patch.object(wifi, "_write_ap_marker")
    @patch("modules.wifi.subprocess.run")
    def test_start_ap_custom_ssid(self, mock_run, mock_marker, mock_timer):
        mock_run.return_value = _mock_run_result(rc=0)
        success, msg = wifi.start_ap(ssid="CustomAP")
        assert success is True
        assert "CustomAP" in msg

    @patch("modules.wifi.subprocess.run")
    def test_start_ap_failure(self, mock_run):
        mock_run.side_effect = [
            _mock_run_result(stdout="GENERAL.HWADDR:AA:BB:CC:DD:EE:FF"),
            _mock_run_result(rc=1, stderr="Error: could not create hotspot"),
        ]
        success, msg = wifi.start_ap()
        assert success is False
        assert "FAILED" in msg


# ---------------------------------------------------------------------------
# stop_ap
# ---------------------------------------------------------------------------


class TestStopAp:
    """Tests for wifi.stop_ap() — removes hotspot connection."""

    @patch.object(wifi, "_cancel_ap_timer")
    @patch.object(wifi, "_clear_ap_marker")
    @patch("modules.wifi.subprocess.run")
    def test_stop_ap_success(self, mock_run, mock_marker, mock_timer):
        mock_run.return_value = _mock_run_result(rc=0)
        success, msg = wifi.stop_ap()
        assert success is True
        assert "STOPPED" in msg
        mock_timer.assert_called_once()
        mock_marker.assert_called_once()

    @patch.object(wifi, "_cancel_ap_timer")
    @patch.object(wifi, "_clear_ap_marker")
    @patch("modules.wifi.subprocess.run")
    def test_stop_ap_failure(self, mock_run, mock_marker, mock_timer):
        mock_run.return_value = _mock_run_result(rc=1, stderr="no active connection")
        success, msg = wifi.stop_ap()
        assert success is False
        assert "FAILED" in msg


# ---------------------------------------------------------------------------
# scan_networks
# ---------------------------------------------------------------------------


class TestScanNetworks:
    """Tests for wifi.scan_networks() — parses nmcli output."""

    @patch("modules.wifi.subprocess.run")
    def test_parses_normal_output(self, mock_run):
        mock_run.return_value = _mock_run_result(
            stdout="HomeWiFi:85:WPA2\nCoffeeShop:42:WPA1\nOpenNet:30:"
        )
        networks = wifi.scan_networks()
        assert len(networks) == 3
        assert networks[0]["ssid"] == "HomeWiFi"
        assert networks[0]["signal"] == 85
        assert networks[0]["security"] == "WPA2"
        # Sorted by signal descending
        assert networks[0]["signal"] >= networks[1]["signal"]

    @patch("modules.wifi.subprocess.run")
    def test_deduplicates_ssids(self, mock_run):
        mock_run.return_value = _mock_run_result(
            stdout="MyNet:90:WPA2\nMyNet:80:WPA2\nOther:70:WPA1"
        )
        networks = wifi.scan_networks()
        ssids = [n["ssid"] for n in networks]
        assert ssids.count("MyNet") == 1

    @patch("modules.wifi.subprocess.run")
    def test_handles_escaped_colons(self, mock_run):
        mock_run.return_value = _mock_run_result(
            stdout="My\\:Network:75:WPA2"
        )
        networks = wifi.scan_networks()
        assert len(networks) == 1
        assert networks[0]["ssid"] == "My:Network"

    @patch("modules.wifi.subprocess.run")
    def test_empty_on_failure(self, mock_run):
        mock_run.return_value = _mock_run_result(rc=1, stderr="error")
        networks = wifi.scan_networks()
        assert networks == []

    @patch("modules.wifi.subprocess.run")
    def test_skips_empty_ssids(self, mock_run):
        mock_run.return_value = _mock_run_result(
            stdout=":80:WPA2\nRealNet:70:WPA1"
        )
        networks = wifi.scan_networks()
        assert len(networks) == 1
        assert networks[0]["ssid"] == "RealNet"


# ---------------------------------------------------------------------------
# _ap_timeout_handler — tries known WiFi before restarting AP
# ---------------------------------------------------------------------------


class TestApTimeoutHandler:
    """Tests for _ap_timeout_handler() — connect to known WiFi first."""

    @patch.object(wifi, "start_ap")
    @patch.object(wifi, "is_connected", return_value=False)
    @patch.object(wifi, "stop_ap", return_value=(True, "stopped"))
    @patch.object(wifi, "_has_ap_clients", return_value=False)
    @patch.object(wifi, "is_ap_active", return_value=True)
    @patch("modules.wifi.time.sleep")
    def test_no_known_wifi_restarts_ap(
        self, mock_sleep, mock_active, mock_clients, mock_stop, mock_connected, mock_start
    ):
        """When no known WiFi is available after stopping AP, restart AP."""
        wifi._ap_timeout_handler()
        mock_stop.assert_called_once()
        mock_sleep.assert_called_with(2)
        mock_connected.assert_called_once()
        mock_start.assert_called_once()

    @patch.object(wifi, "start_ap")
    @patch.object(wifi, "is_connected", return_value=True)
    @patch.object(wifi, "stop_ap", return_value=(True, "stopped"))
    @patch.object(wifi, "_has_ap_clients", return_value=False)
    @patch.object(wifi, "is_ap_active", return_value=True)
    @patch("modules.wifi.time.sleep")
    def test_known_wifi_available_stays_connected(
        self, mock_sleep, mock_active, mock_clients, mock_stop, mock_connected, mock_start
    ):
        """When known WiFi connects after stopping AP, don't restart AP."""
        wifi._ap_timeout_handler()
        mock_stop.assert_called_once()
        mock_connected.assert_called_once()
        mock_start.assert_not_called()

    @patch.object(wifi, "_start_ap_timer")
    @patch.object(wifi, "_has_ap_clients", return_value=True)
    @patch.object(wifi, "is_ap_active", return_value=True)
    def test_clients_connected_resets_timer(self, mock_active, mock_clients, mock_timer):
        """When clients are connected, reset timer instead of stopping."""
        wifi._ap_timeout_handler()
        mock_timer.assert_called_once()

    @patch.object(wifi, "stop_ap")
    @patch.object(wifi, "is_ap_active", return_value=False)
    def test_ap_not_active_noop(self, mock_active, mock_stop):
        """When AP is already stopped, do nothing."""
        wifi._ap_timeout_handler()
        mock_stop.assert_not_called()
