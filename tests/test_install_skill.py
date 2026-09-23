from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill" / "verifying-sales-leads" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import install_skill  # noqa: E402


class InstallSkillTests(unittest.TestCase):
    def test_codex_copy_can_be_safely_refreshed(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "codex" / install_skill.SKILL_NAME
            install_skill.install_copy(target)
            self.assertTrue((target / "SKILL.md").is_file())
            self.assertEqual(
                (target / install_skill.MANAGED_MARKER).read_text(encoding="utf-8").strip(),
                str(install_skill.SKILL_DIR),
            )
            install_skill.install_copy(target)
            self.assertFalse(target.is_symlink())

    def test_unmanaged_codex_folder_is_not_replaced(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "codex" / install_skill.SKILL_NAME
            target.mkdir(parents=True)
            (target / "personal.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                install_skill.install_copy(target)
            self.assertEqual((target / "personal.txt").read_text(encoding="utf-8"), "keep")

    def test_claude_link_points_to_canonical_skill(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "claude" / install_skill.SKILL_NAME
            install_skill.install_link(target)
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), install_skill.SKILL_DIR)


if __name__ == "__main__":
    unittest.main()
