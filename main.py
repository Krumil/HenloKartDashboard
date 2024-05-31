import asyncio
import uvicorn
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.db import database
from utils.helpers import serialize_record

origins = [
    "http://localhost",
    "http://localhost:3000",
]

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def startup_tasks():
    await database.connect()


@app.on_event("startup")
async def startup():
    asyncio.create_task(startup_tasks())


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


@app.get("/api/stats/tokens")
async def get_all_token_stats():
    query = """
    SELECT
        token_id,
        COUNT(*) as total_races,
        SUM(CASE WHEN winning_token_id = token_id THEN 1 ELSE 0 END) as total_wins,
        SUM(bet_size) as total_bet_won
    FROM race_results, unnest(participant_token_ids) as token_id
    GROUP BY token_id
    ORDER BY token_id;
    """
    results = await database.fetch_all(query)
    # {"data": [serialize_record(dict(result)) for result in new_results]}
    return {"data": [serialize_record(dict(result)) for result in results]}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    # uvicorn.run(app, host="0.0.0.0", port=port)
    uvicorn.run(app, host="localhost", port=port)
