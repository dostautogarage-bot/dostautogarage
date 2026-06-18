import sqlite3
import os

# Get the database path
db_path = 'db.sqlite3'

if not os.path.exists(db_path):
    print(f"Database file not found: {db_path}")
    exit(1)

# Connect to the database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Check if is_custom column exists
    cursor.execute("PRAGMA table_info(billing_invoiceitem)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'is_custom' not in columns:
        print("Adding is_custom column...")
        cursor.execute("ALTER TABLE billing_invoiceitem ADD COLUMN is_custom INTEGER NOT NULL DEFAULT 0")
        conn.commit()
        print("[OK] is_custom column added successfully")
    else:
        print("[OK] is_custom column already exists")
    
    # Check if custom_product_name column exists
    cursor.execute("PRAGMA table_info(billing_invoiceitem)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'custom_product_name' not in columns:
        print("Adding custom_product_name column...")
        cursor.execute("ALTER TABLE billing_invoiceitem ADD COLUMN custom_product_name VARCHAR(255) NULL")
        conn.commit()
        print("[OK] custom_product_name column added successfully")
    else:
        print("[OK] custom_product_name column already exists")
    
    # Make product_id nullable if it isn't already
    print("\nChecking product_id column...")
    cursor.execute("PRAGMA table_info(billing_invoiceitem)")
    columns = cursor.fetchall()
    product_col = [col for col in columns if col[1] == 'product_id']
    
    if product_col and product_col[0][3] == 1:  # NOT NULL constraint
        print("Note: product_id column has NOT NULL constraint. This needs to be removed manually.")
        print("You may need to recreate the table or use a migration to make it nullable.")
    else:
        print("[OK] product_id column is already nullable or doesn't have NOT NULL constraint")
    
    print("\n[SUCCESS] Database schema updated successfully!")
    
except sqlite3.Error as e:
    print(f"❌ Error: {e}")
    conn.rollback()
finally:
    conn.close()

# Made with Bob
