"""Reproduce Phase 2E without rewriting prior phase evidence."""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'phase2e/results'
def snapshot():
    paths=[]
    for folder in ('phase2a','phase2b','phase2c','phase2d'):
        for p in (ROOT/folder).rglob('*'):
            if not p.is_file() or any(part in {'.venv','__pycache__','local-m2','target'} for part in p.parts):continue
            paths.append(p)
    paths.extend(p for p in (ROOT/'docs').glob('*.md') if 'PHASE2E' not in p.name)
    paths.extend((ROOT/'gerbers').glob('*.zip'))
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
def command(args,log):
    proc=subprocess.run([sys.executable,*args],cwd=ROOT,capture_output=True,text=True)
    (OUT/log).write_text(proc.stdout+proc.stderr,encoding='utf-8')
    print(log,'exit',proc.returncode,flush=True)
    if proc.returncode:raise SystemExit(proc.returncode)
if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True);before=snapshot()
    command(['phase2e/recovery.py'],'generation.log')
    command(['phase2e/project_evidence.py'],'project-evidence.log')
    command(['phase2e/render_diagnostics.py'],'render-diagnostics.log')
    command(['-m','pytest','phase2a/test_verification.py','-q'],'test-phase2a.txt')
    command(['-m','unittest','-v','phase2b.test_phase2b'],'test-phase2b.txt')
    command(['-m','unittest','-v','phase2c.test_phase2c'],'test-phase2c.txt')
    command(['-m','unittest','-v','phase2d.test_regions'],'test-phase2d.txt')
    command(['-m','unittest','-v','phase2e.test_recovery'],'test-phase2e.txt')
    after=snapshot();changed=[p for p in before if after.get(p)!=before[p]]
    (OUT/'preservation.json').write_text(json.dumps({'priorFileCount':len(before),'changedPriorFiles':changed,'beforeSha256':before,'afterSha256':after},indent=2)+'\n')
    if changed:raise SystemExit('Prior evidence changed: '+repr(changed))
    print('All suites passed. Prior evidence hashes preserved.',flush=True)
