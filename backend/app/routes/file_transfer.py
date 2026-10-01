
import asyncio
import io
import tarfile
from urllib.parse import quote

from fastapi import HTTPException, Request, Response

from backend.app.auth import CurrentUser
from backend.app.services.lab_service import lab_service

LIMIT = 10 * 1024 * 1024

# Executed inside the container as the student user.
FILE_SCRIPT = r"""
import os, stat, sys

action, relative = sys.argv[1:3]
parts = relative.split("/")
if (
    not relative
    or any(p in ("", ".", "..", ".git") for p in parts)
    or any(ord(c) < 32 for c in relative)
    or "\\" in relative
):
    sys.exit(10)

try:
    parent = os.open(
        "/workspace/wibyte-workspace",
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    for part in parts[:-1]:
        next_fd = os.open(
            part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent,
        )
        os.close(parent)
        parent = next_fd

    if action == "upload":
        with open(sys.argv[3], "rb") as source:
            data = source.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            sys.exit(13)
        fd = os.open(
            parts[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o644,
            dir_fd=parent,
        )
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
        except BaseException:
            os.unlink(parts[-1], dir_fd=parent)
            raise
    else:
        fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent,
        )
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                sys.exit(10)
            if info.st_size > 10 * 1024 * 1024:
                sys.exit(13)
            data = source.read(10 * 1024 * 1024 + 1)
            if len(data) > 10 * 1024 * 1024:
                sys.exit(13)
        sys.stdout.buffer.write(data)
except FileExistsError:
    sys.exit(11)
except FileNotFoundError:
    sys.exit(12)
except OSError:
    sys.exit(10)
"""


def checked(result):
    messages = {
        10: (400, "Invalid file path or inaccessible file."),
        11: (409, "A file with that name already exists. Rename it first."),
        12: (404, "File or folder not found."),
        13: (413, "Maximum file size is 10 MB."),
    }
    if result.exit_code:
        status, message = messages.get(
            result.exit_code, (500, "File transfer failed.")
        )
        raise HTTPException(status_code=status, detail=message)


def upload_bytes(container, path, data):
    temp = container.exec_run(
        ["python", "-c",
         "import tempfile; print(tempfile.mkdtemp(prefix='wpl-upload-'))"],
        user="student",
    )
    checked(temp)
    directory = temp.output.decode().strip()

    try:
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as tar:
            entry = tarfile.TarInfo("payload")
            entry.size = len(data)
            entry.mode = 0o444
            tar.addfile(entry, io.BytesIO(data))

        if not container.put_archive(directory, archive.getvalue()):
            raise HTTPException(status_code=500, detail="Upload staging failed.")

        checked(container.exec_run(
            ["python", "-c", FILE_SCRIPT, "upload", path, directory + "/payload"],
            user="student",
        ))
    finally:
        container.exec_run(
            ["python", "-c",
             "import os,sys; "
             "p=sys.argv[1]; "
             "os.path.exists(p+'/payload') and os.unlink(p+'/payload'); "
             "os.rmdir(p)",
             directory],
            user="student",
        )


def download_bytes(container, path):
    result = container.exec_run(
        ["python", "-c", FILE_SCRIPT, "download", path],
        user="student",
        demux=True,
    )
    checked(result)
    stdout, _ = result.output
    return stdout or b""


def register_file_transfers(router):
    def get_container(lab_id, user):
        session = lab_service.get_for_student(lab_id, user.id)
        if session is None:
            raise HTTPException(status_code=404, detail="Lab not found")
        return router.workspace_service._get_container(session.container_id)

    @router.post("/labs/{lab_id}/upload")
    async def upload_file(
        lab_id: str,
        request: Request,
        path: str,
        user: CurrentUser = None,
    ):
        container = await asyncio.to_thread(get_container, lab_id, user)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > LIMIT:
                raise HTTPException(status_code=413, detail="Maximum file size is 10 MB.")
            data.extend(chunk)

        await asyncio.to_thread(upload_bytes, container, path, bytes(data))
        await asyncio.to_thread(lab_service.update_activity, lab_id)
        return {"status": "uploaded", "path": path}

    @router.get("/labs/{lab_id}/download")
    def download_file(
        lab_id: str,
        path: str,
        user: CurrentUser = None,
    ):
        container = get_container(lab_id, user)
        data = download_bytes(container, path)
        lab_service.update_activity(lab_id)
        filename = quote(path.rsplit("/", 1)[-1], safe="")
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''" + filename,
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
