"""One-time real-data rehearsal into the isolated acceptance DB; dry-run by default."""
import argparse
import base64
import json
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
from urllib.parse import urlsplit

from dotenv import dotenv_values
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.features.identity.service import audit
from app.features.reviews.service import normalize
from app.features.skills.service import _read

ROOT=Path('/root/liao/DepartmentKnowledgeBase/department-ai/runtime-data/worktrees/identity-access-20261028')
SOURCE=Path('/root/liao/DepartmentKnowledgeBase/department-ai')
STATE=ROOT/'.identity-state'
RUN='legacy-acceptance-20261029'
TABLES=('knowledge_categories','knowledge_purposes','business_processes','process_steps','knowledge_documents','knowledge_chunks')
LIMIT=2*1024*1024


def private_json(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as out:json.dump(value,out,ensure_ascii=False,indent=2,default=str)
    path.chmod(0o600)


def regular(path,root):
    if not path.is_absolute() or path.resolve()!=path or not path.is_relative_to(root):
        raise ValueError('Unmanaged or symlink path: '+str(path))
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>LIMIT:
        raise ValueError('Not a regular small file: '+str(path))
    return {'bytes':info.st_size,'mtime_ns':info.st_mtime_ns,'inode':info.st_ino}


def connection_info():
    if Path.cwd()!=ROOT:raise ValueError('Run only from the isolated worktree')
    c=json.loads((STATE/'acceptance-db.json').read_text())
    target=urlsplit(c['adminDsn'])
    if (target.hostname,target.port,target.path)!=('127.0.0.1',15433,'/identity_acceptance_20261028'):
        raise ValueError('Not the isolated acceptance database')
    info=json.loads(subprocess.check_output(['docker','inspect','department-identity-dev-20261028'],text=True))[0]
    if info['Config']['Labels'].get('department.identity-development')!='true':
        raise ValueError('Database container ownership mismatch')
    v=dotenv_values(SOURCE/'.env',interpolate=False)
    return v['DEPARTMENT_DATABASE_URL'],c['adminDsn']


def collect(conn,mapping):
    if conn.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']!='on':
        raise ValueError('Source transaction must be read-only')
    if conn.execute("SELECT to_regclass('public.spaces') AS found").fetchone()['found']:
        raise ValueError('Source is not the expected legacy schema')
    rows={t:conn.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(t))).fetchall() for t in TABLES}
    for key,table in [('processes','business_processes'),('documents','knowledge_documents')]:
        if {x['id'] for x in rows[table]}!={x['id'] for x in mapping[key]}:
            raise ValueError('Source inventory changed; reconfirm '+key)
    files=[]
    for document in rows['knowledge_documents']:
        m=next(x for x in mapping['documents'] if x['id']==document['id'])
        source=Path(document['original_path']); allowed=SOURCE/'runtime-data/department-ai-python'
        if document['id']=='knowledge-1787192769204':
            expected='/Users/liao/Desktop/Department Knowledge Base/department-ai/runtime-data/department-ai/documents/knowledge-1787192769204.docx'
            if str(source)!=expected:raise ValueError('Legacy source override no longer matches')
            allowed=SOURCE/'runtime-data/department-ai'
            source=allowed/'documents/knowledge-1787192769204.docx'
        target=STATE/'acceptance/data/spaces'/m['target_space']/'documents'/source.name
        files.append({'kind':'document','id':document['id'],'source':str(source),'source_root':str(allowed),
                      'target':str(target),**regular(source,allowed)})
    skills=[]; root=SOURCE/'runtime-data/department-skills'
    for item in mapping['skills']:
        folder=root/item['id']; resource_paths=[]; ignored=[]
        if folder.resolve()!=folder or not folder.is_dir():raise ValueError('Unsafe skill folder')
        for base,dirs,names in os.walk(folder,followlinks=False):
            if any((Path(base)/d).is_symlink() for d in dirs):
                raise ValueError('Skill contains a linked directory')
            excluded=[d for d in dirs if d.startswith('.') or d in ('node_modules','__pycache__','dist','build')]
            ignored.extend(str((Path(base)/d).relative_to(folder)) for d in excluded)
            dirs[:]=[d for d in dirs if d not in excluded]
            for name in sorted(names):
                p=Path(base)/name;relative=p.relative_to(folder).as_posix()
                if name.startswith('.'):
                    ignored.append(relative);continue
                resource_paths.append(relative)
                files.append({'kind':'skill','id':item['id'],'relative':relative,'source':str(p),'source_root':str(folder),
                    'target':str(STATE/'acceptance/skill-imports'/item['target_space']/item['id']/relative),**regular(p,folder)})
        if len(resource_paths)>30:raise ValueError('Too many skill resources')
        skill=_read(folder)
        unsupported=[p for p in resource_paths if p!='SKILL.md' and p.split('/')[0] not in ('scripts','references','assets')]
        skills.append({'id':item['id'],'space':item['target_space'],'skill':{k:skill[k] for k in ('name','description','instructions','enabled')},
                       'unsupported':unsupported,'ignored':ignored,'draft_ready':not unsupported and item['id']==skill['name']})
    if sum(x['bytes'] for x in files)>15*1024*1024:raise ValueError('Copy plan exceeds small-file limit')
    return rows,files,skills


def insert(conn,table,row):
    values=[Jsonb(v) if isinstance(v,(dict,list)) else v for v in row.values()]
    conn.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),
                 sql.SQL(',').join(map(sql.Identifier,row)),sql.SQL(',').join(sql.Placeholder() for _ in row)),values)


def categories(conn,rows):
    pending=list(rows);done=set()
    while pending:
        ready=[r for r in pending if r['parent_id'] is None or r['parent_id'] in done]
        if not ready:raise ValueError('Invalid directory ancestry')
        for row in ready:insert(conn,'knowledge_categories',row);done.add(row['id']);pending.remove(row)


def apply(conn,rows,files,skills,mapping,target_root,actor,fail_after_files=False):
    created=[];committed=False
    try:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",(RUN,))
            if conn.execute("SELECT 1 FROM audit_events WHERE action='migration.acceptance_import' AND target_id=%s",(RUN,)).fetchone():
                return {'already_imported':True}
            for table in ('business_processes','knowledge_documents','knowledge_categories','review_submissions','skill_publications'):
                if conn.execute(sql.SQL('SELECT 1 FROM {} LIMIT 1').format(sql.Identifier(table))).fetchone():
                    raise ValueError('Target business data is not empty; refusing to overwrite')
            for f in files:
                source=Path(f['source']);target=Path(f['target'])
                if regular(source,Path(f['source_root']))!={k:f[k] for k in ('bytes','mtime_ns','inode')}:
                    raise ValueError('Source file changed since planning')
                if not target.is_relative_to(target_root) or target.resolve()!=target:
                    raise ValueError('Unsafe destination')
                content=source.read_bytes()
                if len(content)!=f['bytes'] or regular(source,Path(f['source_root']))!={k:f[k] for k in ('bytes','mtime_ns','inode')}:
                    raise ValueError('Source changed while copying')
                target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);created.append(target)
                with os.fdopen(fd,'wb') as out:out.write(content)
            if fail_after_files:raise RuntimeError('Synthetic injected failure after file creation')
            # Preserve legacy directory inventory, plus explicitly mapped company copies.
            categories(conn,[{**r,'space_id':'legacy','owner_id':None} for r in rows['knowledge_categories']])
            oldcats={r['id']:r for r in rows['knowledge_categories']}
            for space in ('zkxk','senyuan','shared'):
                copies=[{**oldcats[m['source_id']],'id':m['target_id'],'parent_id':m['parent_id'],'space_id':space,'owner_id':None}
                        for m in mapping['directory_plan'] if m['target_space']==space]
                categories(conn,copies)
            for space in ('zkxk','senyuan'):
                # Target is empty of business data, so seeded purpose defaults can safely be replaced.
                conn.execute('DELETE FROM knowledge_purposes WHERE space_id=%s',(space,))
                for row in rows['knowledge_purposes']:insert(conn,'knowledge_purposes',{**row,'space_id':space,'owner_id':None})
            processes={m['id']:m['target_space'] for m in mapping['processes']}
            for row in rows['business_processes']:insert(conn,'business_processes',{**row,'space_id':processes[row['id']],'owner_id':None})
            for row in rows['process_steps']:insert(conn,'process_steps',{**row,'space_id':processes[row['process_id']],'owner_id':None})
            documents={m['id']:m for m in mapping['documents']}
            paths={f['id']:f['target'] for f in files if f['kind']=='document'}
            for row in rows['knowledge_documents']:
                m=documents[row['id']]
                insert(conn,'knowledge_documents',{**row,'category_id':m['target_category_id'],'space_id':m['target_space'],'owner_id':None,'original_path':paths[row['id']]})
            # Parent chunks are referenced within the same transaction, in ancestry order.
            pending=list(rows['knowledge_chunks']);done=set()
            while pending:
                ready=[r for r in pending if not r['parent_chunk_id'] or r['parent_chunk_id'] in done]
                if not ready:raise ValueError('Invalid chunk ancestry')
                for row in ready:
                    insert(conn,'knowledge_chunks',{**row,'space_id':documents[row['document_id']]['target_space'],'owner_id':None})
                    done.add(row['id']);pending.remove(row)
            draft_ids=[]
            for skill in skills:
                if not skill['draft_ready']:continue
                resources=[{'path':f['relative'],'contentBase64':base64.b64encode(Path(f['target']).read_bytes()).decode()}
                           for f in files if f['kind']=='skill' and f['id']==skill['id'] and f['relative']!='SKILL.md']
                request=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(max_source_bytes=15*1024*1024)))
                payload=normalize(request,'skills',{'skill':skill['skill'],'resources':resources})
                id=RUN+'-'+skill['id'];draft_ids.append(id)
                insert(conn,'review_submissions',{'id':id,'space_id':skill['space'],'owner_id':actor,'kind':'skills',
                    'title':skill['skill']['name'],'draft':payload,'source_key':id})
            result={'documents':len(documents),'processes':len(processes),'steps':len(rows['process_steps']),
                    'chunks':len(rows['knowledge_chunks']),'files':len(files),'skill_drafts':len(draft_ids),
                    'skills_held':[s['id'] for s in skills if not s['draft_ready']]}
            audit(conn,actor,'migration.acceptance_import',RUN,details=result)
        committed=True
        return result
    finally:
        if not committed:
            for path in reversed(created):path.unlink(missing_ok=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');args=p.parse_args()
    source_dsn,target_dsn=connection_info()
    mapping=json.loads((STATE/'legacy-ownership-confirmed-20261028.json').read_text())
    if any(m['target_space'] not in ('zkxk','senyuan','shared') for k in ('documents','skills','processes') for m in mapping[k]):
        raise ValueError('Unconfirmed space')
    with psycopg.connect(source_dsn,row_factory=dict_row,options='-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=1000') as source:
        source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        rows,files,skills=collect(source,mapping)
        plan={'run':RUN,'copy_bytes':sum(f['bytes'] for f in files),'files':files,'counts':{k:len(v) for k,v in rows.items()},
              'skill_review':[{'id':s['id'],'draft_ready':s['draft_ready'],'unsupported':s['unsupported'],'ignored':s['ignored']} for s in skills]}
        private_json(STATE/'real-data-plan-20261029.json',plan)
        if not args.apply:
            print(json.dumps({k:v for k,v in plan.items() if k!='files'},ensure_ascii=False));return
        if not (STATE/'real-data-copy-approved-20261029').is_file():raise ValueError('User confirmation of binary copying is required')
        with psycopg.connect(target_dsn,row_factory=dict_row,autocommit=True) as target:
            actor=target.execute("SELECT id FROM users WHERE username='liao-admin' AND active AND superadmin").fetchone()
            if not actor:raise ValueError('Acceptance operator unavailable')
            result=apply(target,rows,files,skills,mapping,STATE/'acceptance',actor['id'])
        if not result.get('already_imported'):
            private_json(STATE/'real-data-result-20261029.json',result)
        print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
