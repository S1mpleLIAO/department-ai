"""Read-only legacy ownership inventory. Never extracts bodies, embeddings or secrets."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat

from dotenv import dotenv_values
import psycopg
from psycopg.rows import dict_row


def file_metadata(raw, root):
    path=Path(raw)
    if not path.is_absolute():
        return {"state":"non_absolute"}
    resolved=path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        return {"state":"outside_data_root"}
    if resolved!=path:
        return {"state":"symlink"}
    try:info=path.stat()
    except FileNotFoundError:return {"state":"missing"}
    except OSError:return {"state":"unreadable"}
    if not stat.S_ISREG(info.st_mode):return {"state":"not_regular"}
    return {"state":"present","bytes":info.st_size}


def collect(conn, data_root, skill_root):
    if conn.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"]!="on":
        raise RuntimeError("Inventory requires a read-only transaction")
    if conn.execute("SELECT to_regclass('public.spaces') AS present").fetchone()["present"]:
        raise RuntimeError("This inventory expects the legacy schema, not an already migrated database")
    categories=conn.execute("SELECT id,parent_id,name,sort_order FROM knowledge_categories ORDER BY sort_order,id").fetchall()
    processes=conn.execute("SELECT id,name,updated_at FROM business_processes ORDER BY sort_order,id").fetchall()
    steps=conn.execute("SELECT process_id,id,name,knowledge_scopes FROM process_steps ORDER BY process_id,sort_order,id").fetchall()
    purposes=conn.execute("SELECT id,name,can_generate_template,chunk_body FROM knowledge_purposes ORDER BY sort_order,id").fetchall()
    documents=conn.execute("""SELECT d.id,d.title,d.category_id,d.purpose_id,d.status,d.original_name,d.original_path,
        d.applicable_process_id,d.applicable_step_id,d.updated_at,
        (d.document_embedding IS NOT NULL) AS document_indexed,
        (SELECT count(*) FROM knowledge_chunks c WHERE c.document_id=d.id) AS chunk_count,
        (SELECT count(*) FROM knowledge_chunks c WHERE c.document_id=d.id AND c.embedding IS NOT NULL) AS indexed_chunks
        FROM knowledge_documents d ORDER BY d.created_at,d.id""").fetchall()
    for document in documents:
        document["source"]=file_metadata(document.pop("original_path"),data_root)
        document["target_space"]=None
    for item in categories+processes:item["target_space"]=None
    skills=[]
    # Enumerate direct skill folders only. No recursive content/binary/archive processing.
    if skill_root.is_dir():
        for folder in sorted(skill_root.iterdir()):
            if folder.name.startswith("."):continue
            if folder.is_symlink():
                skills.append({"id":folder.name,"state":"symlink_not_followed","target_space":None})
            elif folder.is_dir() and (folder/"SKILL.md").exists():
                skills.append({"id":folder.name,"state":"file_skill","target_space":None})
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"read_only":True,
            "categories":categories,"processes":processes,"steps":steps,"purposes":purposes,
            "documents":documents,"skills":skills,
            "notes":["target_space 留空表示尚未确认，不自动分配公司或共享。",
                     "知识分块和向量仅计数，没有导出正文、向量、技能内容或凭据。",
                     "技能只盘点直接目录；原 Harness 会话归属没有推断或读取。"]}


def review_text(report):
    lines=["历史资料归属确认清单", "", "待确认值：中科信控 / 森远股份 / 部门共享 / 暂不分配。",
           "尚未执行归属修改；普通成员不会自动获得历史资料访问权。", ""]
    names={x["id"]:x["name"] for x in report["categories"]}
    for heading,key,label in (("知识目录","categories","name"),("业务流程","processes","name"),
                              ("知识文档","documents","title"),("技能","skills","id")):
        lines.append(heading+"（"+str(len(report[key]))+"项）")
        for x in report[key]:
            detail=""
            if key=="categories":detail="；上级："+names.get(x["parent_id"],"根目录")
            if key=="documents":detail="；目录："+names.get(x["category_id"],"未分类")+"；状态："+x["status"]+"；原文："+x["source"]["state"]
            lines.append("- "+str(x[label]).replace("\n"," ")+" ["+x["id"]+"]"+detail+" → 待确认")
        lines.append("")
    return "\n".join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    source=Path(args.env_file).resolve(strict=True)
    values=dotenv_values(source,interpolate=False)
    dsn=values.get("DEPARTMENT_DATABASE_URL")
    if not dsn:raise SystemExit("Explicit source environment has no database URL")
    data_root=Path(values.get("DEPARTMENT_DATA_DIR") or source.parent/"runtime-data/department-ai-python")
    skill_root=Path(values.get("DEPARTMENT_SKILL_DIR") or source.parent/"runtime-data/department-skills")
    output=Path(args.output)
    output.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    try:
        with psycopg.connect(dsn,row_factory=dict_row,connect_timeout=5,
             options="-c default_transaction_read_only=on -c statement_timeout=10000 -c lock_timeout=1000") as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            report=collect(conn,data_root,skill_root)
        for path,body in ((output,json.dumps(report,ensure_ascii=False,indent=2,default=str)),
                          (output.with_suffix(".txt"),review_text(report))):
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,"w") as stream:stream.write(body)
    except psycopg.Error:
        raise SystemExit("Read-only inventory failed; no source data changed. Connection details suppressed.")
    print(json.dumps({"read_only":True,"counts":{k:len(report[k]) for k in
                     ("categories","processes","steps","documents","skills")},"output":str(output)},ensure_ascii=False))


if __name__=="__main__":main()
