import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build_plugin import build
from scripts.check_public_release import check


class ReleaseTests(unittest.TestCase):
    def test_package_is_reproducible_source_only_and_contains_licenses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "qgis_ai_copilot"
            package.mkdir()
            (package / "metadata.txt").write_text("[general]\nversion=1.2.3\n", encoding="utf-8")
            (package / "constants.py").write_text('PLUGIN_VERSION = "1.2.3"\n', encoding="utf-8")
            (package / "__init__.py").write_text("# example\n", encoding="utf-8")
            (package / "private.db").write_bytes(b"not distributed")
            (root / "LICENSE").write_text("test license", encoding="utf-8")
            (root / "THIRD_PARTY_NOTICES.md").write_text("test notices", encoding="utf-8")
            output, digest = build(root)
            _, second_digest = build(root)
            self.assertEqual(digest, second_digest)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), {
                    "qgis_ai_copilot/metadata.txt", "qgis_ai_copilot/constants.py",
                    "qgis_ai_copilot/__init__.py", "qgis_ai_copilot/LICENSE",
                    "qgis_ai_copilot/THIRD_PARTY_NOTICES.md",
                })

    def test_audit_rejects_private_file_types(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "profile.db").write_bytes(b"private")
            count, problems = check(root)
            self.assertEqual(count, 1)
            self.assertEqual(len(problems), 1)

    def test_audit_redacts_findings_but_accepts_synthetic_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "example.py").write_text('fixture = "/' + 'Users/private/example.png"', encoding="utf-8")
            self.assertFalse(check(root)[1])
            sensitive = "ghp_" + "Z" * 36
            (root / "bad.py").write_text(sensitive, encoding="utf-8")
            problems = check(root)[1]
            self.assertEqual(len(problems), 1)
            self.assertNotIn(sensitive, str(problems))


if __name__ == "__main__":
    unittest.main()
