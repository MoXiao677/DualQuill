"""Reproducible fictional end-to-end C08 benchmark; standard library only.

Run in an isolated workspace. --output-dir must be a new directory. Never opens
an existing database, contacts a provider, or reads a credential/profile.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid5,NAMESPACE_URL

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from novel_writer.application.service import NovelService
from novel_writer.application.materials import Materials
from novel_writer.application.lexical_rank import rank
from novel_writer.storage.sqlite_repository import SQLiteRepository


def timed(function):
    start=time.perf_counter();value=function();return value,(time.perf_counter()-start)*1000


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--material-chars',type=int,default=50000)
    parser.add_argument('--materials',type=int,default=4)
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    if not 1000<=args.material_chars<=1_000_000 or not 1<=args.materials<=10 or not 1<=args.repeats<=10:parser.error('benchmark size outside declared bounds')
    out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=False);tmp=out/'tmp';tmp.mkdir()
    os.environ.update(TEMP=str(tmp),TMP=str(tmp));tempfile.tempdir=str(tmp)
    db=out/'fictional.sqlite3';service=NovelService(SQLiteRepository(db));materials=Materials(service)
    state=service.create(title='C08可复现实验（全部虚构）');pid=state['document']['project']['id']
    state=service.execute(pid,'add_chapter',dict(title='虚构章'),expected_revision=state['revision']);chapter=state['document']['chapters'][0]['id']
    ordinal=0
    def request():
        nonlocal ordinal
        ordinal+=1
        return dict(operation_id=str(uuid5(NAMESPACE_URL,'fiction-c08-benchmark/'+str(ordinal))),expected_revision=service.get(pid)['revision'])
    texts=[];ids=[];build_ms=[]
    for index in range(args.materials):
        sentence=f'虚构编号{index}：古城河道举行龙舟竞渡。CAFÉ Straße 가 😀。普通村民整理档案。\n'
        text=(sentence*((args.material_chars//len(sentence))+1))[:args.material_chars];texts.append(text)
        created=materials.create(pid,dict(request(),title=f'虚构资料{index}',format='txt',tags=[],text=text));mid=created['material']['id'];ids.append(mid)
        _,elapsed=timed(lambda:materials.rebuild(pid,mid,request()));build_ms.append(elapsed)
    queries=['古城 龙舟','CAFÉ','STRASSE','麒麟不存在']
    trials=[]
    with patch('socket.create_connection',side_effect=AssertionError('network forbidden in C08 benchmark')):
        for query in queries:
            durations=[];signature=None;hit_count=0
            for _ in range(args.repeats):
                result,elapsed=timed(lambda:service.search_local(pid,dict(query=query,chapter_id=chapter,scopes=['materials'],material_ids=ids,mode='hybrid',limit=10)))
                durations.append(elapsed);hit_count=len(result['hits'])
                stable=[(h['entity_id'],h['selection']['excerpt'],h['start'],h['end'],h['score']) for h in result['hits']]
                if signature is None:signature=stable
                else:assert stable==signature,'ranking was not reproducible'
            if query=='麒麟不存在':assert hit_count==0
            else:assert hit_count>0
            trials.append(dict(query=query,hits=hit_count,trials_ms=durations,median_ms=statistics.median(durations),max_ms=max(durations)))
    original=materials.describe(pid,ids[0]);text=texts[0][:-1]+'新'
    materials.update(pid,ids[0],dict(request(),title='虚构资料0',format='txt',tags=[],text=text))
    changed,incremental_ms=timed(lambda:materials.rebuild(pid,ids[0],request()))
    assert changed['index_update']['rebuilt_chunks']==1
    quality_docs=[dict(text='普通村民整理档案。'),dict(text='古城河道中的龙舟竞渡。'),dict(text='古城城墙的石料。'),dict(text='😀 ＣＡＦＥ\u0301 Straße')]
    quality=[]
    for query,expected in [('古城 龙舟',1),('café',3),('STRASSE',3),('从未出现的麒麟',None)]:
        hits=rank(query,quality_docs);actual=quality_docs.index(hits[0]['document']) if hits else None;assert actual==expected
        quality.append(dict(query=query,expected_top=expected,actual_top=actual,passed=True))
    report=dict(method='unicode_lexical_bm25_phrase_rrf_v1',semantic=False,real_provider_calls=0,
        command=[sys.executable,*sys.argv],
        source_sha256={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/'src/novel_writer/application/lexical_rank.py',ROOT/'src/novel_writer/application/hybrid_retrieval.py',ROOT/'src/novel_writer/application/retrieval.py',ROOT/'src/novel_writer/application/materials.py',ROOT/'src/novel_writer/storage/sqlite_repository.py']},
        environment=dict(python=platform.python_version(),platform=platform.platform(),machine=platform.machine()),
        corpus=dict(materials=args.materials,chars_per_material=args.material_chars,total_chars=sum(map(len,texts)),sha256=hashlib.sha256(''.join(texts).encode()).hexdigest(),fictional=True),
        initial_build_ms=build_ms,queries=trials,quality=quality,incremental=dict(elapsed_ms=incremental_ms,**changed['index_update']),
        limitations=['本机单进程定向报告，不是桌面或跨机承诺','持久化仍校验完整快照；词项/BM25按请求扫描，尚无持久倒排表','增量复用未改变的固定窗口ID/哈希，字符插入导致位移时会重算受影响窗口'])
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(report=str(out/'report.json'),total_chars=report['corpus']['total_chars'],query_median_ms={v['query']:round(v['median_ms'],3) for v in trials},incremental=report['incremental'],real_provider_calls=0),ensure_ascii=False))


if __name__=='__main__':main()
