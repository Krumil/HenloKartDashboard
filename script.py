import psycopg2
import re
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database connection parameters
conn_params = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
}


def parse_and_insert_data(filename):
    # Connect to the database
    conn = psycopg2.connect(**conn_params)
    cursor = conn.cursor()

    # Regex pattern to capture relevant data
    pattern = re.compile(
        r"Race ID: (\d+)\nWinner: (.+?)\nWinning Token ID: (\d+)\nSteps: (\d+)\nCommitment Hashes: \[(.+?)\]",
        re.DOTALL,
    )

    # Read the file
    with open(filename, "r") as file:
        file_content = file.read()

    # Find all matches
    matches = pattern.findall(file_content)

    # SQL query for inserting data
    insert_query = """
    INSERT INTO race_results (race_id, winner_address, winning_token_id, steps, commitment_hashes)
    VALUES (%s, %s, %s, %s, %s);
    """

    # Iterate over matches and insert data into the database
    for match in matches:
        race_id, winner, token_id, steps, hashes = match
        # Process the commitment hashes string into a list of bytea
        # Correctly extract and convert byte strings
        hashes = [
            bytes.fromhex(h.strip("b'").rstrip("'").encode().hex())
            for h in hashes.split(",")
        ]
        data = (race_id, winner, token_id, steps, hashes)
        cursor.execute(insert_query, data)

    # Commit changes and close connection
    conn.commit()
    cursor.close()
    conn.close()
    print("Data inserted successfully.")


# Specify your file path
file_path = "log.txt"
parse_and_insert_data(file_path)
