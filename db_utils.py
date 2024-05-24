import psycopg2
import os
from psycopg2 import sql
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database connection
dbname = os.getenv("DB_NAME")
dbhost = os.getenv("DB_HOST")
user = os.getenv("DB_USER")
password = os.getenv("DB_PASSWORD")
port = os.getenv("DB_PORT")

conn = psycopg2.connect(
    dbname=dbname, user=user, password=password, host=dbhost, port=port
)
conn.autocommit = True

# Creating a cursor object using the cursor() method
cursor = conn.cursor()

# Preparing query to create a table
create_table_query = """
CREATE TABLE IF NOT EXISTS race_results (
	race_id BIGINT PRIMARY KEY,
    winner_address VARCHAR(255),
    winning_token_id BIGINT,
    steps INT,
    commitment_hashes TEXT[],
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Creating a table
cursor.execute(create_table_query)
print("Table created successfully in PostgreSQL ")

# Closing the connection
conn.close()
