import re

content = open('backend/database.py', 'r', encoding='utf-8').read()

# Replace all remaining self._db.execute / fetch / fetchrow / fetchval
# with the pool-backed helpers (await self.execute / fetch / etc.)
replacements = [
    ('await self._db.execute(', 'await self.execute('),
    ('await self._db.fetch(', 'await self.fetch('),
    ('await self._db.fetchrow(', 'await self.fetchrow('),
    ('await self._db.fetchval(', 'await self.fetchval('),
    # non-awaited variants (used as the result of execute for row count)
    ('self._db.execute(', 'await self.execute('),
    ('self._db.fetch(', 'await self.fetch('),
    ('self._db.fetchrow(', 'await self.fetchrow('),
    ('self._db.fetchval(', 'await self.fetchval('),
]

count = 0
for old, new in replacements:
    n = content.count(old)
    if n:
        print(f'Replacing {n}x  {old!r}')
        content = content.replace(old, new)
        count += n

open('backend/database.py', 'w', encoding='utf-8').write(content)
print(f'\nDone — {count} replacements total')
remaining = content.count('self._db')
print(f'Remaining self._db references: {remaining}')
