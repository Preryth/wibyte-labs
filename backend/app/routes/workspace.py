from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.services.lab_service import lab_service


router = APIRouter()


class FileWriteRequest(BaseModel):
    content: str


class CreateFileRequest(BaseModel):
    path: str
    type: str = "file"


class RenameFileRequest(BaseModel):
    old_path: str
    new_path: str


@router.get("/labs/{lab_id}/files")
def list_files(
    lab_id: str,
    path: str = ".",
):
    session = lab_service.get(lab_id)

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )

    workspace_service = router.workspace_service

    try:
        files = workspace_service.list_files(
            session.container_id,
            path,
        )

        return {
            "path": path,
            "files": files,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Directory not found",
        )


@router.get(
    "/labs/{lab_id}/files/{path:path}"
)
def read_file(
    lab_id: str,
    path: str,
):
    session = lab_service.get(lab_id)

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )

    workspace_service = router.workspace_service

    try:
        content = workspace_service.read_file(
            session.container_id,
            path,
        )

        return {
            "path": path,
            "content": content,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="File not found",
        )


@router.put(
    "/labs/{lab_id}/files/{path:path}"
)
def write_file(
    lab_id: str,
    path: str,
    request: FileWriteRequest,
):
    session = lab_service.get(lab_id)

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )

    workspace_service = router.workspace_service

    try:
        workspace_service.write_file(
            session.container_id,
            path,
            request.content,
        )

        return {
            "path": path,
            "status": "saved",
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


@router.post(
    "/labs/{lab_id}/files"
)
def create_file(
    lab_id: str,
    request: CreateFileRequest,
):
    session = lab_service.get(lab_id)

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )

    workspace_service = router.workspace_service

    try:
        if request.type == "directory":
            workspace_service.create_directory(
                session.container_id,
                request.path,
            )

        elif request.type == "file":
            workspace_service.create_file(
                session.container_id,
                request.path,
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Type must be "
                    "'file' or 'directory'"
                ),
            )

        return {
            "path": request.path,
            "type": request.type,
            "status": "created",
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


@router.post(
    "/labs/{lab_id}/files/rename"
)
def rename_file(
    lab_id: str,
    request: RenameFileRequest,
):
    session = lab_service.get(lab_id)

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )

    workspace_service = router.workspace_service

    try:
        workspace_service.rename(
            session.container_id,
            request.old_path,
            request.new_path,
        )

        return {
            "old_path": request.old_path,
            "new_path": request.new_path,
            "status": "renamed",
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="File or directory not found",
        )

    except FileExistsError:
        raise HTTPException(
            status_code=409,
            detail=(
                "A file or directory with "
                "that name already exists"
            ),
        )


@router.delete(
    "/labs/{lab_id}/files/{path:path}"
)
def delete_file(
    lab_id: str,
    path: str,
):
    session = lab_service.get(lab_id)

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )

    workspace_service = router.workspace_service

    try:
        workspace_service.delete(
            session.container_id,
            path,
        )

        return {
            "path": path,
            "status": "deleted",
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="File or directory not found",
        )


router.workspace_service = None