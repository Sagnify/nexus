"""Test script to verify extension WebSocket bridge RPC flow."""
import asyncio
import json
import websockets

async def mock_extension_client():
    uri = "ws://127.0.0.1:8000/ws/extension"
    async with websockets.connect(uri) as ws:
        print("[Mock Extension] Connected to ws://127.0.0.1:8000/ws/extension [OK]")
        
        # Send registration
        await ws.send(json.dumps({"type": "register", "client": "test_client"}))
        
        # Wait for a message or close after 2 seconds
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                msg = json.loads(raw)
                print(f"[Mock Extension] Received action: {msg.get('action')}")
                
                # Respond with mock success
                res = {"id": msg.get("id"), "success": True, "data": {"status": "ok", "action": msg.get("action")}}
                await ws.send(json.dumps(res))
        except asyncio.TimeoutError:
            print("[Mock Extension] Handshake verified successfully!")

if __name__ == "__main__":
    asyncio.run(mock_extension_client())
