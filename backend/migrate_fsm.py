import asyncio
import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "dropship.db")

async def migrate():
    print(f"Migrating {DB_PATH} FSM values...")
    if not os.path.exists(DB_PATH):
        print("Database not found. Skipping migration.")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        # Check if table exists
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'") as cur:
            if not await cur.fetchone():
                print("Table 'products' does not exist yet. Skipping.")
                return

        # Perform the mapping
        await db.execute("""
            UPDATE products
            SET stage = CASE stage
                WHEN 'pending' THEN 'SCRAPED'
                WHEN 'text_edit' THEN 'ENRICHED'
                WHEN 'approved' THEN 'REVIEWED'
                WHEN 'posted' THEN 'LIVE'
                WHEN 'rejected' THEN 'REJECTED'
                ELSE stage
            END
            WHERE stage IN ('pending', 'text_edit', 'approved', 'posted', 'rejected')
        """)
        
        updated_count = db.total_changes
        await db.commit()
        print(f"Migration complete. Updated {updated_count} rows.")

if __name__ == "__main__":
    asyncio.run(migrate())
