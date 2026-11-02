"""Reviewed skills are visible only after the database publication commits."""
import base64
from app.core.database import ConflictError
from .service import list_skills


def lock_skills(conn):
    # Serialize legacy file mutations with DB publication within this space.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('skills:'||current_setting('department.space'),0))")


def publication(pool, skill_id):
    with pool.connection() as conn:
        return conn.execute("SELECT * FROM skill_publications WHERE id=%s", (skill_id,)).fetchone()


def list_available_skills(pool, root):
    result = list_skills(root)
    with pool.connection() as conn:
        rows = conn.execute("SELECT * FROM skill_publications ORDER BY updated_at DESC").fetchall()
    published_ids = {row["id"] for row in rows}
    result = [item for item in result if item["id"] not in published_ids]
    for row in rows:
        data = row["data"]
        resources = [{"path": r["path"], "name": r["path"].split("/")[-1],
                      "kind": r["path"].split("/")[0], "size": len(base64.b64decode(r["contentBase64"])),
                      "updatedAt": row["updated_at"].isoformat()} for r in data.get("resources", [])]
        result.append({**data["skill"], "id": row["id"], "enabled": row["enabled"], "valid": True, "error": "",
                       "reviewPublished": True, "resources": resources,
                       "resourceCounts": {k: sum(r["kind"]==k for r in resources) for k in ("scripts","references","assets")},
                       "updatedAt": row["updated_at"].isoformat()})
    return sorted(result,key=lambda s:s["updatedAt"],reverse=True)


def require_file_skill(pool, name):
    if publication(pool, name):
        raise ConflictError("此技能来自审核发布，请通过修改稿提交审核；不能直接覆盖正式版本")
