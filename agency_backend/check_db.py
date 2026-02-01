
import asyncio
import logging
from app.db.postgres import get_db_pool
from app.config import Config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_schema():
    print("Checking database schema...")
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Check if table exists
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'scheduled_follow_ups'
                );
            """)
            print(f"Table 'scheduled_follow_ups' exists: {table_exists}")
            
            if not table_exists:
                return

            # Check constraints/indexes
            indexes = await conn.fetch("""
                SELECT indexname, indexdef 
                FROM pg_indexes 
                WHERE tablename = 'scheduled_follow_ups';
            """)
            print("\nIndexes on 'scheduled_follow_ups':")
            for idx in indexes:
                print(f"- {idx['indexname']}: {idx['indexdef']}")
                
            # Check row count
            count = await conn.fetchval("SELECT COUNT(*) FROM scheduled_follow_ups")
            print(f"\nRow count in 'scheduled_follow_ups': {count}")
            
            # Check manual insertion test to see if it fails
            print("\nAttempting dry-run insertion:")
            try:
                # We use a non-existent call_id for safety, rollback transaction
                async with conn.transaction():
                    await conn.execute("""
                        INSERT INTO scheduled_follow_ups 
                        (call_id, phone_number, client_name, scheduled_at, status)
                        VALUES ('test_check_script', '+1234567890', 'Test', NOW(), 'pending')
                        ON CONFLICT (call_id) WHERE status IN ('pending', 'processing')
                        DO NOTHING
                    """)
                    print("Insertion test SUCCESS (Rolled back automatically due to script end or explicit rollback needed, but here we just wanted to see if it errors)")
                    raise Exception("RollbackTest") # Force rollback
            except Exception as e:
                if str(e) == "RollbackTest":
                    print("Test transaction rolled back successfully.")
                else:
                    print(f"Insertion test FAILED: {e}")

    except Exception as e:
        print(f"Error connecting or checking: {e}")
    finally:
        # We need to close the pool properly if we can, but script exit handles it
        pass

if __name__ == "__main__":
    asyncio.run(check_schema())
