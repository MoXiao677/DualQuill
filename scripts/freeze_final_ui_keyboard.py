"""Freeze this isolated task's evidence and actual no-index source diff."""
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

workspace = Path(__file__).resolve().parents[1]
task = workspace.parent
shared = task.parent
baseline = shared / 'baseline'
evidence = task / 'evidence'
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
manifest = read(shared / 'baseline-manifest.json')
runs = [read(evidence / name / 'report.json') for name in ('baseline-ui-red-01','baseline-ui-red-02','workspace-ui-green-01')]
release = read(evidence / 'process-release.json')
assert release['owned_live_count'] == 0
assert runs[-1]['status'] == 'passed' and len(runs[-1]['checks']) == 37
assert all(not p['alive'] and p['exitCode'] == 0 for r in runs for p in r['processes'])
extra = ['docs/final-ui-keyboard-acceptance.md','tests/final-ui-keyboard-cdp.cjs','tests/final_ui_keyboard_server.py','tests/keyboard-composition.test.cjs','scripts/freeze_final_ui_keyboard.py']
source = {p: digest(workspace / p) for p in sorted(set(manifest['source_sha256']) | set(extra))}
changes = [p for p in manifest['source_sha256'] if source[p] != manifest['source_sha256'][p]]
assert set(changes) == {'src/novel_writer/ui/static/app.js','src/novel_writer/ui/static/rule_reviews.js','src/novel_writer/ui/static/style.css'}
assert all(source[p] == runs[-1]['source_sha256'][p] for p in changes), 'Product source changed after CDP GREEN'
diff = subprocess.run(['git','-c','core.autocrlf=false','-c','core.safecrlf=false','diff','--no-index','--binary','--',baseline.as_posix(),workspace.as_posix()],capture_output=True)
assert diff.returncode == 1
data = diff.stdout
for directory in (baseline, workspace):
    for prefix in ('a/', 'b/'):
        data = data.replace((prefix+directory.as_posix()+'/').encode(), prefix.encode())
(task / 'changes.diff').write_bytes(data)
inventory = {p.relative_to(task).as_posix(): {'sha256':digest(p),'bytes':p.stat().st_size} for p in sorted(evidence.rglob('*')) if p.is_file()}
verification = dict(task='04-ui-keyboard',frozen=True,created_at=datetime.now(timezone.utc).isoformat(),status='finite_source_ui_acceptance_passed_pending_parent_independent_review',overall_product_accepted=False,
    baseline_count=555,baseline_initial_differences=[],baseline_manifest_sha256=digest(shared/'baseline-manifest.json'),source_sha256=source,modified_source=changes,added_source=extra,
    changes_diff_sha256=digest(task/'changes.diff'),source_bound_to_final_cdp=True,source_cdp_runs=[dict(run=r['run'],status=r['status'],checks=len(r['checks']),passed=sum(c['status']=='passed' for c in r['checks']),failed=len(r['failures']),started_at=r['started_at'],finished_at=r['finished_at'],seconds=r['duration_seconds'],exit_code=r['exit_code'],report_sha256=digest(evidence/r['run']/'report.json'),failures=[x['name'] for x in r['failures']],fatal=r.get('fatal'),processes=r['processes']) for r in runs],
    static_runs=[read(evidence/n) for n in ['keyboard-handler-red-01-run.json','keyboard-handler-red-02-run.json','keyboard-handler-green-01-run.json','directed-node-green-01-run.json']],
    actual_ui_matrix=dict(pages=7,sizes=[[1440,900],[1280,720],[1024,768],[390,844]],cells=28,keyboard_and_input_checks=9,passed=37,screenshots=sum(p.suffix=='.png' for p in (evidence/'workspace-ui-green-01').iterdir())),
    process_release=release,real_paid_calls=0,final_fictional_provider_calls=runs[-1]['provider']['provider_calls'],external_page_requests=runs[-1]['external'],renderer_errors=runs[-1]['errors'],
    old_library='Not rerun; storage/schema/backend unchanged. Existing accepted baseline evidence retained, no new old-library claim.',restore_copy='Not rerun; no restore/copy/history/identity/transaction code changed.',manual_permissions='Lock and unlock independently confirmed; failed lock save retains input and leaves revision/body unchanged. Cost/execute consent not retained by new UI draft map; no model request sent.',
    unverified=['Windows real system IME','final integrated/new packaged EXE','real supplier semantic quality and billing','clean Windows install/upgrade/uninstall','large library and full backup/copy in this task','full 37 requirements and overall five-specialty completion'],
    evidence_files=inventory)
(task/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
handoff = f'''# 收尾04｜四尺寸界面与键盘输入验收

状态：本项源界面有限通过，待父独立审；不代表整体验收。只写本任务 workspace，主仓/baseline/其他副本未写。未打包、安装、签名、提交或推送，真实付费0。

## 基线与改动

初始555白名单全部匹配，manifest SHA256 `{verification['baseline_manifest_sha256']}`。实际差异 `changes.diff` SHA256 `{verification['changes_diff_sha256']}`。

仅3个产品文件：app.js四行组合输入守卫；rule_reviews.js保存按书隔离的连接/数值输入草稿，不保存任何费用/执行许可或来源预览；style.css仅规则审核pre换行。新增夹具/定向测试/矩阵/冻结脚本精确路径与全部源SHA见 verification.json。无schema、后端、历史SHA、来源身份、恢复复制或事务守卫修改。

## 实际结果（均保留原始失败）

- 静态red01：20项17fail/3pass，其中8项受CRLF提取器失败影响；有效red02：20项12fail/8pass。修后24/24。最终定向Node36/36，实际时长/退出码及日志SHA详列 verification.json/static_runs。
- baseline-ui-red-01：35检查，131.495秒，exit1；28格截图几何均保留。closed-details可见性误计、导航过早等待造成的假失败/级联超时明确归于驱动，不能冒充产品RED；fatal也保留。
- baseline-ui-red-02：37检查，34pass/3个有效RED，27.646秒，exit1。390规则页327px内容横滚626px；规则预算未保存跨页重置；合成IME Enter把dark改light并执行命令关闭弹框。
- workspace-ui-green-01：37/37，27.167秒，exit0；7入口×4尺寸28格、56截图与9键盘/输入检查。供应商调用0，页面外部请求/渲染异常为空。截图/几何/报告/console/backend/browser日志及完整SHA见 evidence_files。

真实页面覆盖规则语义审核、正文规划、深审/语义查重、竞技场、工作流、图谱、作者锁。键盘覆盖Ctrl+S、Ctrl+K、Tab/Shift+Tab、ArrowDown、Enter/Escape、合成组合期间禁止保存/命令，未保存正文和多类表单往返、失败输入保持、锁内写拒绝后正文/revision不变及独立解锁确认。已视觉检查原/修390规则页及1024工作流截图。

## 资源释放

实际开始09:39:30（Asia/Shanghai）；结束/进程零核查 `{release['checked_at']}`。三轮fixture/Edge根进程均exit0；实际CIM匹配自有根/子/driver为0，见 process-release.json。明确释放04资源，不自行授予05或延长窗口。最终三件套冻结后只供父审，主整合负责语义合并与新候选EXE独验。

## 旧库、恢复复制、许可与未验边界

旧库/完整恢复复制本项未重跑，不借旧结果冒充新测；这些路径及其历史/来源/事务断言均未改。风险预算数值是编辑输入，费用确认/逐请求执行许可不由草稿继承；本轮没有实际模型发送。合成DOM组合事件与CDP键盘仅证明本次浏览器路径，不证明Windows真实系统IME。固定接受EXE未重构/覆盖，新整合EXE、真实模型质量/账单、干净机安装升级卸载、37需求整体与五专项整体收口仍按既有外部门槛处理。
'''
(task/'HANDOFF.md').write_text(handoff,encoding='utf-8')
print(json.dumps(dict(status=verification['status'],modified=changes,added=extra,diff_sha256=digest(task/'changes.diff'),verification_sha256=digest(task/'verification.json'),handoff_sha256=digest(task/'HANDOFF.md'),evidence_files=len(inventory)),ensure_ascii=False))
