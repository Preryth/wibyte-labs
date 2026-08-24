import ast
import asyncio
import json
import shlex

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
)

from backend.app.services.lab_service import (
    lab_service,
)


router = APIRouter()


def file_uses_tkinter(
    container,
    path: str,
) -> bool:
    """
    Inspect a Python source file inside the existing Lab container
    and determine whether it imports tkinter.

    This keeps GUI detection on the backend and avoids sending the
    editor contents through the terminal protocol again.
    """
    safe_path = shlex.quote(path)

    result = container.exec_run(
        [
            "bash",
            "-lc",
            f"cat -- {safe_path}",
        ],
        user="student",
        workdir="/workspace/wibyte-workspace",
    )

    if result.exit_code != 0:
        return False

    source = result.output.decode(
        "utf-8",
        errors="replace",
    )

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "tkinter"
                or alias.name.startswith("tkinter.")
                for alias in node.names
            ):
                return True

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""

            if (
                module == "tkinter"
                or module.startswith("tkinter.")
            ):
                return True

    return False


@router.websocket(
    "/labs/{lab_id}/terminal"
)
async def terminal(
    websocket: WebSocket,
    lab_id: str,
):
    await websocket.accept()

    session = lab_service.get(
        lab_id
    )

    if session is None:
        await websocket.send_json(
            {
                "type": "error",
                "message": "Lab not found",
            }
        )

        await websocket.close()
        return

    terminal_service = (
        websocket.app.state
        .terminal_service
    )

    terminal_session = (
        terminal_service.create_session(
            session.container_id
        )
    )

    async def docker_to_websocket():
        while True:
            data = (
                await terminal_session.read()
            )

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
            raw_message = (
                await websocket.receive_text()
            )

            try:
                message = json.loads(
                    raw_message
                )

            except json.JSONDecodeError:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": (
                            "Invalid terminal "
                            "message."
                        ),
                    }
                )

                continue

            message_type = message.get(
                "type"
            )

            # -----------------------------------------
            # Normal terminal keyboard input
            # -----------------------------------------

            if message_type == "input":
                data = message.get(
                    "data",
                    "",
                )

                if isinstance(
                    data,
                    str,
                ):
                    await terminal_session.write(
                        data
                    )

            # -----------------------------------------
            # Run file
            # -----------------------------------------

            elif message_type == "run":
                path = message.get(
                    "path",
                    "",
                )

                if not isinstance(
                    path,
                    str,
                ):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": (
                                "Invalid file "
                                "path."
                            ),
                        }
                    )

                    continue

                path = path.strip()

                if not path:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": (
                                "No file specified."
                            ),
                        }
                    )

                    continue

                container = (
                    terminal_service.docker_client
                    .containers.get(
                        session.container_id
                    )
                )

                uses_tkinter = file_uses_tkinter(
                    container,
                    path,
                )

                if uses_tkinter:
                    gui_service = (
                        websocket.app.state
                        .gui_service
                    )

                    gui_status = gui_service.status(
                        session.container_id
                    )

                    if not gui_status["ready"]:
                        await websocket.send_json(
                            {
                                "type": "output",
                                "data": (
                                    "\r\n"
                                    "This program requires the GUI environment.\r\n"
                                    "Click the GUI button to open the desktop environment,\r\n"
                                    "then run the program again.\r\n"
                                ),
                            }
                        )

                        await websocket.send_json(
                            {
                                "type": "process_exit",
                                "exit_code": 1,
                            }
                        )

                        continue

                    await websocket.send_json(
                        {
                            "type": "output",
                            "data": (
                                "\r\n"
                                f"Running {path} in GUI...\r\n"
                                "Opened in GUI.\r\n"
                            ),
                        }
                    )

                    safe_path = shlex.quote(
                        path
                    )

                    command = (
                        f"DISPLAY={shlex.quote(gui_status['display'])} "
                        f"python -u {safe_path}\r"
                    )

                else:
                    safe_path = shlex.quote(
                        path
                    )

                    command = (
                        f"python -u "
                        f"{safe_path}\r"
                    )

                await websocket.send_json(
                    {
                        "type": "run_started",
                        "path": path,
                    }
                )

                await terminal_session.write(
                    command
                )

            # -----------------------------------------
            # Stop running process
            # -----------------------------------------

            elif message_type == "stop":
                await websocket.send_json(
                    {
                        "type": "stop_requested",
                    }
                )

                await terminal_session.write(
                    "\x03"
                )

            # -----------------------------------------
            # Unknown message
            # -----------------------------------------

            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": (
                            "Unknown terminal "
                            "message type: "
                            f"{message_type}"
                        ),
                    }
                )

    try:
        await asyncio.gather(
            docker_to_websocket(),
            websocket_to_docker(),
        )

    except WebSocketDisconnect:
        pass

    finally:
        terminal_session.close()
