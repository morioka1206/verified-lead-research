from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verifying-sales-leads" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import install_skill  # noqa: E402


class InstallSkillTests(unittest.TestCase):
    def make_source(self, root, release, content):
        source = root / release / 'skills' / install_skill.SKILL_NAME
        source.mkdir(parents=True)
        (source / 'SKILL.md').write_text(content, encoding='utf-8')
        return source.resolve()

    def test_explicit_previous_source_migrates_and_keeps_a_backup(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            old = self.make_source(root, 'old release', 'old skill')
            new = self.make_source(root, 'new release', 'new skill')
            target = root / 'codex' / 'skills' / install_skill.SKILL_NAME
            with patch.object(install_skill, 'SKILL_DIR', old):
                install_skill.install_copy(target)
            (target / 'personal.txt').write_text('keep my notes')
            with patch.object(install_skill, 'SKILL_DIR', new):
                with self.assertRaises(FileExistsError):
                    install_skill.install_copy(target)
                install_skill.install_copy(target, previous_source=old)
            self.assertEqual((target / 'SKILL.md').read_text(), 'new skill')
            self.assertEqual((target / install_skill.MANAGED_MARKER).read_text().strip(), str(new))
            backups = list((root / 'codex' / 'skill-backups').glob('*/verifying-sales-leads'))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / 'personal.txt').read_text(), 'keep my notes')
            self.assertEqual((backups[0] / 'SKILL.md').read_text(), 'old skill')
            self.assertEqual((old / 'SKILL.md').read_text(), 'old skill')

    def test_wrong_previous_source_and_unmanaged_paths_are_not_replaced(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            old = self.make_source(root, 'old', 'old skill')
            new = self.make_source(root, 'new', 'new skill')
            target = root / 'skills' / install_skill.SKILL_NAME
            with patch.object(install_skill, 'SKILL_DIR', old):
                install_skill.install_copy(target)
            with patch.object(install_skill, 'SKILL_DIR', new):
                with self.assertRaises(FileExistsError):
                    install_skill.install_copy(target, previous_source=root / 'wrong')
                (target / install_skill.MANAGED_MARKER).unlink()
                with self.assertRaises(FileExistsError):
                    install_skill.install_copy(target, previous_source=old)
            self.assertEqual((target / 'SKILL.md').read_text(), 'old skill')

    def test_failed_install_after_backup_restores_previous_copy(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.make_source(root, 'release', 'old skill')
            target = root / 'codex' / 'skills' / install_skill.SKILL_NAME
            with patch.object(install_skill, 'SKILL_DIR', source):
                install_skill.install_copy(target)
                (source / 'SKILL.md').write_text('new skill')
                real_replace = Path.replace

                def fail_staging_replace(path, destination):
                    if path.name.startswith('.' + install_skill.SKILL_NAME + '-') and destination == target:
                        raise OSError('simulated installation failure')
                    return real_replace(path, destination)

                with patch.object(Path, 'replace', fail_staging_replace):
                    with self.assertRaisesRegex(OSError, 'simulated installation failure'):
                        install_skill.install_copy(target)
            self.assertEqual((target / 'SKILL.md').read_text(), 'old skill')
            self.assertTrue((target / install_skill.MANAGED_MARKER).is_file())

    def test_show_source_reports_old_zip_without_changing_the_installation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            old = self.make_source(root, 'old release', 'old skill')
            new = self.make_source(root, 'new release', 'new skill')
            target = root / '.codex' / 'skills' / install_skill.SKILL_NAME
            with patch.object(install_skill, 'SKILL_DIR', old):
                install_skill.install_copy(target)
            output = StringIO()
            with patch.object(install_skill, 'SKILL_DIR', new), \
                    patch.object(install_skill.Path, 'home', return_value=root), \
                    patch.object(install_skill, 'os', SimpleNamespace(environ={})), \
                    patch.object(sys, 'argv', ['install_skill.py', '--codex-only', '--show-source']), \
                    redirect_stdout(output):
                self.assertEqual(install_skill.main(), 0)
            self.assertEqual(output.getvalue().strip(), str(old))
            self.assertEqual((target / 'SKILL.md').read_text(), 'old skill')

    def test_cli_rejects_migration_without_codex_only_before_installing(self):
        with patch.object(sys, 'argv', ['install_skill.py', '--previous-source', '/old/skills/verifying-sales-leads']), redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as result:
                install_skill.main()
        self.assertEqual(result.exception.code, 2)

    def test_cli_migration_updates_only_codex_and_preserves_old_source(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            old = self.make_source(root, 'old release', 'old skill')
            new = self.make_source(root, 'new release', 'new skill')
            target = root / '.codex' / 'skills' / install_skill.SKILL_NAME
            with patch.object(install_skill, 'SKILL_DIR', old):
                install_skill.install_copy(target)
            with patch.object(install_skill, 'SKILL_DIR', new), \
                    patch.object(install_skill.Path, 'home', return_value=root), \
                    patch.object(install_skill, 'os', SimpleNamespace(environ={})), \
                    patch.object(sys, 'argv', ['install_skill.py', '--codex-only', '--previous-source', str(old)]):
                self.assertEqual(install_skill.main(), 0)
            self.assertEqual((target / 'SKILL.md').read_text(), 'new skill')
            self.assertEqual((old / 'SKILL.md').read_text(), 'old skill')
            self.assertFalse((root / '.claude').exists())

    def test_relative_previous_source_is_rejected_before_making_target(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'skills' / install_skill.SKILL_NAME
            with self.assertRaises(ValueError):
                install_skill.install_copy(target, previous_source=Path('old/skills/verifying-sales-leads'))
            self.assertFalse(target.parent.exists())

    def test_copy_failure_keeps_a_current_source_link_intact(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.make_source(root, 'release', 'old skill')
            target = root / 'skills' / install_skill.SKILL_NAME
            target.parent.mkdir()
            target.symlink_to(source, target_is_directory=True)
            with patch.object(install_skill, 'SKILL_DIR', source), \
                    patch.object(install_skill.shutil, 'copytree', side_effect=OSError('copy failed')):
                with self.assertRaisesRegex(OSError, 'copy failed'):
                    install_skill.install_copy(target)
            self.assertTrue(target.is_symlink())
            self.assertEqual((target / 'SKILL.md').read_text(), 'old skill')

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

    def test_legacy_managed_codex_copy_can_be_migrated(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "codex" / install_skill.SKILL_NAME
            target.mkdir(parents=True)
            legacy = install_skill.SKILL_DIR.parents[1] / "skill" / install_skill.SKILL_NAME
            (target / install_skill.MANAGED_MARKER).write_text(str(legacy), encoding="utf-8")
            install_skill.install_copy(target)
            self.assertEqual(
                (target / install_skill.MANAGED_MARKER).read_text(encoding="utf-8").strip(),
                str(install_skill.SKILL_DIR),
            )

    def test_claude_link_points_to_canonical_skill(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "claude" / install_skill.SKILL_NAME
            install_skill.install_link(target)
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), install_skill.SKILL_DIR)

    def test_legacy_claude_link_is_migrated(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "skills" / install_skill.SKILL_NAME
            canonical.mkdir(parents=True)
            legacy = root / "skill" / install_skill.SKILL_NAME
            target = root / "claude" / install_skill.SKILL_NAME
            target.parent.mkdir(parents=True)
            target.symlink_to(legacy, target_is_directory=True)
            with patch.object(install_skill, "SKILL_DIR", canonical):
                install_skill.install_link(target)
            self.assertEqual(target.resolve(), canonical.resolve())


if __name__ == "__main__":
    unittest.main()
