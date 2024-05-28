import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from config.db import database
from utils.helpers import serialize_record


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
