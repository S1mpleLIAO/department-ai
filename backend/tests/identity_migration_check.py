"""Legacy-schema migration rehearsal, disposable database in the test container."""
import json
import tempfile
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from app.features.identity.manage import migrate
from app.features.identity.inventory import collect, file_metadata

ROOT=Path(__file__).resolve().parents[2]
config=json.loads((ROOT/".identity-state/credentials.json").read_text())
assert "@127.0.0.1:15433/identity_test" in config["adminDsn"]
name="identity_legacy_"+uuid4().hex[:10]
with psycopg.connect(config["adminDsn"],autocommit=True) as manager:
    manager.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        args=conninfo_to_dict(config["adminDsn"]);args["dbname"]=name
        with psycopg.connect(**args,row_factory=dict_row) as conn:
            conn.execute((ROOT/"backend/migrations/000_baseline.sql").read_text())
            conn.execute("RESET ALL")
            conn.execute("SET search_path=public")
            conn.execute("INSERT INTO business_processes(id,name,description,sort_order) VALUES('old-process','旧流程','合成历史数据',0)")
            conn.execute("INSERT INTO knowledge_categories(id,name) VALUES('old-category','旧目录')")
            conn.execute("INSERT INTO knowledge_categories(id,parent_id,name) VALUES('old-child','old-category','子目录')")
            conn.execute("""INSERT INTO process_steps(process_id,id,name,objective,knowledge_scopes,sort_order)
                            VALUES('old-process','old-step','旧步骤','合成目标','["旧目录"]',0)""")
            conn.execute("""INSERT INTO knowledge_purposes(id,name,description,can_generate_template,chunk_body,inherit_chunking,chunk_settings,sort_order)
                         VALUES('old-purpose','旧用途','合成历史用途',false,true,true,'{}',0)""")
            conn.execute("""INSERT INTO knowledge_documents(id,title,category_id,original_name,original_path,mime_type,status,parsed_text,chunk_settings,purpose_id)
                         VALUES('old-doc','旧资料','old-child','old.txt','/synthetic/old.txt','text/plain','effective','synthetic','{}','old-purpose')""")
            conn.execute("""INSERT INTO knowledge_chunks(id,document_id,chunk_index,content,token_count)
                            VALUES('old-parent','old-doc',0,'synthetic-parent',1)""")
            conn.execute("""INSERT INTO knowledge_chunks(id,document_id,parent_chunk_id,chunk_index,content,token_count)
                            VALUES('old-chunk','old-doc','old-parent',1,'synthetic-child',1)""")
            vector="["+",".join(["0.25"]*1024)+"]"
            conn.execute("UPDATE knowledge_documents SET document_embedding=%s,embedding_model='synthetic-model'",(vector,))
            conn.execute("UPDATE knowledge_chunks SET embedding=%s,embedding_model='synthetic-model'",(vector,))
            conn.commit()
            # Inventory is genuinely read-only; no bodies/vectors/credential fields enter its output.
            with tempfile.TemporaryDirectory() as folder, conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                root=Path(folder)
                ordinary=root/"synthetic.txt";ordinary.write_text("synthetic")
                link=root/"link.txt";link.symlink_to(ordinary)
                assert file_metadata(str(ordinary),root)=={"state":"present","bytes":9}
                assert file_metadata(str(link),root)["state"]=="symlink"
                assert file_metadata(str(root/"missing.txt"),root)["state"]=="missing"
                assert file_metadata("relative.txt",root)["state"]=="non_absolute"
                report=collect(conn,Path(folder),Path(folder))
                encoded=json.dumps(report,default=str)
                assert "synthetic-parent" not in encoded and "parsed_text" not in encoded and "0.25" not in encoded
                assert report["documents"][0]["target_space"] is None
                try:
                    with conn.transaction():conn.execute("DELETE FROM knowledge_documents")
                except psycopg.errors.ReadOnlySqlTransaction:pass
                else:raise AssertionError("read-only inventory transaction allowed a mutation")
            conn.commit()
            # Inject an interruption after DDL: the outer transaction must restore the legacy schema.
            try:
                with conn.transaction():
                    migrate(conn)
                    raise RuntimeError("synthetic migration interruption")
            except RuntimeError as error:
                assert str(error)=="synthetic migration interruption"
            assert conn.execute("SELECT to_regclass('public.users') AS present").fetchone()["present"] is None
            assert conn.execute("SELECT to_regclass('public.schema_migrations') AS present").fetchone()["present"] is None
            conn.commit()
            migrate(conn)
            migrate(conn)
            assert conn.execute("SELECT space_id FROM knowledge_documents WHERE id='old-doc'").fetchone()["space_id"]=="legacy"
            assert conn.execute("SELECT space_id FROM business_processes WHERE id='old-process'").fetchone()["space_id"]=="legacy"
            assert conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"]==5
            assert conn.execute("SELECT count(*) AS n FROM knowledge_purposes WHERE space_id='shared'").fetchone()["n"]==3
            assert conn.execute("SELECT original_path FROM knowledge_documents WHERE id='old-doc'").fetchone()["original_path"]=="/synthetic/old.txt"
            assert conn.execute("SELECT document_embedding::text AS v FROM knowledge_documents WHERE id='old-doc'").fetchone()["v"]==vector
            assert conn.execute("SELECT count(*) AS n FROM knowledge_chunks WHERE embedding=%s::vector AND space_id='legacy'",(vector,)).fetchone()["n"]==2
            assert conn.execute("SELECT parent_chunk_id FROM knowledge_chunks WHERE id='old-chunk'").fetchone()["parent_chunk_id"]=="old-parent"
            assert conn.execute("SELECT parent_id FROM knowledge_categories WHERE id='old-child'").fetchone()["parent_id"]=="old-category"
            assert conn.execute("SELECT process_id,space_id FROM process_steps WHERE id='old-step'").fetchone()=={"process_id":"old-process","space_id":"legacy"}
            for table,id in (("knowledge_documents","old-doc"),("knowledge_categories","old-child"),("process_steps","old-step")):
                try:
                    with conn.transaction():
                        conn.execute(sql.SQL("UPDATE {} SET space_id='zkxk' WHERE id=%s").format(sql.Identifier(table)),(id,))
                except psycopg.errors.ForeignKeyViolation:pass
                else:raise AssertionError("cross-space relation was accepted")
            conn.execute("GRANT USAGE ON SCHEMA public TO department_app")
            conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO department_app")
            for space in ("zkxk","senyuan","shared"):
                with conn.transaction():
                    conn.execute("SET LOCAL ROLE department_app")
                    conn.execute("SELECT set_config('department.space',%s,true)",(space,))
                    assert conn.execute("SELECT count(*) AS n FROM knowledge_documents").fetchone()["n"]==0
                    assert conn.execute("SELECT count(*) AS n FROM business_processes").fetchone()["n"]==0
                    conn.execute("RESET ROLE")
            print("identity-migration-check: read-only inventory, interrupted DDL rollback, repeat migration, original IDs/files/vectors, FK and company quarantine passed")
    finally:
        manager.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
