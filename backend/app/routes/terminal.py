import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.services.lab_service import lab_service


router = APIRouter()


@router.websocket("/labs/{lab_id}/terminal")
async def terminal(websocket: WebSocket, lab_id: str):
    await websocket.accept()

    session = lab_service.get(lab_id)

    if session is None:
        await websocket.send_json(
            {
                "type": "error",
                "message": "Lab not found",
            }
        )
        await websocket.close()
        return

    terminal_service = websocket.app.state.terminal_service

    terminal_session = terminal_service.create_session(
        session.container_id
    )

    async def docker_to_websocket():
        while True:
            data = await terminal_session.read()

            if not data:
                break

            await websocket.send_json(
                {
                    "type": "output",
                    "data": data.decode(
                        "utf-8",
                        errors="replace",
                    ),
                }
            )

    async def websocket_to_docker():
        while True:
            raw_message = await websocket.receive_text()

            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            message_type = message.get("type")

            if message_type == "input":
                data = message.get("data", "")
                await terminal_session.write(data)

    try:
        await asyncio.gather(
            docker_to_websocket(),
            websocket_to_docker(),
        )

    except WebSocketDisconnect:
        pass

    finally:
        terminal_session.close()