"""Real ZIP and filesystem checks for the pinned Pages media installer."""

import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from scripts import install_course_media as media


class CourseMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="academy-media-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repository"
        self.destination = self.root / "www" / "learn" / "media"
        self.destination.mkdir(parents=True)
        (self.destination / "old.txt").write_text(
            "previous complete release", encoding="utf-8"
        )
        self.config = Path(self.temp.name) / "release.json"
        self.archive = Path(self.temp.name) / "release.zip"
        self.root_patch = patch.object(media, "REPO_ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def bundle(self, files=None, *, manifest=None, extras=None):
        files = (
            files
            if files is not None
            else {"C3/audio.mp3": b"example audio", "C3/captions.vtt": b"WEBVTT\n\n"}
        )
        if manifest is None:
            manifest = {
                "schema": 1,
                "files": [
                    {
                        "path": name,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data),
                    }
                    for name, data in files.items()
                ],
            }
        with ZipFile(self.archive, "w", compression=ZIP_DEFLATED) as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest))
            for name, data in files.items():
                bundle.writestr(name, data)
            for name, data in (extras or {}).items():
                bundle.writestr(name, data)
        self.pin()
        return files

    def pin(self):
        self.config.write_text(
            json.dumps(
                {
                    "url": "https://example.com/pinned/release.zip",
                    "sha256": hashlib.sha256(self.archive.read_bytes()).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

    def install(self, **kwargs):
        return media.install_media(config=self.config, archive=self.archive, **kwargs)

    def assert_previous_intact(self):
        self.assertEqual(
            (self.destination / "old.txt").read_text(encoding="utf-8"),
            "previous complete release",
        )
        self.assertEqual(
            list(self.destination.iterdir()), [self.destination / "old.txt"]
        )
        self.assertFalse(list(self.destination.parent.glob(".media-install-*")))

    def test_verified_bundle_replaces_complete_previous_release(self):
        files = self.bundle()
        self.assertEqual(self.install(), 2)
        self.assertFalse((self.destination / "old.txt").exists())
        for name, data in files.items():
            self.assertEqual((self.destination / name).read_bytes(), data)
        self.assertTrue((self.destination / "manifest.json").is_file())
        self.assertFalse(list(self.destination.parent.glob(".media-install-*")))

    def test_archive_checksum_failure_leaves_previous_release(self):
        self.bundle()
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config["sha256"] = "0" * 64
        self.config.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(
            media.MediaInstallError, "Archive SHA-256 mismatch"
        ):
            self.install()
        self.assert_previous_intact()

    def test_invalid_archive_pin_prevents_zip_inspection(self):
        self.bundle()
        self.archive.write_bytes(b"not a ZIP, and not the pinned bytes")
        with patch.object(
            media, "ZipFile", side_effect=AssertionError("Unverified ZIP was inspected")
        ):
            with self.assertRaisesRegex(
                media.MediaInstallError, "Archive SHA-256 mismatch"
            ):
                self.install()
        self.assert_previous_intact()

    def test_traversal_absolute_backslash_and_drive_paths_are_rejected(self):
        for unsafe in (
            "../escape.mp3",
            "/absolute.mp3",
            "C:/drive.mp3",
            "folder\\escape.mp3",
            "a/../../escape.mp3",
            "a//alias.mp3",
            "a/./alias.mp3",
            "CON.mp3",
            "stream.mp3:payload",
        ):
            with self.subTest(unsafe=unsafe):
                self.bundle(extras={unsafe: b"unsafe"})
                with self.assertRaises(media.MediaInstallError):
                    self.install()
                self.assert_previous_intact()
                self.assertFalse((self.root / "escape.mp3").exists())

    def test_manifest_hash_binds_file_contents(self):
        self.bundle(
            files={"audio.mp3": b"changed audio"},
            manifest={
                "schema": 1,
                "files": [
                    {
                        "path": "audio.mp3",
                        "sha256": hashlib.sha256(b"original data").hexdigest(),
                        "bytes": len(b"changed audio"),
                    }
                ],
            },
        )
        with self.assertRaisesRegex(media.MediaInstallError, "Manifest SHA-256"):
            self.install()
        self.assert_previous_intact()

    def test_manifest_size_binds_file_length(self):
        self.bundle(
            manifest={
                "schema": 1,
                "files": [
                    {"path": "C3/audio.mp3", "sha256": "a" * 64, "bytes": 999},
                    {
                        "path": "C3/captions.vtt",
                        "sha256": hashlib.sha256(b"WEBVTT\n\n").hexdigest(),
                        "bytes": 8,
                    },
                ],
            }
        )
        with self.assertRaisesRegex(media.MediaInstallError, "byte count"):
            self.install()
        self.assert_previous_intact()

    def test_manifest_rejects_missing_and_undeclared_files(self):
        for manifest in (
            {
                "schema": 1,
                "files": [{"path": "missing.mp3", "sha256": "a" * 64, "bytes": 0}],
            },
            {
                "schema": 1,
                "files": [{"path": "C3/audio.mp3", "sha256": "a" * 64, "bytes": 13}],
            },
        ):
            with self.subTest(manifest=manifest):
                self.bundle(manifest=manifest)
                with self.assertRaisesRegex(media.MediaInstallError, "exactly match"):
                    self.install()
                self.assert_previous_intact()

    def test_root_manifest_is_required(self):
        with ZipFile(self.archive, "w") as bundle:
            bundle.writestr("audio.mp3", b"audio")
        self.pin()
        with self.assertRaisesRegex(media.MediaInstallError, "requires root manifest"):
            self.install()
        self.assert_previous_intact()

    def test_symlink_member_is_rejected(self):
        self.bundle()
        link = ZipInfo("link.mp3")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with ZipFile(self.archive, "a") as bundle:
            bundle.writestr(link, "../../outside")
        self.pin()
        with self.assertRaisesRegex(media.MediaInstallError, "links and special"):
            self.install()
        self.assert_previous_intact()

    def test_unsafe_extensions_are_rejected(self):
        self.bundle(extras={"run.html": b"<script>bad()</script>"})
        with self.assertRaisesRegex(
            media.MediaInstallError, "Unsupported media extension"
        ):
            self.install()
        self.assert_previous_intact()

    def test_case_alias_members_are_rejected_portably(self):
        self.bundle(extras={"C3/Audio.mp3": b"case alias"})
        with self.assertRaisesRegex(media.MediaInstallError, "Duplicate ZIP path"):
            self.install()
        self.assert_previous_intact()

    def test_expanded_size_cap_is_enforced_before_replacement(self):
        self.bundle()
        with patch.object(media, "MAX_EXPANDED_BYTES", 5):
            with self.assertRaisesRegex(media.MediaInstallError, "expanded size"):
                self.install()
        self.assert_previous_intact()

    def test_outside_destination_cannot_be_replaced(self):
        self.bundle()
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(media.MediaInstallError, "Destination must"):
            self.install(destination=outside)
        self.assertEqual((outside / "keep.txt").read_text(encoding="utf-8"), "keep")
        self.assert_previous_intact()

    def test_destination_link_cannot_redirect_replacement(self):
        self.bundle()
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        link = self.root / "redirect"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Host does not permit creating test directory symlinks")
        with self.assertRaisesRegex(media.MediaInstallError, "Destination must"):
            self.install(destination=link)
        self.assertTrue(link.is_symlink())
        self.assert_previous_intact()

    def test_failed_final_move_restores_old_complete_release(self):
        self.bundle()
        real_replace = os.replace

        def fail_payload(source, destination):
            if Path(source).name == "payload":
                raise OSError("simulated replacement failure")
            return real_replace(source, destination)

        with patch.object(media.os, "replace", side_effect=fail_payload):
            with self.assertRaisesRegex(
                media.MediaInstallError, "previous media was restored"
            ):
                self.install()
        self.assert_previous_intact()

    def test_invalid_config_url_rejected_even_for_local_archive(self):
        self.bundle()
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config["url"] = "http://example.com/unpinned.zip"
        self.config.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(media.MediaInstallError, "must be HTTPS"):
            self.install()
        self.assert_previous_intact()

    def test_cli_local_archive_succeeds_and_reports_verified_count(self):
        self.bundle()
        output = io.StringIO()
        with redirect_stdout(output):
            code = media.main(
                [
                    "--config",
                    str(self.config),
                    "--destination",
                    str(self.destination),
                    "--archive",
                    str(self.archive),
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("verified 2 course media files", output.getvalue())
        self.assertTrue((self.destination / "manifest.json").is_file())

    def test_cli_failure_has_nonzero_exit_and_keeps_previous_bundle(self):
        self.bundle()
        self.archive.write_bytes(b"tampered archive")
        output = io.StringIO()
        with redirect_stderr(output):
            code = media.main(
                ["--config", str(self.config), "--archive", str(self.archive)]
            )
        self.assertEqual(code, 1)
        self.assertIn("SHA-256 mismatch", output.getvalue())
        self.assert_previous_intact()


if __name__ == "__main__":
    unittest.main()
