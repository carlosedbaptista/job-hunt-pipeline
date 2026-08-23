"""
test_gdrive_root.py -- Pins how the Drive root folder is resolved.

Background, all verified against the live API on 2026-08-23.

Uploads had never worked. The pipeline authenticated as a Service Account,
and Google reports that identity's quota as literally `{"limit": "0"}`: a
Service Account owns no bytes, so every upload into a personal Drive came
back 403 storageQuotaExceeded. Sharing the folder with it granted the right
to enter, never the right to store.

The fix is OAuth2, where the candidate owns the files. The scope chosen is
`drive.file` rather than `drive`, because the refresh token lives in a GitHub
Secret: under `drive` a leak costs his entire personal Drive, under
`drive.file` it costs the job PDFs he already sends to recruiters.

That choice has one consequence worth pinning: a folder created by hand in
the browser is INVISIBLE to the app. GDRIVE_PARENT_FOLDER_ID pointing at such
a folder returns 404, and blindly trusting it would send every upload into a
folder the app cannot write to. Hence the reachability probe and the
find-or-create fallback.
"""
import pytest

import gdrive_uploader as g


class FakeFiles:
    def __init__(self, reachable_ids=(), found=None, created="new-root-id"):
        self.reachable = set(reachable_ids)
        self.found = found
        self.created = created
        self.create_calls = []

    def get(self, fileId=None, **kw):
        class R:
            def __init__(self, ok, fid):
                self.ok, self.fid = ok, fid

            def execute(self):
                if not self.ok:
                    raise RuntimeError(f"404 not found: {self.fid}")
                return {"id": self.fid}

        return R(fileId in self.reachable, fileId)

    def list(self, **kw):
        found = self.found

        class R:
            def execute(self):
                return {"files": [{"id": found, "name": "Job Hunt Pipeline"}] if found else []}

        return R()

    def create(self, body=None, **kw):
        self.create_calls.append(body)
        created = self.created

        class R:
            def execute(self):
                return {"id": created}

        return R()


class FakeService:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


class TestRootResolution:
    def test_a_reachable_configured_id_is_used(self, monkeypatch):
        monkeypatch.setenv("GDRIVE_PARENT_FOLDER_ID", "known-folder")
        files = FakeFiles(reachable_ids=["known-folder"])
        assert g._resolve_root_folder(FakeService(files)) == "known-folder"
        assert files.create_calls == []

    def test_an_unreachable_configured_id_falls_back(self, monkeypatch):
        """The hand-made folder case: the id is set but 404s under drive.file."""
        monkeypatch.setenv("GDRIVE_PARENT_FOLDER_ID", "made-in-the-browser")
        files = FakeFiles(reachable_ids=[], found=None)
        assert g._resolve_root_folder(FakeService(files)) == "new-root-id"
        assert files.create_calls[0]["name"] == g.ROOT_FOLDER_NAME

    def test_an_existing_app_owned_root_is_reused(self, monkeypatch):
        """Second run onwards: found by name, never created twice."""
        monkeypatch.delenv("GDRIVE_PARENT_FOLDER_ID", raising=False)
        files = FakeFiles(found="already-mine")
        assert g._resolve_root_folder(FakeService(files)) == "already-mine"
        assert files.create_calls == []

    def test_root_is_created_when_nothing_exists(self, monkeypatch):
        monkeypatch.delenv("GDRIVE_PARENT_FOLDER_ID", raising=False)
        files = FakeFiles(found=None)
        assert g._resolve_root_folder(FakeService(files)) == "new-root-id"


class TestScope:
    def test_scope_is_restricted(self):
        """`drive` would put the candidate's whole Drive behind a CI secret."""
        assert g.SCOPES == ["https://www.googleapis.com/auth/drive.file"]

    def test_setup_script_asks_for_the_same_scope(self):
        """A token minted for a different scope than the uploader expects
        fails at upload time, long after the browser step is forgotten."""
        import importlib.util
        import os

        spec = importlib.util.spec_from_file_location(
            "setup_oauth2",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "config", "setup_oauth2.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.SCOPES == g.SCOPES
