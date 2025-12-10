"""
Simple example to test local SQL tools without Azure.

Tests the LocalSQLTools class directly with a local .db file.
"""

import asyncio
import logging
import os
from pathlib import Path

from agent_framework.tools import LocalSQLTools

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    """Test local SQL tools"""
    
    logger.info("=" * 80)
    logger.info("Local SQL Tools Test")
    logger.info("=" * 80)
    
    # Path to test database (you can create one or use existing)
    db_path = Path(__file__).parent.parent.parent.parent.parent / "data" / "test.db"
    
    if not db_path.exists():
        logger.warning(f"Database not found at {db_path}")
        logger.info("Creating sample database for testing...")
        
        # Create sample database
        import sqlite3
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Create sample table
        cursor.execute("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE,
                total_purchases REAL
            )
        """)
        
        # Insert sample data
        cursor.executemany("""
            INSERT INTO customers (name, email, total_purchases)
            VALUES (?, ?, ?)
        """, [
            ("Alice Johnson", "alice@example.com", 1250.50),
            ("Bob Smith", "bob@example.com", 890.25),
            ("Carol White", "carol@example.com", 2340.75),
            ("David Brown", "david@example.com", 567.00),
            ("Eve Davis", "eve@example.com", 3420.10),
        ])
        
        conn.commit()
        conn.close()
        
        logger.info(f"✓ Created sample database at {db_path}")
    
    # ====================================================================================
    # Test 1: Initialize LocalSQLTools
    # ====================================================================================
    
    logger.info("\n[TEST 1] Initializing LocalSQLTools...")
    
    tools = LocalSQLTools(str(db_path))
    
    logger.info(f"✓ Initialized with database: {db_path}")
    logger.info(f"✓ Database type: {tools.db_type}")
    
    # ====================================================================================
    # Test 2: List tables
    # ====================================================================================
    
    logger.info("\n[TEST 2] Listing tables...")
    
    result = await tools.list_tables()
    logger.info(f"\n{result}")
    
    # ====================================================================================
    # Test 3: Get database schema
    # ====================================================================================

    logger.info("\n[TEST 3] Getting database schema...")

    result = await tools.get_database_schema(database=str(db_path))
    logger.info(f"\n{result}")

    # ====================================================================================
    # Test 4: Describe specific table
    # ====================================================================================

    logger.info("\n[TEST 4] Describing 'customers' table...")

    result = await tools.describe_table("customers")
    logger.info(f"\n{result}")

    # ====================================================================================
    # Test 5: Execute SELECT query
    # ====================================================================================

    logger.info("\n[TEST 5] Executing SELECT query...")

    query = "SELECT * FROM customers WHERE total_purchases > 1000 ORDER BY total_purchases DESC"

    result = await tools.execute_sql_query(query, database=str(db_path))
    logger.info(f"\n{result}")

    # ====================================================================================
    # Test 6: Execute aggregate query
    # ====================================================================================

    logger.info("\n[TEST 6] Executing aggregate query...")

    query = """
        SELECT
            COUNT(*) as total_customers,
            SUM(total_purchases) as total_revenue,
            AVG(total_purchases) as avg_purchase
        FROM customers
    """

    result = await tools.execute_sql_query(query, database=str(db_path))
    logger.info(f"\n{result}")
    
    logger.info("\n" + "=" * 80)
    logger.info("All tests complete!")
    logger.info("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
