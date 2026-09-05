import ast
import asyncio
import json
import shlex

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.services.lab_service import lab_service
from backend.app.auth import authenticate_token


router = APIRouter()


def file_uses_tkinter(container, path: str) -> bool:
    """Inspect a Python source file inside the Lab container."""
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

    source = result.output.decode("utf-8", errors="replace")

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
            if module == "tkinter" or module.startswith("tkinter."):
                return True

    return False


@router.websocket("/labs/{lab_id}/terminal")
async def terminal(websocket: WebSocket, lab_id: str):
    await websocket.accept()

    token = websocket.query_params.get("access_token", "")
    try:
        user = authenticate_token(token)
    except Exception:
        await websocket.send_json(
            {"type": "error", "message": "Authentication failed"}
        )
        await websocket.close(code=1008)
        return

    session = lab_service.get_for_student(lab_id, user.id)
    if session is None:
        await websocket.send_json(
            {"type": "error", "message": "Lab not found"}
        )
        await websocket.close(code=1008)
        return

    terminal_service = websocket.app.state.terminal_service
    terminal_session = terminal_service.create_session(session.container_id)

    process_session = None
    process_task = None

    async def docker_to_websocket():
        while True:
            data = await terminal_session.read()
            if not data:
                break

            await websocket.send_json(
                {
                    "type": "output",
                    "data": data.decode("utf-8", errors="replace"),
                }
            )

    async def relay_process(process):
        try:
            while True:
                data = await process.read()
                if data:
                    await websocket.send_json(
                        {
                            "type": "output",
                            "data": data.decode("utf-8", errors="replace"),
                        }
                    )
                    continue

                if not process.is_running():
                    break

                await asyncio.sleep(0.05)

            await websocket.send_json(
                {
                    "type": "process_exit",
                    "exit_code": process.exit_code(),
                }
            )
        except WebSocketDisconnect:
            pass
        finally:
            process.close()

    async def websocket_to_docker():
        nonlocal process_session, process_task

        while True:
            raw_message = await websocket.receive_text()

            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Invalid terminal message.",
                    }
                )
                continue

            message_type = message.get("type")

            if message_type == "input":
                data = message.get("data", "")
                if isinstance(data, str):
                    await terminal_session.write(data)
                continue

            if message_type == "run":
                path = message.get("path", "")
                if not isinstance(path, str):
                    await websocket.send_json(
                        {"type": "error", "message": "Invalid file path."}
                    )
                    continue

                path = path.strip()
                if not path:
                    await websocket.send_json(
                        {"type": "error", "message": "No file specified."}
                    )
                    continue

                # Only one Run process may own the Run button at a time.
                if process_session is not None:
                    if process_session.is_running():
                        await process_session.write("\x03")
                        await asyncio.sleep(0.1)
                    process_session.close()
                    process_session = None

                container = terminal_service.docker_client.containers.get(
                    session.container_id
                )

                uses_tkinter = file_uses_tkinter(container, path)
                environment = None

                if uses_tkinter:
                    gui_service = websocket.app.state.gui_service

                    # Starting GUI here makes Run self-contained: a Tkinter
                    # program cannot fail merely because the user forgot to
                    # press the GUI button first.
                    try:
                        gui_status = await asyncio.to_thread(
                            gui_service.start,
                            session.container_id,
                        )
                    except Exception as exc:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": (
                                    "Failed to start the GUI environment: "
                                    f"{exc}"
                                ),
                            }
                        )
                        continue

                    environment = {
                        "DISPLAY": gui_status["display"],
                    }

                    await websocket.send_json(
                        {
                            "type": "output",
                            "data": (
                                "\r\n"
                                f"Running {path} in GUI...\r\n"
                            ),
                        }
                    )

                safe_path = shlex.quote(path)
                command = f"python -u -- {safe_path}"

                try:
                    process_session = terminal_service.start_process(
                        session.container_id,
                        command,
                        environment=environment,
                    )
                except Exception as exc:
                    process_session = None
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": f"Failed to start process: {exc}",
                        }
                    )
                    continue

                await websocket.send_json(
                    {
                        "type": "run_started",
                        "path": path,
                    }
                )

                process_task = asyncio.create_task(
                    relay_process(process_session)
                )
                continue

            if message_type == "stop":
                await websocket.send_json({"type": "stop_requested"})

                if process_session is not None:
                    await process_session.write("\x03")
                else:
                    await terminal_session.write("\x03")
                continue

            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Unknown terminal message type: {message_type}",
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

        if process_session is not None:
            try:
                await process_session.write("\x03")
            except Exception:
                pass
            process_session.close()

        if process_task is not None and not process_task.done():
            process_task.cancel()
            try:
                await process_task
            except asyncio.CancelledError:
                pass
