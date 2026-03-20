"""Tests for HDMI-CEC TV control module (app/modules/cec.py).

Verifies correct cec-ctl command construction, timeout handling,
graceful degradation on missing binary, and init state query.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from modules import cec


# ---------------------------------------------------------------------------
# _cec_cmd — core command runner
# ---------------------------------------------------------------------------


class TestCecCmd:
    """Tests for the low-level _cec_cmd helper."""

    @patch("modules.cec.subprocess.run")
    def test_success_returns_stdout(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = cec._cec_cmd(["--playback", "-t0", "--standby"])

        assert result == "ok\n"
        mock_run.assert_called_once_with(
            ["cec-ctl", "--playback", "-t0", "--standby"],
            capture_output=True,
            text=True,
            timeout=5,
        )

    @patch("modules.cec.subprocess.run")
    def test_nonzero_returncode_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = cec._cec_cmd(["--playback", "-t0", "--standby"])

        assert result is None

    @patch("modules.cec.subprocess.run")
    def test_timeout_returns_none(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="cec-ctl", timeout=5)
        result = cec._cec_cmd(["--playback", "-t0", "--standby"])

        assert result is None

    @patch("modules.cec.subprocess.run")
    def test_file_not_found_returns_none(self, mock_run):
        mock_run.side_effect = FileNotFoundError("cec-ctl")
        result = cec._cec_cmd(["--playback", "-t0", "--standby"])

        assert result is None

    @patch("modules.cec.subprocess.run")
    def test_generic_exception_returns_none(self, mock_run):
        mock_run.side_effect = OSError("permission denied")
        result = cec._cec_cmd(["--playback", "-t0", "--standby"])

        assert result is None

    @patch("modules.cec.subprocess.run")
    def test_custom_timeout_passed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        cec._cec_cmd(["--standby"], timeout=10)

        mock_run.assert_called_once_with(
            ["cec-ctl", "--standby"],
            capture_output=True,
            text=True,
            timeout=10,
        )


# ---------------------------------------------------------------------------
# tv_power_on
# ---------------------------------------------------------------------------


class TestTvPowerOn:
    @patch("modules.cec._cec_cmd")
    def test_success(self, mock_cmd):
        mock_cmd.return_value = "Transmit OK\n"
        assert cec.tv_power_on() is True
        mock_cmd.assert_called_once_with(
            ["--playback", "-t0", "--image-view-on"]
        )

    @patch("modules.cec._cec_cmd")
    def test_failure(self, mock_cmd):
        mock_cmd.return_value = None
        assert cec.tv_power_on() is False


# ---------------------------------------------------------------------------
# tv_standby
# ---------------------------------------------------------------------------


class TestTvStandby:
    @patch("modules.cec._cec_cmd")
    def test_success(self, mock_cmd):
        mock_cmd.return_value = "Transmit OK\n"
        assert cec.tv_standby() is True
        mock_cmd.assert_called_once_with(["--playback", "-t0", "--standby"])

    @patch("modules.cec._cec_cmd")
    def test_failure(self, mock_cmd):
        mock_cmd.return_value = None
        assert cec.tv_standby() is False


# ---------------------------------------------------------------------------
# tv_status
# ---------------------------------------------------------------------------


class TestTvStatus:
    @patch("modules.cec._cec_cmd")
    def test_on(self, mock_cmd):
        mock_cmd.return_value = "pwr-status: on\n"
        assert cec.tv_status() == "on"

    @patch("modules.cec._cec_cmd")
    def test_on_case_insensitive(self, mock_cmd):
        mock_cmd.return_value = "PWR-STATUS: ON\n"
        assert cec.tv_status() == "on"

    @patch("modules.cec._cec_cmd")
    def test_standby(self, mock_cmd):
        mock_cmd.return_value = "pwr-status: standby\n"
        assert cec.tv_status() == "standby"

    @patch("modules.cec._cec_cmd")
    def test_standby_extra_whitespace(self, mock_cmd):
        mock_cmd.return_value = "pwr-status:  standby\n"
        assert cec.tv_status() == "standby"

    @patch("modules.cec._cec_cmd")
    def test_unrecognized_format_returns_unknown(self, mock_cmd):
        mock_cmd.return_value = "power status: standby\n"
        assert cec.tv_status() == "unknown"

    @patch("modules.cec._cec_cmd")
    def test_unknown_output(self, mock_cmd):
        mock_cmd.return_value = "some unrecognized output\n"
        assert cec.tv_status() == "unknown"

    @patch("modules.cec._cec_cmd")
    def test_command_failure_returns_unknown(self, mock_cmd):
        mock_cmd.return_value = None
        assert cec.tv_status() == "unknown"


# ---------------------------------------------------------------------------
# set_active_source
# ---------------------------------------------------------------------------


class TestSetActiveSource:
    @patch("modules.cec._cec_cmd")
    def test_success(self, mock_cmd):
        mock_cmd.return_value = "Transmit OK\n"
        assert cec.set_active_source() is True
        mock_cmd.assert_called_once_with(
            ["--playback", "-t0", "--active-source", "phys-addr=1.0.0.0"]
        )

    @patch("modules.cec._cec_cmd")
    def test_failure(self, mock_cmd):
        mock_cmd.return_value = None
        assert cec.set_active_source() is False


# ---------------------------------------------------------------------------
# init_cec — cold-start state query (Lesson #7)
# ---------------------------------------------------------------------------


class TestInitCec:
    @patch("modules.cec.tv_status")
    def test_returns_detected_status(self, mock_status):
        mock_status.return_value = "on"
        assert cec.init_cec() == "on"

    @patch("modules.cec.tv_status")
    def test_unknown_status_still_returns(self, mock_status):
        mock_status.return_value = "unknown"
        assert cec.init_cec() == "unknown"

    @patch("modules.cec.tv_status")
    def test_standby_status(self, mock_status):
        mock_status.return_value = "standby"
        assert cec.init_cec() == "standby"
