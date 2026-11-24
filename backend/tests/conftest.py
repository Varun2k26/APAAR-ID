import json
import os
import shutil
import tempfile

_tmp = tempfile.mkdtemp(prefix="apaar-test-")
os.environ["APAAR_DATA_DIR"] = _tmp
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["BACKGROUND_JOBS"] = "0"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from seed import generate  # noqa: E402


@pytest.fixture(scope="session")
def seeded():
    generate.main(reset=True)
    data = json.loads(open(os.path.join(_tmp, "demo_accounts.json")).read())
    yield data
    shutil.rmtree(_tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def client(seeded):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def tokens(client, seeded):
    import pyotp
    out = {}
    for a in seeded["accounts"]:
        r = client.post("/api/v1/auth/login", json={"username": a["username"], "password": a["password"]}).json()
        if r.get("mfa_required"):
            from app.db import SessionLocal
            from app.models import User
            db = SessionLocal()
            u = db.query(User).filter_by(username=a["username"]).one()
            code = pyotp.TOTP(u.totp_secret).now()
            db.close()
            r = client.post("/api/v1/auth/mfa", json={"mfa_token": r["mfa_token"], "code": code}).json()
        out[a["username"]] = r["access_token"]
    return out


def H(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def student_token(client, seeded):
    def login(apaar):
        code = client.post("/api/v1/mock/digilocker/authorize", json={"apaar_id": apaar, "otp": "123456"}).json()["code"]
        return client.post("/api/v1/auth/digilocker/token", json={"code": code}).json()["access_token"]
    return login


@pytest.fixture(scope="session")
def demo_dir(seeded):
    return os.path.join(_tmp, "demo")
