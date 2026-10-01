"""업데이트 — requirements.txt 가 바뀌면 받는 자리에서 깐다(재시작은 run.bat 설치 단계를 건너뛴다)."""
import subprocess
import sys
from types import SimpleNamespace

from app import update


def _fake_git(changed):
    heads = iter(["aaa", "bbb", "bbb", "bbb"])      # 받기 전 · 받은 뒤 · 결과에 적는 것

    def git(*args, timeout=25):
        if args[:2] == ("rev-parse", "--is-inside-work-tree"):
            return 0, "true"
        if args[:1] == ("remote",):
            return 0, "origin"
        if args[:2] == ("rev-parse", "--short"):
            return 0, next(heads)
        if args[:1] == ("log",):
            return 0, "x"
        if args[:1] == ("pull",):
            return 0, ""
        if args[:1] == ("diff",):
            return 0, "\n".join(changed)
        raise AssertionError(args)
    return git


def test_pull_installs_when_requirements_changed(monkeypatch):
    monkeypatch.setattr(update, "_git", _fake_git(["requirements.txt", "app/main.py"]))
    called = []
    monkeypatch.setattr(update, "install_deps", lambda: called.append(1) or {"ok": True})
    r = update.pull()
    assert r["restart"] and r["deps"] == {"ok": True} and called == [1]


def test_pull_skips_install_otherwise(monkeypatch):
    monkeypatch.setattr(update, "_git", _fake_git(["app/web/static/map.html"]))
    monkeypatch.setattr(update, "install_deps", lambda: (_ for _ in ()).throw(AssertionError("불렀다")))
    r = update.pull()
    assert not r["restart"] and "deps" not in r


def test_install_deps_uses_this_python_and_reports_failure(monkeypatch, tmp_path):
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: Could not find a version\nERROR: No matching distribution found for h5py")
    monkeypatch.setattr(subprocess, "run", run)
    r = update.install_deps()
    assert seen["cmd"][:4] == [sys.executable, "-m", "pip", "install"]
    assert "--upgrade" not in seen["cmd"]
    assert r["ok"] is False and "h5py" in r["error"]


def test_install_deps_marks_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "base"))
    assert update.install_deps() == {"ok": True}
    assert (tmp_path / ".installed").exists()       # run.bat 이 다음에 또 깔지 않게
