# Deployment

Sakshya is a single Python web service. It serves the workbench and the API from one process and keeps cases on local disk.

## Render

### Blueprint

`render.yaml` describes the service:

```yaml
services:
  - type: web
    name: sakshya
    runtime: python
    plan: free
    buildCommand: pip install --upgrade pip && pip install -r requirements.txt
    startCommand: uvicorn sakshya.api.app:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips "*"
    healthCheckPath: /api/health
    autoDeploy: true
    envVars:
      - key: SAKSHYA_WORKSPACE
        value: /opt/render/project/src/workspace
```

1. Put the project in a GitHub or GitLab repository, with `render.yaml` at the root.
2. In Render choose **New**, then **Blueprint**, connect the repository and apply.
3. The first build installs the dependencies with the Python version in `.python-version` (3.13). The service is live when `/api/health` answers.

### Manual web service

| Setting | Value |
| --- | --- |
| Runtime | Python |
| Root directory | the folder that holds `requirements.txt` |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn sakshya.api.app:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/api/health` |

### Keeping uploaded cases

Render's file system is reset on every deploy and restart. The five demonstration cases are copied into the workspace on each start, so they are always present, but uploaded cases and investigator decisions are lost unless the workspace sits on a persistent disk:

1. Choose a paid instance type and add a disk, for example mounted at `/var/data`.
2. Set `SAKSHYA_WORKSPACE` to `/var/data/workspace`.

### Start-up

The port opens immediately. The demonstration cases are analysed in a background thread on start, which takes a few seconds on a small instance; a case requested before its analysis finishes waits for it.

## Docker

```bash
docker build -t sakshya .
docker run -p 8000:8000 -v sakshya-data:/data sakshya
```

The image runs as an unprivileged user and stores the workspace in `/data/workspace`.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `SAKSHYA_WORKSPACE` | `./workspace` | Where cases, ledgers and analysis bundles are stored |
| `PORT` | `8000` | Port for `python -m sakshya serve` |

Model parameters live in `sakshya/config/settings.yaml` (thresholds, caps, windows, beam size, freeze latency), crime templates in `sakshya/config/templates/` and indicator weights in `sakshya/config/indicators.yaml`. Changes take effect on restart, and the configuration is part of the input digest recorded in the ledger, so every analysis can be traced to the settings it used.

## Security

* Uploads must be `.zip` archives of at most 25 MB with at most 400 files. Paths that leave the case folder and file types other than CSV, text, email, JSON, YAML and images are refused.
* Case identifiers are restricted to letters, digits, `-` and `_`.
* Responses carry `X-Content-Type-Options`, `Referrer-Policy` and `X-Frame-Options` headers.
* There are no user accounts. Every investigator action is recorded with the name entered in the workbench, and the ledger shows any later change to it, but the service should still run on a protected network or behind an authenticating proxy when real case data is used.

## API

Interactive API documentation is served at `/api/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service status |
| GET | `/api/cases` | Case list with the decision for each |
| POST | `/api/cases` | Upload a case archive (`multipart/form-data`, field `file`) |
| GET | `/api/cases/{id}` | Full analysis bundle |
| GET | `/api/cases/{id}/reach?as_of=&policy=` | Money trail and freeze list at a time, `pro_rata` or `fifo` |
| GET | `/api/cases/{id}/links/{link_id}` | One link with its terms and both ends |
| GET | `/api/cases/{id}/observations/{obs_id}` | One record with its file, line and hash |
| POST | `/api/cases/{id}/actions` | Confirm or reject a link, forbid a merge, or revoke an earlier action |
| GET | `/api/cases/{id}/report` | HTML case report; its SHA-256 is returned in `X-Report-SHA256` and logged |
| GET | `/api/cases/{id}/export.json` | Analysis bundle as a download |
| GET | `/api/evaluation` | Evaluation results |
