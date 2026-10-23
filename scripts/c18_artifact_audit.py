"""Read-only ZIP/ASAR and optional NSIS header audit. Never extracts or runs artifacts."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import sys
import zipfile

MAX_MEMBER=512*1024*1024
MAX_TOTAL=2*1024*1024*1024


def require(condition,message):
    if not condition:raise ValueError(message)


def digest(data):return hashlib.sha256(data).hexdigest()


def safe_name(name):
    require(isinstance(name,str) and name and '\\' not in name and ':' not in name,
            'Unsafe archive path')
    require(not name.startswith('/') and all(part not in ('','..','.') for part in name.rstrip('/').split('/')),
            'Archive path traversal')
    return name


def asar_files(data):
    require(len(data)>=16,'Truncated ASAR')
    size_payload,header_size,header_payload,json_size=struct.unpack_from('<IIII',data)
    require(size_payload==4 and 8<=header_size<=16*1024*1024 and
            header_payload==header_size-4 and json_size<=header_size-8 and
            8+header_size<=len(data),'Invalid ASAR pickle header')
    header=json.loads(data[16:16+json_size].decode('utf-8'));result={}
    def walk(directory,prefix=''):
        require(type(directory) is dict and type(directory.get('files')) is dict,'Invalid ASAR directory')
        for name,entry in directory['files'].items():
            require('/' not in name,'Invalid ASAR name');safe_name(name)
            relative=prefix+name
            require(type(entry) is dict and not entry.get('link') and not entry.get('unpacked'),
                    'ASAR links/unpacked files are not supported by this application allowlist')
            if 'files' in entry:walk(entry,relative+'/');continue
            offset=int(entry['offset']);size=entry['size'];start=8+header_size+offset
            require(type(size) is int and 0<=size<=MAX_MEMBER and offset>=0 and start+size<=len(data),
                    'ASAR entry out of range')
            result[relative]=data[start:start+size]
    walk(header)
    return result


def audit(archive,source_root,installer=None):
    root=Path(source_root).resolve();archive=Path(archive)
    with zipfile.ZipFile(archive) as package:
        names=package.namelist();require(len(names)==len(set(names)),'Duplicate ZIP entries')
        require(len(names)<=20000 and sum(item.file_size for item in package.infolist())<=MAX_TOTAL,
                'Archive resource limit')
        for info in package.infolist():
            safe_name(info.filename)
            require(info.file_size<=MAX_MEMBER and (info.external_attr>>16)&0o170000!=0o120000,
                    'Oversized member or archive symlink')
            parts=PurePosixPath(info.filename).parts
            require(not any(p.lower() in ('.git','.cache','node_modules','tests','fixtures','author-preview') for p in parts),
                    'Forbidden private/build/test archive member')
            require(not info.filename.lower().endswith(('.sqlite','.sqlite3','.db','.dpapi','.log','.env')),
                    'Private data/credential/log archive member')
        def find(suffix):
            matches=[name for name in names if name.endswith(suffix)]
            require(len(matches)==1,'Missing or ambiguous artifact resource: '+suffix)
            return matches[0]
        manifest=json.loads(package.read(find('resources/resource-manifest.json')))
        inventory=json.loads(package.read(find('resources/dependency-inventory.json')))
        binding=manifest['binding'];require(manifest['format']==2 and binding['algorithm']=='sha256','Unsupported source manifest')
        canonical=json.dumps(binding['files'],ensure_ascii=False,separators=(',',':')).encode('utf-8')
        require(digest(canonical)==binding['digest'],'Source binding digest mismatch')
        bound={item['file']:item['sha256'] for item in binding['files']}
        require(len(bound)==len(binding['files']) and list(bound)==sorted(bound),'Source binding order/duplicates')
        for relative,expected in bound.items():
            safe_name(relative);target=root.joinpath(*PurePosixPath(relative).parts)
            require(target.resolve().is_relative_to(root) and not target.is_symlink(),'Source path escapes root')
            require(digest(target.read_bytes())==expected,'Artifact source binding differs: '+relative)
        expected_backend={entry['file']:entry['sha256'] for entry in manifest['source']}
        require(expected_backend and len(expected_backend)==len(manifest['source']),'Empty/duplicate backend manifest')
        backend_prefix=find('resources/resource-manifest.json').removesuffix('resource-manifest.json')+'backend/'
        actual_backend={name[len(backend_prefix):] for name in names if name.startswith(backend_prefix) and not name.endswith('/')}
        require(actual_backend==set(expected_backend),'Backend member allowlist mismatch')
        for relative,expected in expected_backend.items():
            safe_name(relative);require(bound.get(relative)==expected,'Backend source not bound')
            require(digest(package.read(backend_prefix+relative))==expected,'Backend bytes differ: '+relative)
        app=asar_files(package.read(find('resources/app.asar')))
        package_json=json.loads(app['package.json'])
        require(package_json['version']==inventory['version'] and package_json['license']=='MIT',
                'Packaged application identity/license mismatch')
        expected_app={'package.json','main.cjs','preload.cjs','security.cjs','backend.cjs','localization.cjs'}
        notice='THIRD-PARTY-NOTICES.txt'
        require(set(app) in (expected_app,expected_app|{notice}),'Unexpected ASAR files')
        for name in expected_app-{'package.json'}:
            require(digest(app[name])==bound.get('desktop/'+name),'Desktop source bytes differ: '+name)
        # electron-builder excludes an extraResources input from app.asar. Both
        # historical embedded and actual external layouts remain hash-bound.
        notices=[package.read(name) for name in names if name.endswith('resources/'+notice)]
        require(len(notices)<=1,'Ambiguous application notice')
        if notice in app:notices.append(app[notice])
        require(notices and all(digest(data)==bound.get('desktop/'+notice) for data in notices),
                'Application notice missing or bytes differ')
        application_license=package.read(find('resources/LICENSE.application.txt'))
        require(bound.get('LICENSE') is not None and digest(application_license)==bound['LICENSE'],
                'Application license missing or bytes differ')
        require(application_license.startswith(b'MIT License') and b'Permission is hereby granted, free of charge' in application_license,
                'Application MIT license text invalid')
        # electron-builder may normalize package.json; compare security-relevant fields explicitly.
        declared=json.loads((root/'desktop/package.json').read_text(encoding='utf-8'))
        for key in ('name','version','main','license'):
            require(package_json.get(key)==declared.get(key),'ASAR package identity differs: '+key)
        require(inventory['inputs']==manifest['inputs'],'Runtime manifest differs')
        require(inventory['application_license']=='MIT' and inventory['public_distribution_approved'] is False,
                'Artifact application license or publication approval mismatch')
        lock=json.loads((root/'desktop/package-lock.json').read_text(encoding='utf-8'))
        actual_licenses={p['path']:(p['version'],p['license'],p['resolved'],p['integrity']) for p in inventory['packages']}
        locked_licenses={name:(p['version'],p['license'],p['resolved'],p['integrity']) for name,p in lock['packages'].items() if name}
        require(actual_licenses==locked_licenses,'Dependency inventory differs from bound lockfile')
        find('resources/runtime/LICENSE.txt');find('LICENSES.chromium.html')
        require(any(name.endswith(('LICENSE.electron.txt','LICENSE')) for name in names),'Electron license text missing')
    report=dict(verified=True,mode='static_read_only',archive=str(archive.resolve()),
                archive_sha256=digest(archive.read_bytes()),source_digest=binding['digest'],
                source_files=len(bound),backend_files=len(expected_backend),desktop_files=len(app),
                dependency_declarations=len(actual_licenses),installer_executed=False,
                runtime_binary_integrity_verified=False,
                signature_verified=False,clean_vm_tested=False,real_provider_calls=0)
    if installer:
        installer=Path(installer)
        with installer.open('rb') as stream:require(stream.read(2)==b'MZ','Installer does not have a PE header')
        report['installer']=dict(path=str(installer.resolve()),sha256=digest(installer.read_bytes()),
                                 scope='PE magic and SHA-256 only; NSIS behavior/signature not verified')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip',required=True,type=Path)
    parser.add_argument('--source-root',required=True,type=Path)
    parser.add_argument('--installer',type=Path)
    parser.add_argument('--report',required=True,type=Path)
    args=parser.parse_args()
    try:report=audit(args.zip,args.source_root,args.installer);code=0
    except (ValueError,KeyError,OSError,zipfile.BadZipFile,struct.error) as error:
        report=dict(verified=False,error=str(error),installer_executed=False,real_provider_calls=0);code=1
    require(not args.report.exists(),'Refusing to overwrite previous artifact evidence')
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return code


if __name__=='__main__':sys.exit(main())
