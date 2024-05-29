import uvicorn
import os
from fastapi import FastAPI
from app.websocket import websocket_endpoint

app = FastAPI()

app.add_websocket_route("/ws", websocket_endpoint)

@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
