from pathlib import Path
import importlib.util, json, re, shutil, subprocess
source=Path(__file__).resolve().parents[3]
installed=Path.home()/'.codex/skills/skill-release-manager'
candidate=Path('/private/tmp/gongchuang-publisher-review-20260921')
(candidate/'scripts').mkdir(parents=True,exist_ok=True)
(candidate/'references').mkdir(exist_ok=True)
for p in (installed/'scripts').glob('*.py'):shutil.copy2(p,candidate/'scripts'/p.name)
shutil.copy2(source/'toolchain-candidates/skill-release-manager/references/portable-runtime-notice.md',candidate/'references/portable-runtime-notice.md')
subprocess.run(['patch','--batch','-p1','-i',str(source/'toolchain-candidates/skill-release-manager/package-runtime-notice.patch')],cwd=candidate,check=True)
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
old=load('old_publisher',installed/'scripts/package_skill_release.py');new=load('new_publisher',candidate/'scripts/package_skill_release.py')
pat=re.compile(re.escape(new.RUNTIME_MARKER_START)+r'.*?'+re.escape(new.RUNTIME_MARKER_END),re.S)
canonical=(candidate/'references/portable-runtime-notice.md').read_text().strip()
results=[]
for p in sorted((source/'skills').glob('*/SKILL.md')):
 before=p.read_text();oldroot=candidate/'old-output'/p.parent.name;newroot=candidate/'new-output'/p.parent.name
 for out in [oldroot,newroot]:out.mkdir(parents=True,exist_ok=True);(out/'SKILL.md').write_text(before)
 old.ensure_runtime_instructions(oldroot,p.parent.name);new.ensure_runtime_instructions(newroot,p.parent.name)
 updated=(newroot/'SKILL.md').read_text();new.ensure_runtime_instructions(newroot,p.parent.name)
 result={'skill':p.parent.name,'old_publisher_replaces_candidate_notice':pat.search((oldroot/'SKILL.md').read_text()).group()!=canonical,'candidate_notice_preserved':pat.search(updated).group()==canonical,'second_pass_identical':updated==(newroot/'SKILL.md').read_text()}
 assert result['candidate_notice_preserved'] and result['second_pass_identical'],result
 results.append(result)
report={'scope':'isolated instruction preparation only; no signing, installation or release','skill_count':len(results),'old_publisher_replacements':sum(x['old_publisher_replaces_candidate_notice'] for x in results),'candidate_preserved':sum(x['candidate_notice_preserved'] for x in results),'idempotent':sum(x['second_pass_identical'] for x in results),'candidate_publisher':str(candidate),'results':results}
out=source/'docs/product/evidence/publisher-notice-check-20260921.json';out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False))
