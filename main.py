from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from databases import Database
from dotenv import load_dotenv
import os
import asyncio

load_dotenv()

app = FastAPI()

# Database connection
db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASSWORD")
db_host = os.getenv("DB_HOST")
db_name = os.getenv("DB_NAME")


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
