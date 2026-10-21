"""Inspect Git upload candidates without staging files or printing credentials."""
from collections import Counter
import fnmatch
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIRS = {
    '.local', '.ui-work', '.runtime', '.venv', 'venv', 'node_modules', '__pycache__',
    'cache', 'chart_cache', 'output', 'customs_workspace', 'earnings_workspace',
    'classification_sources', 'classification_reports',
}
LOCAL_FILES = {'industry_overrides.json', 'instrument_exclusions.json', 'sectors.json',
               'sector_etfs.json', 'recap_cache.json', 'complete_cleanup.ps1'}


def candidate_files(root=ROOT):
    command = ['git', '-c', 'safe.directory=' + root.as_posix(), '-C', str(root),
               'ls-files', '--cached', '--others', '--exclude-standard', '-z']
    result = subprocess.run(command, capture_output=True, check=True)
    names = {name.decode('utf-8') for name in result.stdout.split(b'\0') if name}
    return sorted(root / name for name in names if (root / name).is_file())


def local_reason(relative):
    if any(part in LOCAL_DIRS for part in relative.parts):
        return 'local workspace or generated directory'
    if relative.parts[:2] in {('earnings', '자료'), ('earnings', '결과')}:
        return 'personal earnings inputs or reports'
    name = relative.name
    if name in LOCAL_FILES or fnmatch.fnmatch(name, 'screen_cache*.json'):
        return 'personal state or one-time maintenance script'
    if name == '.env' or (name.startswith('.env.') and name != '.env.example'):
        return 'credential file'
    if any(fnmatch.fnmatch(name, pattern) for pattern in ('*.sqlite3*', '*.db', '*.parquet', '*.log', '*.tmp', 'KUIM_*.xlsx', 'CLEANUP-*.json')):
        return 'database, source workbook or generated artifact'
    return ''


def main():
    files = candidate_files()
    problems = []
    secret = ''
    env = ROOT / '.env'
    if env.is_file():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            name, _, value = line.strip().removeprefix('export ').partition('=')
            if name.strip() == 'CUSTOMS_API_KEY':
                secret = value.strip().strip('\"\'')
    # Concrete personal home paths belong in local records, not shared source.
    home_pattern = re.compile(r'(?i)(?:[a-z]:[\\/]+Users[\\/]+|/Users/|/home/)[a-z0-9_.-]+')
    for path in files:
        relative = path.relative_to(ROOT)
        reason = local_reason(relative)
        if reason:
            problems.append(f'{relative.as_posix()}: {reason}')
            continue
        if path.stat().st_size > 10 * 1024 * 1024:
            problems.append(f'{relative.as_posix()}: file exceeds 10 MiB; review before publishing')
        raw = path.read_bytes()
        if secret and secret.encode() in raw:
            problems.append(f'{relative.as_posix()}: contains the local Customs credential')
        if path.suffix in {'.py', '.js', '.mjs', '.cjs', '.md', '.yaml', '.json', '.ps1', '.txt', '.cmd'}:
            if home_pattern.search(raw.decode('utf-8-sig', errors='replace')):
                problems.append(f'{relative.as_posix()}: contains a personal absolute home path')
    if problems:
        print('\n'.join(problems), file=sys.stderr)
        return 1
    groups = Counter(path.relative_to(ROOT).parts[0] if len(path.relative_to(ROOT).parts) > 1 else '(root)' for path in files)
    print(json.dumps({'files': len(files), 'bytes': sum(path.stat().st_size for path in files),
                      'groups': dict(sorted(groups.items())), 'local_data_and_credentials': 'excluded'}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
