import os
import tempfile

# Must be set before `app` is imported: the engine is bound at import time.
_tmp = tempfile.mkdtemp(prefix="msadiq-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp, 'test.db')}"
os.environ["SEED_DEMO_DATA"] = "1"
os.environ["ENVIRONMENT"] = "development"
os.environ["UPLOAD_FOLDER"] = os.path.join(_tmp, "uploads")
os.environ.pop("VERCEL", None)
