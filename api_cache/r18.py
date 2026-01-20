import hashlib
import requests
import psycopg
import os
import dotenv

dotenv.load_dotenv("E:/DB/.env")

 
DB_URL = os.getenv("PG_URL")


session = requests.Session()


def get_id_all():
    """获取所有缓存的id"""
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT query_json->>'id' FROM r18_cache")
            rows = cur.fetchall()
            return [row[0] for row in rows]



def cache_query(id: str):

    query_hash = hashlib.sha256(id.encode()).hexdigest()

    try:
        data = r18dev(id)
        # 缓存查询结果

    except aiohttp.ClientError as e:
        print(e)
        return {"error": "id not found"}


def r18dev(id: str):
    """查询r18.dev"""

    content_id = id

    if "-" in id:
        url = f"https://r18.dev/videos/vod/movies/detail/-/dvd_id={id}/json"
        resp = session.get(url)
        data = resp.json()
        content_id = data["content_id"]

    url = f"https://r18.dev/videos/vod/movies/detail/-/combined={content_id}/json"
    resp = session.get(url)
    data = resp.json()
    return data


def main():
    ids = get_id_all()
    for id in ids:
        cache_query(id)


if __name__ == "__main__":
    main()
