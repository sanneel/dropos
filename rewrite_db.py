import re

def convert_query_params(match):
    query = match.group(0)
    counter = 1
    while '?' in query:
        query = query.replace('?', f'${counter}', 1)
        counter += 1
    return query

def main():
    with open('backend/database.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Imports
    content = content.replace('import aiosqlite', 'import asyncpg\nimport urllib.parse')
    content = content.replace('Optional[aiosqlite.Connection]', 'Optional[asyncpg.Connection]')

    # 2. Connect
    old_connect = '''    async def connect(self):
        self._db = await aiosqlite.connect(DB_PATH)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA synchronous=NORMAL;")'''
    new_connect = '''    async def connect(self):
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL is not set")
        self._db = await asyncpg.connect(db_url)'''
    content = content.replace(old_connect, new_connect)
    
    # Also replace init_db pragmas
    content = re.sub(r'    await conn.execute\("PRAGMA journal_mode=WAL"\)\n', '', content)
    content = re.sub(r'    await conn.execute\("PRAGMA synchronous=NORMAL"\)\n', '', content)
    content = re.sub(r'    await conn.execute\("PRAGMA cache_size=-64000"\)\n', '', content)

    # 3. Table creation definitions
    content = content.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
    content = content.replace('REAL', 'DOUBLE PRECISION')
    # PostgreSQL doesn't like '' for REAL/INTEGER, so we just use DEFAULT 0 or drop DEFAULT ''
    # Actually, REAL DEFAULT 0 is fine, TEXT DEFAULT '' is fine.
    # INTEGER DEFAULT 0 is fine.
    content = content.replace('INSERT OR IGNORE INTO', 'INSERT INTO')
    # Wait, INSERT OR IGNORE INTO needs ON CONFLICT DO NOTHING
    # It's better to just manually patch those specific queries using regex.

    # 4. execute(query, (args,)) -> execute(query, *args)
    # This is tricky with regex. Instead of regex, I'll provide a fixed `database.py` 
    # file directly via a python string literal because I understand the logic.
    pass

if __name__ == "__main__":
    main()
