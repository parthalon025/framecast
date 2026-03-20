"""Tests for modules/updater.py — OTA update check, apply, and rollback."""

import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

# Patch config before import so module-level reads use test values
with patch("modules.config.get", return_value="test"):
    from modules import updater


# ---------------------------------------------------------------------------
# validate_tag
# ---------------------------------------------------------------------------

class TestValidateTag:
    def test_valid_tags(self):
        assert updater.validate_tag("v1.0.0") is True
        assert updater.validate_tag("v0.0.1") is True
        assert updater.validate_tag("v12.34.56") is True

    def test_invalid_tags(self):
        assert updater.validate_tag("1.0.0") is False
        assert updater.validate_tag("v1.0") is False
        assert updater.validate_tag("v1.0.0-beta") is False
        assert updater.validate_tag("") is False
        assert updater.validate_tag("latest") is False
        assert updater.validate_tag("v1.0.0; rm -rf /") is False


# ---------------------------------------------------------------------------
# get_current_version
# ---------------------------------------------------------------------------

class TestGetCurrentVersion:
    def test_reads_version_file(self, tmp_path):
        vfile = tmp_path / "VERSION"
        vfile.write_text("2.1.0\n")
        with patch.object(updater, "VERSION_FILE", vfile):
            assert updater.get_current_version() == "2.1.0"

    def test_missing_version_file(self, tmp_path):
        with patch.object(updater, "VERSION_FILE", tmp_path / "MISSING"):
            assert updater.get_current_version() == "0.0.0"


# ---------------------------------------------------------------------------
# _version_newer
# ---------------------------------------------------------------------------

class TestVersionNewer:
    def test_newer(self):
        assert updater._version_newer("2.0.0", "1.0.0") is True
        assert updater._version_newer("1.1.0", "1.0.0") is True
        assert updater._version_newer("1.0.1", "1.0.0") is True

    def test_same(self):
        assert updater._version_newer("1.0.0", "1.0.0") is False

    def test_older(self):
        assert updater._version_newer("1.0.0", "2.0.0") is False

    def test_invalid_fallback(self):
        # Falls back to string comparison
        assert updater._version_newer("b", "a") is True


# ---------------------------------------------------------------------------
# check_for_update
# ---------------------------------------------------------------------------

class TestCheckForUpdate:
    def _mock_api_response(self, tag="v2.0.0", commitish="abc123" * 7):
        data = json.dumps({
            "tag_name": tag,
            "html_url": f"https://github.com/test/test/releases/tag/{tag}",
            "target_commitish": commitish,
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch.object(updater, "get_current_version", return_value="1.0.0")
    @patch("urllib.request.urlopen")
    def test_update_available(self, mock_urlopen, mock_ver):
        mock_urlopen.return_value = self._mock_api_response("v2.0.0")
        result = updater.check_for_update()
        assert result["available"] is True
        assert result["latest"] == "2.0.0"
        assert result["tag_name"] == "v2.0.0"
        assert result["current"] == "1.0.0"

    @patch.object(updater, "get_current_version", return_value="2.0.0")
    @patch("urllib.request.urlopen")
    def test_no_update(self, mock_urlopen, mock_ver):
        mock_urlopen.return_value = self._mock_api_response("v2.0.0")
        result = updater.check_for_update()
        assert result["available"] is False

    @patch.object(updater, "get_current_version", return_value="1.0.0")
    @patch("urllib.request.urlopen")
    def test_api_error(self, mock_urlopen, mock_ver):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("network down")
        result = updater.check_for_update()
        assert result["available"] is False
        assert result["current"] == "1.0.0"

    @patch.object(updater, "get_current_version", return_value="1.0.0")
    @patch("urllib.request.urlopen")
    def test_missing_tag_name(self, mock_urlopen, mock_ver):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"html_url": ""}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = updater.check_for_update()
        assert result["available"] is False


# ---------------------------------------------------------------------------
# apply_update
# ---------------------------------------------------------------------------

class TestApplyUpdate:
    @patch.object(updater, "_git")
    @patch.object(updater, "_atomic_write")
    @patch.object(updater, "get_current_version", return_value="1.0.0")
    @patch.object(updater, "_hmac_sign", return_value="sig123")
    def test_apply_success_no_sha(self, mock_sign, mock_ver, mock_write, mock_git):
        mock_git.return_value = (True, "ok")
        success, msg = updater.apply_update("v2.0.0")
        assert success is True
        assert "v2.0.0" in msg
        # Should have called git fetch and checkout
        calls = [c[0] for c in mock_git.call_args_list]
        assert ("fetch", "--tags") in calls
        assert ("checkout", "v2.0.0") in calls

    @patch.object(updater, "_git")
    @patch.object(updater, "_atomic_write")
    @patch.object(updater, "get_current_version", return_value="1.0.0")
    @patch.object(updater, "_hmac_sign", return_value="sig123")
    def test_apply_sha_verification_pass(self, mock_sign, mock_ver, mock_write, mock_git):
        sha = "a" * 40
        def git_side_effect(*args):
            if args[0] == "rev-parse":
                return (True, sha)
            return (True, "ok")
        mock_git.side_effect = git_side_effect
        success, msg = updater.apply_update("v2.0.0", expected_sha=sha)
        assert success is True

    @patch.object(updater, "_git")
    @patch.object(updater, "_atomic_write")
    @patch.object(updater, "get_current_version", return_value="1.0.0")
    @patch.object(updater, "_hmac_sign", return_value="sig123")
    def test_apply_sha_mismatch_aborts(self, mock_sign, mock_ver, mock_write, mock_git):
        expected = "a" * 40
        actual = "b" * 40
        def git_side_effect(*args):
            if args[0] == "rev-parse":
                return (True, actual)
            return (True, "ok")
        mock_git.side_effect = git_side_effect
        success, msg = updater.apply_update("v2.0.0", expected_sha=expected)
        assert success is False
        assert "mismatch" in msg.lower()

    def test_apply_rejects_bad_tag(self):
        success, msg = updater.apply_update("not-a-tag")
        assert success is False
        assert "Invalid" in msg

    @patch.object(updater, "_git")
    @patch.object(updater, "_atomic_write")
    @patch.object(updater, "get_current_version", return_value="1.0.0")
    @patch.object(updater, "_hmac_sign", return_value="sig123")
    def test_apply_fetch_failure(self, mock_sign, mock_ver, mock_write, mock_git):
        mock_git.return_value = (False, "network error")
        success, msg = updater.apply_update("v2.0.0")
        assert success is False
        assert "fetch" in msg.lower()

    @patch.object(updater, "_git")
    @patch.object(updater, "_atomic_write")
    @patch.object(updater, "get_current_version", return_value="1.0.0")
    @patch.object(updater, "_hmac_sign", return_value="sig123")
    def test_apply_checkout_failure(self, mock_sign, mock_ver, mock_write, mock_git):
        def git_side_effect(*args):
            if args[0] == "checkout":
                return (False, "checkout error")
            return (True, "ok")
        mock_git.side_effect = git_side_effect
        success, msg = updater.apply_update("v2.0.0")
        assert success is False
        assert "checkout" in msg.lower()


# ---------------------------------------------------------------------------
# _verify_tag_sha
# ---------------------------------------------------------------------------

class TestVerifyTagSha:
    @patch.object(updater, "_git")
    def test_sha_match(self, mock_git):
        sha = "a" * 40
        mock_git.return_value = (True, sha)
        ok, msg = updater._verify_tag_sha("v1.0.0", sha)
        assert ok is True

    @patch.object(updater, "_git")
    def test_sha_mismatch(self, mock_git):
        mock_git.return_value = (True, "b" * 40)
        ok, msg = updater._verify_tag_sha("v1.0.0", "a" * 40)
        assert ok is False
        assert "mismatch" in msg.lower()

    def test_empty_sha_skips(self):
        ok, msg = updater._verify_tag_sha("v1.0.0", "")
        assert ok is True
        assert "skipped" in msg.lower()

    @patch.object(updater, "_git")
    def test_git_failure(self, mock_git):
        mock_git.return_value = (False, "error")
        ok, msg = updater._verify_tag_sha("v1.0.0", "a" * 40)
        assert ok is False


# ---------------------------------------------------------------------------
# _atomic_write
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_writes_file(self, tmp_path):
        target = tmp_path / "test.txt"
        updater._atomic_write(target, "hello")
        assert target.read_text() == "hello"

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "sub" / "dir" / "file.txt"
        updater._atomic_write(target, "content")
        assert target.read_text() == "content"

    def test_cleans_up_on_failure(self, tmp_path):
        target = tmp_path / "test.txt"
        with patch("builtins.open", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                updater._atomic_write(target, "content")
