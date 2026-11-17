"""Build the in-app update package for a release (standard library only).

  python3 tools/build_update.py <tree> <out dir> [--notes FILE] [--repo OWNER/NAME] [--min-version V]
                                [--base-url URL]
      -> <out>/ClashRektBot-<version>-update.zip        the app's files + app_manifest.json
         <out>/ClashRektBot-<version>-update.zip.sha256
         <out>/latest.json                               what the app reads to find the update

  python3 tools/build_update.py --manifest-only <tree>
      -> <tree>/app_manifest.json   (put it in every installer's files: updates use it to tell the
                                     files the release shipped from files the user changed)

The version is the tree's VERSION file. Attach the zip, then latest.json, to the GitHub release
v<version> (the "Build installers" workflow does this for every published release).
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_engine():
    path = HERE.parent / 'source' / 'updates' / 'engine.py'
    spec = importlib.util.spec_from_file_location('crb_update_engine', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(tree, out, notes='', repo=None, min_version='2.1.0', base_url=None):
    engine = load_engine()
    tree, out = Path(tree).resolve(), Path(out).resolve()
    version = engine.read_version(tree)
    if not version or engine.parse_version(version)[:3] == (0, 0, 0):
        raise SystemExit(f'{tree}/VERSION is missing or empty')
    repo = repo or engine.REPO
    files = engine.collect_files(tree)
    if 'VERSION' not in files or 'runtime/run_bot.py' not in files:
        raise SystemExit('the tree does not look like Clash Rekt Bot (VERSION / runtime/run_bot.py missing)')
    manifest = engine.build_manifest(tree, version, files)
    out.mkdir(parents=True, exist_ok=True)
    name = engine.PACKAGE_NAME.format(version=version)
    package = out / name
    stamp = (2020, 1, 1, 0, 0, 0)                       # same input -> same zip
    with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in files:
            info = zipfile.ZipInfo(rel, stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if manifest['files'][rel].get('x') else 0o100644) << 16
            z.writestr(info, (tree / rel).read_bytes())
        info = zipfile.ZipInfo(engine.MANIFEST, stamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        z.writestr(info, json.dumps(manifest, indent=1, sort_keys=True))
    engine.verify_package(package)                       # never publish a package the app would refuse
    sha = hashlib.sha256(package.read_bytes()).hexdigest()
    (out / (name + '.sha256')).write_text(f'{sha}  {name}\n', encoding='utf-8')
    base = (base_url or f'https://github.com/{repo}/releases/download/v{version}').rstrip('/')
    latest = {
        'schema': 1,
        'name': 'Clash Rekt Bot',
        'version': version,
        'tag': f'v{version}',
        'released': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'page': f'https://github.com/{repo}/releases/tag/v{version}',
        'notes': notes,
        'min_version': min_version,
        'package': {'name': name, 'url': f'{base}/{name}', 'size': package.stat().st_size, 'sha256': sha},
    }
    (out / 'latest.json').write_text(json.dumps(latest, indent=2) + '\n', encoding='utf-8')
    print(f'{name}: {len(files)} files, {package.stat().st_size / 1e6:.1f} MB, sha256 {sha}')
    return package


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--manifest-only', action='store_true')
    parser.add_argument('tree')
    parser.add_argument('out', nargs='?')
    parser.add_argument('--notes', help='file with the release notes (Markdown)')
    parser.add_argument('--repo', help='GitHub OWNER/NAME (default: the official repository)')
    parser.add_argument('--min-version', default='2.1.0',
                        help='oldest installed version allowed to update in-app (older ones need the installer)')
    parser.add_argument('--base-url', help='where the zip will be downloadable from (default: the release)')
    args = parser.parse_args(argv)
    if args.manifest_only:
        engine = load_engine()
        tree = Path(args.tree).resolve()
        manifest = engine.build_manifest(tree, engine.read_version(tree))
        engine.save_json(tree / engine.MANIFEST, manifest)
        print(f"{tree / engine.MANIFEST}: {len(manifest['files'])} files, version {manifest['version']}")
        return 0
    if not args.out:
        parser.error('the output folder is missing')
    notes = Path(args.notes).read_text(encoding='utf-8') if args.notes else ''
    build(args.tree, args.out, notes, args.repo, args.min_version, args.base_url)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
