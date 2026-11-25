from __future__ import annotations

import io
import shutil
import zipfile

import pytest
from fastapi.testclient import TestClient

from sakshya.api.app import create_app
from sakshya.api.workspace import Workspace

from .conftest import DEMO, DEMO_IDS

CASE = DEMO_IDS[0]


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    root = tmp_path_factory.mktemp("workspace")
    shutil.copytree(DEMO / CASE, root / "cases" / CASE)
    app = create_app(Workspace(root))
    with TestClient(app) as test_client:
        yield test_client


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_health_and_listing(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"
    cases = client.get("/api/cases").json()
    assert CASE in {c["id"] for c in cases}
    assert client.get("/").status_code == 200
    assert client.get("/").headers["x-content-type-options"] == "nosniff"


def test_case_link_and_observation(client: TestClient) -> None:
    data = client.get(f"/api/cases/{CASE}").json()
    link = next(l for l in data["links"] if l["status"] == "inferred")
    detail = client.get(f"/api/cases/{CASE}/links/{link['link_id']}").json()
    assert detail["link_id"] == link["link_id"]
    obs_id = data["timeline"]["items"][0]["obs_id"]
    observation = client.get(f"/api/cases/{CASE}/observations/{obs_id}").json()
    assert len(observation["sha256"]) == 64
    assert observation["row"] >= 1


def test_unknown_case_and_bad_identifiers(client: TestClient) -> None:
    assert client.get("/api/cases/NOPE").status_code == 404
    assert client.get("/api/cases/..%2F..%2Fetc").status_code in {400, 404}


def test_reach_as_of_and_policy(client: TestClient) -> None:
    full = client.get(f"/api/cases/{CASE}/reach", params={"policy": "fifo"}).json()
    assert full["trace"]["policy"] == "fifo"
    early = client.get(f"/api/cases/{CASE}/reach", params={"as_of": 0}).json()
    assert early["trace"]["victim_out"] == 0


def test_investigator_rejection_is_applied_and_logged(client: TestClient) -> None:
    data = client.get(f"/api/cases/{CASE}").json()
    link = next(l for l in data["links"] if l["type"] == "co_presence" and l["status"] == "inferred")
    response = client.post(
        f"/api/cases/{CASE}/actions",
        json={"type": "reject_link", "target": link["link_id"], "reason": "Phone was with the police at the time"},
    )
    assert response.status_code == 200
    updated = next(l for l in response.json()["links"] if l["link_id"] == link["link_id"])
    assert updated["status"] == "rejected"
    entries = response.json()["evidence"]["ledger_entries"]
    assert any(e["type"] == "investigator_action" for e in entries)
    action_id = next(a["id"] for a in response.json()["actions"] if a["target"] == link["link_id"])
    restored = client.post(
        f"/api/cases/{CASE}/actions", json={"type": "revoke", "target": action_id, "reason": "Entered in error"}
    )
    assert next(l for l in restored.json()["links"] if l["link_id"] == link["link_id"])["status"] == "inferred"


def test_action_needs_a_reason(client: TestClient) -> None:
    response = client.post(f"/api/cases/{CASE}/actions", json={"type": "reject_link", "target": "x", "reason": ""})
    assert response.status_code == 422


def test_report_is_hashed_into_the_ledger(client: TestClient) -> None:
    response = client.get(f"/api/cases/{CASE}/report")
    assert response.status_code == 200
    assert "Annex A" in response.text
    digest = response.headers["x-report-sha256"]
    entries = client.get(f"/api/cases/{CASE}").json()["evidence"]["ledger_entries"]
    assert any(e["type"] == "report_export" and e["payload"]["sha256"] == digest for e in entries)


@pytest.mark.parametrize(
    "files,status",
    [
        ({"case/../../evil.csv": b"x", "case/case.yaml": b"id: X1\nevidence: []\n"}, 400),
        ({"case/case.yaml": b"id: X2\nevidence: []\n", "case/run.sh": b"echo"}, 400),
        ({"case/notes.csv": b"a,b\n"}, 400),
    ],
)
def test_unsafe_uploads_are_refused(client: TestClient, files: dict[str, bytes], status: int) -> None:
    response = client.post("/api/cases", files={"file": ("case.zip", _zip(files), "application/zip")})
    assert response.status_code == status


def test_not_a_zip_is_refused(client: TestClient) -> None:
    response = client.post("/api/cases", files={"file": ("case.zip", b"plain text", "application/zip")})
    assert response.status_code == 400


def test_valid_upload_is_analysed(client: TestClient) -> None:
    source = DEMO / DEMO_IDS[-1]
    files = {}
    for path in source.rglob("*"):
        if path.is_file() and path.name != "truth.json":
            relative = path.relative_to(source).as_posix()
            data = path.read_bytes()
            if relative == "case.yaml":
                data = data.replace(DEMO_IDS[-1].encode(), b"CASE-UPLOAD-1", 1)
            files[f"upload/{relative}"] = data
    response = client.post("/api/cases", files={"file": ("case.zip", _zip(files), "application/zip")})
    assert response.status_code == 200, response.text
    assert response.json()["id"] == "CASE-UPLOAD-1"
    again = client.post("/api/cases", files={"file": ("case.zip", _zip(files), "application/zip")})
    assert again.status_code == 409
