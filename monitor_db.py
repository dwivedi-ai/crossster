# stereotype_quiz_app/monitor_db.py

import mysql.connector # Use MySQL connector
from mysql.connector import Error as MySQLError # Import specific error class
import os
import sys

# --- Configuration ---

# !! IMPORTANT !!
# These credentials MUST match the ones used in your app.py and your actual MySQL setup.
# Consider using environment variables or a config file in a real application
# instead of hardcoding them here and in app.py.
MYSQL_HOST = 'localhost'        # Or your MySQL server host
MYSQL_USER = 'stereotype_user'  # The user you created for the app
MYSQL_PASSWORD = 'RespAI@2025' # The password for the user (REPLACE THIS!)
MYSQL_DB = 'stereotype_quiz_db' # The database name used by the app
MYSQL_PORT = 3306               # Default MySQL port

TABLE_NAME = 'results'          # Table to query

# --- Optional: Use pandas for nicer table output ---
# If you want to use pandas, set to True and ensure pandas is installed (`pip install pandas`)
USE_PANDAS = False
# USE_PANDAS = True # Uncomment this line to try using Pandas

if USE_PANDAS:
    try:
        import pandas as pd
    except ImportError:
        print("Pandas library not found. Install it using: pip install pandas")
        print("Falling back to basic printing.")
        USE_PANDAS = False

# --- Ensure MySQL Connector is installed ---
try:
    import mysql.connector
except ImportError:
    print("Error: MySQL Connector not found.")
    print("Please install it using: pip install mysql-connector-python")
    sys.exit(1)

# --- Main Function ---
def view_data():
    """Connects to the MySQL database and prints the contents of the results table."""

    print(f"Attempting to connect to MySQL database '{MYSQL_DB}' on {MYSQL_HOST}...")

    conn = None # Initialize connection variable
    try:
        # Connect to the MySQL database
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DB,
            port=MYSQL_PORT
        )

        if conn.is_connected():
            print("Successfully connected to MySQL.")
            print(f"\n--- Data from table '{TABLE_NAME}' ---")

            if USE_PANDAS:
                # Use pandas to read and print the table
                try:
                    # Pass the MySQL connection object to pandas
                    df = pd.read_sql_query(f"SELECT * FROM {TABLE_NAME} ORDER BY timestamp DESC", conn)
                    if df.empty:
                        print("Table is empty.")
                    else:
                        # Configure pandas display options (optional)
                        pd.set_option('display.max_rows', None)
                        pd.set_option('display.max_columns', None)
                        pd.set_option('display.width', 1000)
                        # Convert DataFrame to string for printing all rows/cols
                        print(df.to_string(index=False))
                except pd.io.sql.DatabaseError as e:
                     print(f"Pandas Error reading table: {e}")
                     print(f"Check if table '{TABLE_NAME}' exists and connection details are correct.")
                except Exception as e:
                     print(f"An unexpected error occurred with pandas: {e}")

            else:
                # Basic printing without pandas
                # Use a dictionary cursor to access columns by name if needed,
                # but for basic printing, a standard cursor is fine.
                # cursor = conn.cursor(dictionary=True)
                cursor = conn.cursor()
                try:
                    cursor.execute(f"SELECT * FROM {TABLE_NAME} ORDER BY timestamp DESC") # Order results
                    rows = cursor.fetchall()

                    if not rows:
                        print("Table is empty.")
                    else:
                        # Print header (column names)
                        column_names = [desc[0] for desc in cursor.description]
                        print("\t|\t".join(column_names)) # Use pipe for clarity
                        # Calculate separator length based on header
                        separator_length = sum(len(name) + 3 for name in column_names) - 3
                        print("-" * separator_length)

                        # Print each row
                        for row in rows:
                            # Convert all items to string, handle None gracefully
                            print("\t|\t".join(map(lambda x: str(x) if x is not None else 'NULL', row)))

                except MySQLError as e:
                     print(f"MySQL Error executing query: {e}")
                     print(f"Check if table '{TABLE_NAME}' exists and has the expected columns.")
                finally:
                     if cursor:
                         cursor.close() # Close the cursor

        else:
            print("MySQL connection failed (is_connected() returned False).")
            # This case might not be reached if connect() throws an error first

    except MySQLError as e:
        print(f"MySQL Connection Error: {e}")
        print("Please check:")
        print(f" - Is the MySQL server running on {MYSQL_HOST}:{MYSQL_PORT}?")
        print(f" - Are the username ('{MYSQL_USER}') and password correct?")
        print(f" - Does the database '{MYSQL_DB}' exist?")
        print(f" - Does the user '{MYSQL_USER}' have privileges on '{MYSQL_DB}'?")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()
            print("\n--- MySQL connection closed ---")

# --- Run the function ---
if __name__ == "__main__":
    # Add a quick check for the password placeholder
    if MYSQL_PASSWORD == 'RespAI@2025':
        print("\n*** WARNING: Default MySQL password detected in script! ***")
        print("*** Please update MYSQL_PASSWORD in monitor_db.py with your actual password. ***\n")
    view_data()