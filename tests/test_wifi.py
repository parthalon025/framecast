"""Tests for modules/wifi.py — AP marker, timeout SSE events, watchdog."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Patch config before import
with patch("modules.config.get", return_value="/home/pi/media"):
    from modules import wifi


# ---------------------------------------------------------------------------
# AP marker location
# ---------------------------------------------------------------------------

class TestApMarkerPath:
    def test_marker_in_var_lib(self):
        assert wifi._AP_MARKER_FILE == Path("/var/lib/framecast/ap_started")

    def test_marker_not_in_home(self):
        assert ".ap_started" not in str(wifi._AP_MARKER_FILE)


# ---------------------------------------------------------------------------
# AP timeout SSE events
# ---------------------------------------------------------------------------

class TestApTimeoutSSE:
    @patch.object(wifi, "_notify_sse")
    @patch.object(wifi, "start_ap", return_value=(True, "started"))
    @patch.object(wifi, "is_connected", return_value=False)
    @patch.object(wifi, "stop_ap", return_value=(True, "stopped"))
    @patch.object(wifi, "_has_ap_clients", return_value=False)
    @patch.object(wifi, "is_ap_active", return_value=True)
    @patch.object(wifi, "get_ap_ssid", return_value="FrameCast-TEST")
    @patch("time.sleep")
    def test_timeout_no_wifi_emits_ap_restarted(self, mock_sleep, mock_ssid,
                                                 mock_active, mock_clients,
                                                 mock_stop, mock_conn,
                                                 mock_start, mock_sse):
        wifi._ap_timeout_handler()
        mock_sse.assert_called_once_with("wifi:ap_restarted",
                                         {"ap_ssid": "FrameCast-TEST"})

    @patch.object(wifi, "_notify_sse")
    @patch.object(wifi, "get_current_ssid", return_value="HomeWiFi")
    @patch.object(wifi, "is_connected", return_value=True)
    @patch.object(wifi, "stop_ap", return_value=(True, "stopped"))
    @patch.object(wifi, "_has_ap_clients", return_value=False)
    @patch.object(wifi, "is_ap_active", return_value=True)
    @patch("time.sleep")
    def test_timeout_known_wifi_emits_connected(self, mock_sleep, mock_active,
                                                 mock_clients, mock_stop,
                                                 mock_conn, mock_ssid,
                                                 mock_sse):
        wifi._ap_timeout_handler()
        mock_sse.assert_called_once_with("wifi:connected",
                                         {"ssid": "HomeWiFi"})

    @patch.object(wifi, "_notify_sse")
    @patch.object(wifi, "_start_ap_timer")
    @patch.object(wifi, "_has_ap_clients", return_value=True)
    @patch.object(wifi, "is_ap_active", return_value=True)
    def test_timeout_with_clients_resets_timer(self, mock_active, mock_clients,
                                               mock_timer, mock_sse):
        wifi._ap_timeout_handler()
        mock_timer.assert_called_once()
        mock_sse.assert_not_called()


# ---------------------------------------------------------------------------
# WiFi watchdog
# ---------------------------------------------------------------------------

class TestWifiWatchdog:
    @patch.object(wifi, "start_ap", return_value=(True, "started"))
    @patch.object(wifi, "_notify_sse")
    @patch.object(wifi, "is_ap_active", return_value=False)
    @patch.object(wifi, "is_connected", return_value=False)
    @patch("time.sleep")
    def test_watchdog_starts_ap_after_threshold(self, mock_sleep, mock_conn,
                                                mock_ap, mock_sse, mock_start):
        wifi._disconnect_since = None
        call_count = [0]

        def sleep_side_effect(duration):
            call_count[0] += 1
            if call_count[0] == 1:
                return
            elif call_count[0] == 2:
                wifi._disconnect_since = time.time() - wifi._WATCHDOG_DISCONNECT_THRESHOLD - 1
                return
            else:
                raise StopIteration

        mock_sleep.side_effect = sleep_side_effect

        with pytest.raises(StopIteration):
            wifi._wifi_watchdog_loop()

        mock_sse.assert_called_with("wifi:disconnected",
                                    {"reason": "home_wifi_lost"})
        mock_start.assert_called_once()

    @patch.object(wifi, "start_ap")
    @patch.object(wifi, "is_ap_active", return_value=False)
    @patch.object(wifi, "is_connected", return_value=True)
    @patch("time.sleep")
    def test_watchdog_resets_on_reconnect(self, mock_sleep, mock_conn,
                                          mock_ap, mock_start):
        wifi._disconnect_since = time.time() - 100
        call_count = [0]

        def sleep_side_effect(duration):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise StopIteration

        mock_sleep.side_effect = sleep_side_effect

        with pytest.raises(StopIteration):
            wifi._wifi_watchdog_loop()

        assert wifi._disconnect_since is None
        mock_start.assert_not_called()

    @patch.object(wifi, "start_ap")
    @patch.object(wifi, "is_ap_active", return_value=True)
    @patch.object(wifi, "is_connected", return_value=False)
    @patch("time.sleep")
    def test_watchdog_skips_if_ap_active(self, mock_sleep, mock_conn,
                                         mock_ap, mock_start):
        call_count = [0]

        def sleep_side_effect(duration):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise StopIteration

        mock_sleep.side_effect = sleep_side_effect

        with pytest.raises(StopIteration):
            wifi._wifi_watchdog_loop()

        mock_start.assert_not_called()


# ---------------------------------------------------------------------------
# _notify_sse helper
# ---------------------------------------------------------------------------

class TestNotifySSE:
    @patch("sse.notify")
    def test_notify_calls_sse(self, mock_notify):
        wifi._notify_sse("wifi:test", {"key": "value"})
        mock_notify.assert_called_once_with("wifi:test", {"key": "value"})

    @patch("sse.notify", side_effect=ImportError("no sse"))
    def test_notify_handles_import_error(self, mock_notify):
        wifi._notify_sse("wifi:test", {})  # Should not raise
