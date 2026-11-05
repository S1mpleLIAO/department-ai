from psycopg.types.json import Jsonb
from .store import DEFAULT_PURPOSES


def seed_purposes(conn, space):
    conn.execute("SELECT set_config('department.space',%s,true)", (space,))
    for index,p in enumerate(DEFAULT_PURPOSES):
        conn.execute("""INSERT INTO knowledge_purposes(space_id,id,name,description,can_generate_template,
                        chunk_body,inherit_chunking,chunk_settings,sort_order)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                     (space,p["id"],p["name"],p["description"],p["canGenerateTemplate"],
                      p["chunkBody"],p["inheritChunking"],Jsonb(p["chunkSettings"]),index*10))
