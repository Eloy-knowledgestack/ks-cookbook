#!/usr/bin/env python3
"""Core logic — Create definition → Create/start Run → Poll → Download."""

import io as _io
import time
import zipfile
from pathlib import Path
from uuid import UUID

from ksapi.api.bulk_download_api import BulkDownloadApi
from ksapi.api.documents_api import DocumentsApi
from ksapi.api.workflow_definitions_api import WorkflowDefinitionsApi
from ksapi.api.workflow_runs_api import WorkflowRunsApi
from ksapi.exceptions import ApiException
from ksapi.models.bulk_download_request import BulkDownloadRequest
from ksapi.models.create_workflow_definition_request import CreateWorkflowDefinitionRequest
from ksapi.models.start_workflow_run_request import StartWorkflowRunRequest
from ksapi.models.workflow_execution_state import WorkflowExecutionState
from ksapi.models.workflow_run_response import WorkflowRunResponse
from ksclient import client

_DOCUMENT_PART_TYPE = "DOCUMENT"
_BATCH_SIZE = 200


def _value(enum_or_str):
    return str(getattr(enum_or_str, "value", enum_or_str))


# ══════════════════════════════════════════════════════════════════════════
#  Step 1: Create workflow definition
# ══════════════════════════════════════════════════════════════════════════


def create_definition(
    api: WorkflowDefinitionsApi | None = None,
    *,
    name: str,
    description: str = "",
    parent_folder_id: UUID,
    approval_required: bool = True,
    max_run_duration_seconds: int = 1800,
    is_template: bool = False,
):
    if api is None:
        api = WorkflowDefinitionsApi(client)
    req = CreateWorkflowDefinitionRequest(
        name=name,
        description=description or None,
        parent_path_part_id=parent_folder_id,
        approval_required=approval_required,
        max_run_duration_seconds=max_run_duration_seconds,
        is_template=is_template,
    )
    return api.create_workflow_definition(req)


# ══════════════════════════════════════════════════════════════════════════
#  Step 2a: Create Run
# ══════════════════════════════════════════════════════════════════════════


def create_run(
    api: WorkflowDefinitionsApi | None = None,
    *,
    definition_id: UUID,
    name: str,
    input_scope: str | None = None,
    auto_start: bool = False,
    user_message: str | None = None,
    input_file_paths: list[str] | None = None,
) -> WorkflowRunResponse:
    """Create a Run draft.

    Existing documents → reference via input_scope directly.
    Local files → create empty Run then upload to the run's inputs/ folder.
    """
    if api is None:
        api = WorkflowDefinitionsApi(client)

    run = api.create_workflow_run(
        definition_id=definition_id,
        name=name,
        input_scope=input_scope,
        auto_start=auto_start,
        user_message=user_message,
    )

    if input_file_paths:
        _upload_to_inputs(run.inputs_path_part_id, input_file_paths)

    return run


def _upload_to_inputs(inputs_path_part_id: UUID, file_paths: list[str]) -> None:
    """Upload files to the Run's inputs/ folder."""
    import os as _os

    docs_api = DocumentsApi(client)
    for fp in file_paths:
        name = _os.path.basename(fp)
        with open(fp, "rb") as fh:
            docs_api.ingest_document(
                file=(name, fh.read()),
                path_part_id=inputs_path_part_id,
            )


# ══════════════════════════════════════════════════════════════════════════
#  Step 2b: Start Run
# ══════════════════════════════════════════════════════════════════════════


def start_run(
    api: WorkflowRunsApi | None = None,
    *,
    run_id: UUID,
    user_message: str | None = None,
) -> dict:
    """Start a Run, optionally with a user_message layered on top of the instruction."""
    if api is None:
        api = WorkflowRunsApi(client)

    req = StartWorkflowRunRequest()
    if user_message:
        req.user_message = user_message

    run = api.start_workflow_run(run_id, start_workflow_run_request=req)

    return {
        "run_id": str(run.id),
        "execution_state": run.execution_state.value if run.execution_state else None,
        "approval_state": run.approval_state.value if run.approval_state else None,
    }


# ══════════════════════════════════════════════════════════════════════════
#  Step 3: Poll & download outputs
# ══════════════════════════════════════════════════════════════════════════


def poll_run(
    api: WorkflowRunsApi | None = None,
    *,
    run_id: UUID,
    poll_interval: int = 10,
    max_wait: int = 600,
):
    """Poll until COMPLETED or FAILED.

    Returns the run object on success, or None on failure/timeout.
    """
    if api is None:
        api = WorkflowRunsApi(client)

    terminal = {WorkflowExecutionState.COMPLETED, WorkflowExecutionState.FAILED}
    elapsed = 0
    run = api.get_workflow_run(run_id)

    while run.execution_state not in terminal:
        if elapsed >= max_wait:
            return None
        time.sleep(poll_interval)
        elapsed += poll_interval
        try:
            run = api.get_workflow_run(run_id)
        except ApiException:
            continue

    if run.execution_state == WorkflowExecutionState.FAILED:
        return None
    return run


def download_outputs(
    api: BulkDownloadApi | None = None,
    *,
    run,  # WorkflowRunResponse
    out_dir: str | Path = "./workflow_outputs",
) -> dict:
    """Download & extract Run outputs.

    Returns dict: {run_id, state, file_count, skipped, dest_dir, error}
    """
    state = _value(run.execution_state) if run.execution_state else "unknown"
    if run.execution_state != WorkflowExecutionState.COMPLETED:
        return {
            "run_id": str(run.id),
            "state": state,
            "file_count": 0,
            "skipped": 0,
            "dest_dir": "",
            "error": f"Run not completed, current state: {state}",
        }

    if api is None:
        api = BulkDownloadApi(client)

    document_ids = [
        asset.id
        for asset in (run.output_assets or [])
        if _value(asset.part_type) == _DOCUMENT_PART_TYPE
    ]
    if not document_ids:
        return {
            "run_id": str(run.id),
            "state": state,
            "file_count": 0,
            "skipped": 0,
            "dest_dir": "",
            "error": "No DOCUMENT-type output assets",
        }

    dest = Path(out_dir) / (run.name or str(run.id))
    dest.mkdir(parents=True, exist_ok=True)

    skipped_total = 0
    for start in range(0, len(document_ids), _BATCH_SIZE):
        batch = document_ids[start : start + _BATCH_SIZE]
        resp = api.start_bulk_download_without_preload_content(
            BulkDownloadRequest(document_ids=batch)
        )
        data = resp.read()
        skipped_total += int(resp.headers.get("X-Bulk-Download-Skipped", "0"))
        with zipfile.ZipFile(_io.BytesIO(data)) as archive:
            archive.extractall(dest)

    return {
        "run_id": str(run.id),
        "state": state,
        "file_count": sum(1 for _ in dest.rglob("*") if _.is_file()),
        "skipped": skipped_total,
        "dest_dir": str(dest),
    }
