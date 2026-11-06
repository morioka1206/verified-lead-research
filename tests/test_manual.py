"""Public manual integrity and publication boundary checks (no prose snapshots)."""
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Document(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.nodes = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.doc = Document((ROOT / 'GUIDE.html').read_text(encoding='utf-8'))

    def test_links_and_accessible_controls_have_unique_targets(self):
        ids = [a['id'] for _, a in self.doc.nodes if 'id' in a]
        self.assertEqual(len(ids), len(set(ids)), 'Duplicate HTML ids')
        for tag, attrs in self.doc.nodes:
            href = attrs.get('href', '')
            if href.startswith('#'):
                self.assertIn(href[1:], ids, href)
            if attrs.get('role') == 'tab':
                self.assertIn(attrs['aria-controls'], ids)
                self.assertIn(attrs['id'], ids)

    def test_instructions_remain_available_without_javascript(self):
        panels = [a for _, a in self.doc.nodes if a.get('role') == 'tabpanel']
        self.assertGreaterEqual(len(panels), 2)
        self.assertFalse(any('hidden' in a for a in panels),
                         'OS instructions must not depend on JavaScript to become visible')

    def test_public_links_never_expose_local_files(self):
        for _, attrs in self.doc.nodes:
            for name in ('href', 'src'):
                url = attrs.get(name, '')
                self.assertFalse(url.startswith(('file:', '/Users/', 'http://localhost')), url)


class PublicationTests(unittest.TestCase):
    def builder(self):
        path = ROOT / 'scripts/build_public_manual.py'
        self.assertTrue(path.is_file(), 'Public manual builder not implemented')
        spec = importlib.util.spec_from_file_location('public_manual', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.build

    def test_only_manual_is_published_with_identical_bytes(self):
        build = self.builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'GUIDE.html'
            source.write_bytes('<!doctype html><p>日本語の説明</p>'.encode())
            (root / '.env').write_text('PRIVATE_SECRET')
            (root / 'runs').mkdir()
            (root / 'runs/audit.json').write_text('PRIVATE_LEADS')
            (root / 'private-link').symlink_to(root / '.env')
            target = root / 'public'
            result = build(source, target)
            self.assertEqual(result, target / 'index.html')
            self.assertEqual(result.read_bytes(), source.read_bytes())
            self.assertEqual([p.name for p in target.iterdir()], ['index.html'])

    def test_existing_directory_is_not_overwritten_or_published(self):
        build = self.builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'GUIDE.html'
            source.write_text('manual')
            target = root / 'public'
            target.mkdir()
            secret = target / 'private.json'
            secret.write_text('keep')
            with self.assertRaises(FileExistsError):
                build(source, target)
            self.assertEqual(secret.read_text(), 'keep')

    def test_symlink_source_is_rejected_without_creating_output(self):
        build = self.builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / 'private.json'
            secret.write_text('private')
            source = root / 'GUIDE.html'
            source.symlink_to(secret)
            with self.assertRaises(ValueError):
                build(source, root / 'public')
            self.assertFalse((root / 'public').exists())

    def test_destination_symlink_is_rejected_without_writing(self):
        build = self.builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'GUIDE.html'
            source.write_text('manual')
            private = root / 'private'
            private.mkdir()
            target = root / 'public'
            target.symlink_to(private, target_is_directory=True)
            with self.assertRaises(FileExistsError):
                build(source, target)
            self.assertEqual(list(private.iterdir()), [])

    def test_cli_does_not_accept_arbitrary_source_file(self):
        self.builder()
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/build_public_manual.py'),
                                 '--source', '/private/file'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
