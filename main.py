import asyncio
import os
import json
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from databases import Database
from dotenv import load_dotenv
from web3 import Web3
from web3.exceptions import TimeExhausted
import psycopg2

load_dotenv()

app = FastAPI()

# Database connection
db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASSWORD")
db_host = os.getenv("DB_HOST")
db_name = os.getenv("DB_NAME")
db_port = os.getenv("DB_PORT")

DATABASE_URL = f"postgresql://{db_user}:{db_password}@{db_host}/{db_name}"
database = Database(DATABASE_URL)


def serialize_record(record):
    return {
        **record,
        "timestamp": (
            record["timestamp"].isoformat() if record.get("timestamp") else None
        ),
    }


@app.on_event("startup")
async def startup():
    await database.connect()
    asyncio.create_task(log_loop(start_block=14878994))  # Adjust the starting block


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    last_race_id = 0  # Adjusted to track the last race_id sent
    try:
        # First, send all existing data
        initial_query = "SELECT * FROM race_results ORDER BY race_id;"
        initial_results = await database.fetch_all(initial_query)
        if initial_results:
            last_race_id = initial_results[-1]["race_id"]
            await websocket.send_json(
                {"data": [serialize_record(dict(result)) for result in initial_results]}
            )

        # Then, only new updates
        while True:
            update_query = f"SELECT * FROM race_results WHERE race_id > {last_race_id} ORDER BY race_id;"
            new_results = await database.fetch_all(update_query)
            if new_results:
                last_race_id = new_results[-1]["race_id"]
                await websocket.send_json(
                    {"data": [serialize_record(dict(result)) for result in new_results]}
                )
                print(f"Sent new data: {new_results}")

            await asyncio.sleep(10)  # Check for new updates every 10 seconds
    except WebSocketDisconnect:
        print("Client disconnected")


# Web3 setup
web3 = Web3(Web3.WebsocketProvider(os.getenv("BASE_URL")))
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

# Instantiate the contract
contract = web3.eth.contract(address=contract_address, abi=abi)


def save_to_database(event_data):
    with psycopg2.connect(
        dbname=db_name, user=db_user, password=db_password, host=db_host, port=db_port
    ) as conn:
        with conn.cursor() as cur:
            query = """
            INSERT INTO race_results (race_id, winner_address, winning_token_id, steps, commitment_hashes)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (race_id) DO NOTHING
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
    if to_block is None:
        to_block = web3.eth.block_number

    current_block = from_block
    while current_block < to_block:
        end_block = min(current_block + batch_size, to_block)
        print(f"Fetching from {current_block} to {end_block}")
        try:
            fetch_events(current_block, end_block)
            current_block = end_block + 1
        except TimeExhausted:
            print(f"Timeout fetching between blocks {current_block} and {end_block}")
        except Exception as e:
            print(f"An error occurred: {e}")

    return current_block


def fetch_events(from_block, to_block):
    try:
        event_filter = contract.events.RaceFinished.create_filter(
            fromBlock=from_block, toBlock=to_block
        )
        events = event_filter.get_all_entries()
        for event in events:
            print_event_data(event)
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


# Function to handle new event data
def handle_event(event):
    print_event_data(event)
    save_to_database(event["args"])


# Subscribe to the event and fetch new events in batches since the last block
async def log_loop(start_block):
    latest_block = web3.eth.block_number
    while True:
        try:
            # Fetch events in batches since the last fetched block
            start_block = fetch_events_in_batches(start_block, latest_block)

            # Update latest_block to the current block number
            latest_block = web3.eth.block_number

            # Create a new event filter from the latest block
            event_filter = contract.events.RaceFinished.create_filter(
                fromBlock=latest_block
            )

            # Poll for new events
            new_entries = event_filter.get_new_entries()
            for event in new_entries:
                handle_event(event)

            await asyncio.sleep(10)  # Wait before polling again
        except Exception as e:
            print(f"An error occurred: {str(e)}")
            await asyncio.sleep(10)  # Wait before trying again


# Start block for fetching events
# start_block = 14820784
start_block = 14888483
start_block = fetch_events_in_batches(start_block)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
