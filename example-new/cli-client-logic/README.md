# End-to-End Execution Case

> Create a Workflow definition from scratch, reference existing documents + upload local files,
> start the run, wait for completion, and download outputs.
> Unified CLI entrypoint: `python cli.py <subcommand>`.

## Step 1 — Create Definition

```
python cli.py define --name test123456 --json
   │
   │  POST /v1/workflow-definitions
   │
   ▼
```

```json
{
  "id":                       "019f42fb-6311-7109-bbf7-5e7e7eea3014",  ◄── passed to Step 2a
  "name":                     "test123456",
  "path_part_id":             "019f42fb-6314-7c6f-bf1e-48042b2d3ca8",
  "instruction_path_part_id": "019f42fb-6322-7627-a524-2a829f1badfc",
  "parent_path_part_id":      "019f3ab8-b807-73d8-b2d5-5dbb4235dbe5",
  "approval_required":        true,
  "is_template":              false,
  "created_at":               "2026-07-09T02:26:38+08:00"
}
```

**Output → Input chain:** `id` → Step 2a `--definition-id`

---

## Step 2a — Create Draft

```
python cli.py run \
  --definition-id 019f42fb-6311-7109-bbf7-5e7e7eea3014 \   ◄── Step 1 id
  --name "demorun" \
  --input-scope 019f40a1-8eec-74e6-9675-bcf583fb0dd4 \  ◄── existing document path_part_id (bare UUID, auto-wrapped to JSON array)
  --input-files ./uploadtest.md                                ◄── local file
   │
   │  POST /v1/workflow-definitions/{id}/runs     ← create empty Run
   │  POST /v1/documents/ingest                   ← upload to inputs/
   │
   ▼
```

```
Run draft created
   Run ID               : 019f431f-343f-7c0b-a3e9-7349ceef2d91  ◄── passed to Step 2b
   Name                 : demorun
   Inputs path          : 019f431f-3453-703c-b2d9-f4b1d7758481
   State                : NOT_STARTED
Next: python cli.py start --run-id 019f431f-343f-7c0b-a3e9-7349ceef2d91
```

**Output → Input chain:** `Run ID` → Step 2b `--run-id`

---

## Step 2b — Start Run

```
python cli.py start --run-id 019f431f-343f-7c0b-a3e9-7349ceef2d91
   │
   │  POST /v1/workflow-runs/{id}/start
   │  → freeze snapshot, execution_state → IN_PROGRESS
   │
   ▼
```

```
Run started
   Run ID               : 019f431f-343f-7c0b-a3e9-7349ceef2d91
   State                : IN_PROGRESS
   Approval             : not_required
```

**Output → Input chain:** `Run ID` → Step 3 `--run-id`

---

## Step 3 — Poll & Download

### 3a) Dry Run

```
python cli.py download --run-id 019f431f-343f-7c0b-a3e9-7349ceef2d91 --dry-run
   │
   │  poll_run() → GET /v1/workflow-runs/{id} every 10s → wait for COMPLETED
   │  dry_run()  → iterate output_assets, count only, no download
   │
   ▼
```

```
Polling until run completes ...
Run completed

  Run: demorun (019f431f-343f-7c0b-a3e9-7349ceef2d91)
  Pending documents: 1
  Target dir: workflow_outputs/demorun
```

### 3b) Download

```
python cli.py download --run-id 019f431f-343f-7c0b-a3e9-7349ceef2d91
   │
   │  poll_run() → COMPLETED
   │  download_outputs() → POST /v1/documents/bulk-download → ZIP → extract
   │
   ▼
```

```
Download complete
   Run ID       : 019f431f-343f-7c0b-a3e9-7349ceef2d91
   Files        : 1
   Dest         : workflow_outputs/demorun
```

---

## Full Parameter Flow

```
  KS_PARENT_FOLDER_ID ──► Step 1: cli.py define
    --parent-folder-id ◄──┘
    → definition_id ──────────────────────┐
                                          │
  Step 2a: cli.py run                     │
    --definition-id ◄─────────────────────┘
    --input-scope ◄── existing document path_part_id
    --input-files ◄── local files
    → run_id ──────────────────────────────┐
                                           │
  Step 2b: cli.py start                    │
    --run-id ◄─────────────────────────────┘
    (execution_state → IN_PROGRESS)

  Step 3: cli.py download
    --run-id ◄── run_id from Step 2a/b
    → workflow_outputs/<run_name>/
```

## Subcommand Quick Reference

| Step            | Command                    | Required args                   |
| --------------- | -------------------------- | ------------------------------- |
| 1. Define       | `python cli.py define`   | `--parent-folder-id`          |
| 2a. Create Run  | `python cli.py run`      | `--definition-id`, `--name`  |
| 2b. Start Run   | `python cli.py start`    | `--run-id`                    |
| 3. Download     | `python cli.py download` | `--run-id`                    |

> All subcommands support `--json` output and `--help` for detailed usage.
