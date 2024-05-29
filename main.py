import asyncio
import uvicorn
import os
from fastapi import FastAPI
from app.websocket import websocket_endpoint
from config.db import database

app = FastAPI()

app.add_websocket_route("/ws", websocket_endpoint)


async def startup_tasks():
    await database.connect()


@app.on_event("startup")
async def startup():
    asyncio.create_task(startup_tasks())


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
