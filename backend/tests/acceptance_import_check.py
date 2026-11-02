"""Synthetic-only acceptance import: rollback, file safety, RLS, vectors, idempotence."""
import copy,json,tempfile
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from app.features.identity.manage import migrate,bootstrap
from app.features.identity.acceptance_import import apply,regular,TABLES
from app.core.database import StoreError
ROOT=Path(__file__).resolve().parents[2]
c=json.loads((ROOT/'.identity-state/credentials.json').read_text())
assert '@127.0.0.1:15433/identity_test' in c['adminDsn']
name='identity_import_'+uuid4().hex[:10]
with psycopg.connect(c['adminDsn'],autocommit=True) as manager:
 manager.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
 try:
  args=conninfo_to_dict(c['adminDsn']);args['dbname']=name
  with psycopg.connect(**args,row_factory=dict_row,autocommit=True) as db,tempfile.TemporaryDirectory() as tmp:
   migrate(db);actor=bootstrap(db,'operator','迁移测试管理员','Synthetic-only-password-123')
   root=Path(tmp);src=root/'source';dest=root/'target';src.mkdir();dest.mkdir()
   rows={t:[] for t in TABLES};vector='['+','.join(['0.25']*1024)+']'
   rows['knowledge_categories']=[{'id':'cat','name':'原目录','parent_id':None},{'id':'child','name':'子目录','parent_id':'cat'}]
   rows['knowledge_purposes']=[{'id':'old','name':'历史用途','can_generate_template':False,'chunk_body':True,'inherit_chunking':True,'chunk_settings':{}}]
   rows['business_processes']=[{'id':'p','name':'原流程','description':'synthetic'}]
   rows['process_steps']=[{'id':'step','process_id':'p','name':'原步骤','objective':'synthetic','sort_order':0,'knowledge_scopes':['原目录']}]
   files=[]
   for id,space in [('a','zkxk'),('b','senyuan')]:
    file=src/(id+'.txt');file.write_text('Synthetic '+id)
    target=dest/'data/spaces'/space/'documents'/file.name
    files.append({'kind':'document','id':id,'source':str(file),'source_root':str(src),'target':str(target),**regular(file,src)})
    rows['knowledge_documents'].append({'id':id,'title':'同名资料','category_id':'child','original_name':file.name,'original_path':str(file),'mime_type':'text/plain','status':'effective','parsed_text':'Synthetic '+id,'chunk_settings':{},'purpose_id':'old','document_embedding':vector,'embedding_model':'synthetic'})
   rows['knowledge_chunks']=[{'id':'parent','document_id':'a','parent_chunk_id':None,'chunk_index':0,'content':'parent','token_count':1,'embedding':vector},
      {'id':'child-chunk','document_id':'a','parent_chunk_id':'parent','chunk_index':1,'content':'child','token_count':1,'embedding':vector}]
   skill={'id':'demo','space':'zkxk','skill':{'name':'demo','description':'合成技能','instructions':'仅用于测试','enabled':True},'draft_ready':True}
   mapping={'directory_plan':[{'source_id':id,'target_id':'zkxk-'+id,'target_space':'zkxk','parent_id':None if id=='cat' else 'zkxk-cat'} for id in ['cat','child']],
       'processes':[{'id':'p','target_space':'zkxk'}], 'documents':[{'id':id,'target_space':space,'target_category_id':'zkxk-child' if id=='a' else None} for id,space in [('a','zkxk'),('b','senyuan')]]}
   try:apply(db,rows,files,[skill],mapping,dest,actor,fail_after_files=True)
   except RuntimeError:pass
   else:raise AssertionError('failure injection did not fire')
   assert not any(Path(f['target']).exists() for f in files)
   assert db.execute('SELECT count(*) AS n FROM knowledge_documents').fetchone()['n']==0
   print('PASS file-stage interruption rolls back and removes only new files')
   bad=copy.deepcopy(skill);bad['skill']['description']=''
   try:apply(db,rows,files,[bad],mapping,dest,actor)
   except StoreError:pass
   else:raise AssertionError('invalid draft accepted')
   assert not any(Path(f['target']).exists() for f in files)
   assert db.execute('SELECT count(*) AS n FROM business_processes').fetchone()['n']==0
   print('PASS late validation failure restores DB and files')
   existing=Path(files[1]['target']);existing.write_text('existing user file')
   try:apply(db,rows,files,[skill],mapping,dest,actor)
   except FileExistsError:pass
   else:raise AssertionError('existing file overwritten')
   assert existing.read_text()=='existing user file' and not Path(files[0]['target']).exists()
   existing.unlink()
   result=apply(db,rows,files,[skill],mapping,dest,actor)
   assert result['documents']==2 and result['skill_drafts']==1
   for f in files:assert Path(f['target']).read_bytes()==Path(f['source']).read_bytes()
   assert db.execute("SELECT document_embedding::text AS v FROM knowledge_documents WHERE id='a'").fetchone()['v']==vector
   assert db.execute("SELECT parent_chunk_id FROM knowledge_chunks WHERE id='child-chunk'").fetchone()['parent_chunk_id']=='parent'
   assert db.execute('SELECT count(*) AS n FROM knowledge_documents WHERE owner_id IS NULL').fetchone()['n']==2
   assert db.execute('SELECT count(*) AS n FROM skill_publications').fetchone()['n']==0
   assert db.execute('SELECT status FROM review_submissions').fetchone()['status']=='draft'
   print('PASS IDs, same-title documents, original bytes, vectors, ancestry and unknown authors preserved; skills remain drafts')
   db.execute("UPDATE knowledge_documents SET title='验收中修改' WHERE id='a'")
   assert apply(db,rows,files,[skill],mapping,dest,actor)=={'already_imported':True}
   assert db.execute("SELECT title FROM knowledge_documents WHERE id='a'").fetchone()['title']=='验收中修改'
   db.execute('GRANT USAGE ON SCHEMA public TO department_app')
   db.execute('GRANT SELECT ON ALL TABLES IN SCHEMA public TO department_app')
   for space,expected in [('zkxk',['a']),('senyuan',['b']),('shared',[])]:
    with db.transaction():
     db.execute('SET LOCAL ROLE department_app');db.execute("SELECT set_config('department.space',%s,true)",(space,))
     assert [r['id'] for r in db.execute('SELECT id FROM knowledge_documents')]==expected
   print('PASS company isolation, shared empty, repeat import preserves later changes')
 finally:manager.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
print('acceptance-import-check: passed; disposable synthetic database removed')
