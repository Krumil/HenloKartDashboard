import json
import os
import time
from web3 import Web3
from web3.exceptions import TimeExhausted
from web3.middleware import geth_poa_middleware
from dotenv import load_dotenv
import psycopg2

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
conn.autocommit = True  # Ensure data is committed to the database immediately after the command is executed
# Setup Web3 connection
web3 = Web3(
    Web3.WebsocketProvider(os.getenv("BASE_URL"), websocket_timeout=60)
)  # Increase timeout to 60 seconds
if web3.is_connected():
    print("Connected to Base network successfully.")
else:
    print("Failed to connect to the Base network.")
    exit(1)  # Exit if there is no connection to avoid further errors

# Load the contract ABI
abi_path = "abi.json"
with open(abi_path, "r") as f:
    abi = json.load(f)

# Contract address
contract_address = Web3.to_checksum_address(
    "0x5f6687b70f7a6029dd37480592da84d465d8cbb7"
)

# Create the contract instance with the newly-deployed address and abi
contract = web3.eth.contract(address=contract_address, abi=abi)


def save_to_database(event_data):
    with conn.cursor() as cur:
        query = """
        INSERT INTO race_results (race_id, winner_address, winning_token_id, steps, commitment_hashes)
        VALUES (%s, %s, %s, %s, %s)
        """
        values = (
            event_data["raceId"],
            event_data["winner"],
            event_data["winningTokenId"],
            event_data["steps"],
            event_data["commitmentHashes"],
        )
        cur.execute(query, values)


def fetch_events_in_batches(from_block, to_block=None, batch_size=1000):
    # Get the latest block number if to_block is not specified
    if to_block is None:
        to_block = web3.eth.block_number

    current_block = from_block
    while current_block < to_block:
        end_block = min(current_block + batch_size, to_block)
        print(f"Fetching from {current_block} to {end_block}")
        try:
            fetch_events(current_block, end_block)
        except TimeExhausted:
            print(f"Timeout fetching between blocks {current_block} and {end_block}")
        except Exception as e:
            print(f"An error occurred: {e}")
        current_block = end_block + 1


def fetch_events(from_block, to_block):
    try:
        event_filter = contract.events.RaceFinished.create_filter(
            fromBlock=from_block, toBlock=to_block
        )
        events = event_filter.get_all_entries()
        for event in events:
            print_event_data(event)
            save_event_data_to_file(event)
            save_to_database(event["args"])
    except Exception as e:
        print(f"Error fetching events: {str(e)}")


def print_event_data(event):
    print(
        {
            "race_id": event["args"]["raceId"],
            "winner": event["args"]["winner"],
            "winning_token_id": event["args"]["winningTokenId"],
            "steps": event["args"]["steps"],
            "bet_size": event["args"]["betSize"],
            "bet_token": event["args"]["betToken"],
            "executor": event["args"]["executor"],
            "commitment_hashes": [
                hash.hex() for hash in event["args"]["commitmentHashes"]
            ],
        }
    )


def save_event_data_to_file(event):
    with open("log.txt", "a") as log_file:
        log_file.write(
            f"Race ID: {event['args']['raceId']}\nWinner: {event['args']['winner']}\nWinning Token ID: {event['args']['winningTokenId']}\nSteps: {event['args']['steps']}\nCommitment Hashes: {event['args']['commitmentHashes']}\n\n"
        )


# Example Usage: Adjust the starting block as needed.
fetch_events_in_batches(
    14820784
)  # 'latest' is now dynamically set to the current block number
