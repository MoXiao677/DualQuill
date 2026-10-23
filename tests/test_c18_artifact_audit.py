"""Synthetic ZIP/ASAR fixtures validate the auditor, not a real installer/build."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from scripts.c18_artifact_audit import audit, asar_files, safe_name

ROOT=Path(__file__).resolve().parents[1]
APP={'package.json','main.cjs','preload.cjs','security.cjs','backend.cjs','localization.cjs','THIRD-PARTY-NOTICES.txt'}


def sha(data):return hashlib.sha256(data).hexdigest()


def asar(files):
    offset=0;entries={};payload=b''
    for name,data in sorted(files.items()):
        entries[name]=dict(size=len(data),offset=str(offset));offset+=len(data);payload+=data
    header=json.dumps(dict(files=entries),separators=(',',':')).encode()
    pickle_payload=struct.pack('<I',len(header))+header
    pickle_payload+=b'\0'*((-len(pickle_payload))%4)
    header_pickle=struct.pack('<I',len(pickle_payload))+pickle_payload
    return struct.pack('<II',4,len(header_pickle))+header_pickle+payload


class ArtifactAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='fiction-c18-artifacts-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        self.backend='src/novel_writer/application/extensions.py'
        names=['desktop/'+name for name in APP]+['LICENSE','desktop/package-lock.json',self.backend]
        self.bound=[]
        for name in sorted(names):
            target=self.source/name;target.parent.mkdir(parents=True,exist_ok=True)
            data=(ROOT/name).read_bytes();target.write_bytes(data);self.bound.append(dict(file=name,sha256=sha(data)))
        self.binding=dict(algorithm='sha256',files=self.bound,
            digest=sha(json.dumps(self.bound,separators=(',',':')).encode()))
        lock=json.loads((ROOT/'desktop/package-lock.json').read_text(encoding='utf-8'))
        self.inventory=dict(version=lock['version'],application_license='MIT',
            public_distribution_approved=False,inputs=[],
            packages=[dict(path=name,**{k:entry[k] for k in ('version','license','resolved','integrity')})
                for name,entry in lock['packages'].items() if name])
        self.app={name:(ROOT/'desktop'/name).read_bytes() for name in APP}
        self.members={
            'resources/resource-manifest.json':json.dumps(dict(format=2,inputs=[],binding=self.binding,
                source=[dict(file=self.backend,sha256=sha((ROOT/self.backend).read_bytes()))])).encode(),
            'resources/dependency-inventory.json':json.dumps(self.inventory).encode(),
            'resources/backend/'+self.backend:(ROOT/self.backend).read_bytes(),
            'resources/app.asar':asar(self.app),
            'resources/LICENSE.application.txt':(ROOT/'LICENSE').read_bytes(),
            'resources/runtime/LICENSE.txt':b'fictional fixture notice; not a runtime distribution',
            'LICENSE.electron.txt':b'fictional fixture notice',
            'LICENSES.chromium.html':b'fictional fixture notice'}

    def archive(self):
        target=self.root/'synthetic.zip'
        with zipfile.ZipFile(target,'w') as package:
            for name,data in self.members.items():package.writestr(name,data)
        return target

    def test_valid_synthetic_package_is_readonly_and_reports_unverified_runtime_vm_signature(self):
        archive=self.archive();before=archive.read_bytes();report=audit(archive,self.source)
        self.assertTrue(report['verified']);self.assertEqual(report['dependency_declarations'],284)
        self.assertFalse(report['installer_executed']);self.assertFalse(report['clean_vm_tested'])
        self.assertFalse(report['runtime_binary_integrity_verified']);self.assertEqual(before,archive.read_bytes())

    def test_builder_external_notice_layout_requires_exact_bound_notice(self):
        notice=self.app.pop('THIRD-PARTY-NOTICES.txt')
        self.members['resources/app.asar']=asar(self.app)
        self.members['resources/THIRD-PARTY-NOTICES.txt']=notice
        self.assertTrue(audit(self.archive(),self.source)['verified'])
        self.members['resources/THIRD-PARTY-NOTICES.txt']=b'tampered notice'
        with self.assertRaisesRegex(ValueError,'notice'):audit(self.archive(),self.source)
        del self.members['resources/THIRD-PARTY-NOTICES.txt']
        with self.assertRaisesRegex(ValueError,'notice'):audit(self.archive(),self.source)

    def test_source_backend_and_asar_tampering_are_rejected(self):
        archive=self.archive();(self.source/'desktop/main.cjs').write_text('// tampered',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'source binding'):audit(archive,self.source)
        (self.source/'desktop/main.cjs').write_bytes((ROOT/'desktop/main.cjs').read_bytes())
        self.members['resources/backend/'+self.backend]=b'# tampered'
        with self.assertRaisesRegex(ValueError,'Backend bytes'):audit(self.archive(),self.source)
        self.members['resources/backend/'+self.backend]=(ROOT/self.backend).read_bytes()
        self.members['resources/app.asar']=asar(dict(self.app,**{'main.cjs':b'// tampered'}))
        with self.assertRaisesRegex(ValueError,'Desktop source'):audit(self.archive(),self.source)

    def test_archive_traversal_private_files_and_unexpected_backend_are_rejected(self):
        for name in ('../outside.py','C:/private.txt','resources/private.sqlite3','tests/fixture.txt',
                     'resources/backend/src/novel_writer/injected.py'):
            with self.subTest(name=name):
                self.members[name]=b'fiction'
                with self.assertRaises(ValueError):audit(self.archive(),self.source)
                del self.members[name]

    def test_dependency_inventory_and_notice_omission_are_rejected(self):
        self.inventory['packages'][0]['license']='invented-license'
        self.members['resources/dependency-inventory.json']=json.dumps(self.inventory).encode()
        with self.assertRaisesRegex(ValueError,'inventory'):audit(self.archive(),self.source)
        del self.members['resources/runtime/LICENSE.txt']
        with self.assertRaises(ValueError):audit(self.archive(),self.source)

    def test_bad_asar_bounds_and_path_are_rejected(self):
        for data in (b'bad',struct.pack('<IIII',4,0xffffffff,4,4)):
            with self.assertRaises(ValueError):asar_files(data)
        with self.assertRaises(ValueError):asar_files(asar({'../payload':b'fiction'}))
        for name in ('/absolute','../outside','a\\b','C:/file','a//b'):
            with self.assertRaises(ValueError):safe_name(name)

    def test_installer_is_only_read_for_pe_magic_and_hash(self):
        installer=self.root/'fictional.exe';installer.write_bytes(b'MZfictional-fixture-not-executable')
        report=audit(self.archive(),self.source,installer)
        self.assertEqual(report['installer']['sha256'],sha(installer.read_bytes()))
        self.assertFalse(report['installer_executed'])
        installer.write_bytes(b'not-pe')
        with self.assertRaisesRegex(ValueError,'PE header'):audit(self.archive(),self.source,installer)

class ApplicationLicenseAuditTests(unittest.TestCase):
    setUp=ArtifactAuditTests.setUp
    archive=ArtifactAuditTests.archive
    def test_missing_tampered_license_and_false_inventory_are_rejected(self):
        valid=self.members['resources/LICENSE.application.txt']
        del self.members['resources/LICENSE.application.txt']
        with self.assertRaisesRegex(ValueError,'license|LICENSE'):audit(self.archive(),self.source)
        self.members['resources/LICENSE.application.txt']=b'tampered'
        with self.assertRaisesRegex(ValueError,'license|LICENSE'):audit(self.archive(),self.source)
        self.members['resources/LICENSE.application.txt']=valid
        self.inventory['application_license']='UNLICENSED'
        self.members['resources/dependency-inventory.json']=json.dumps(self.inventory).encode()
        with self.assertRaisesRegex(ValueError,'license'):audit(self.archive(),self.source)
