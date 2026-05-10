import datetime
import importlib.util
from pathlib import Path

import pytest
import requests
import yaml

from kuper import gitlab_activity as kuper

CLI_PATH = Path(__file__).resolve().parents[2] / "kuper-cli.py"
CLI_SPEC = importlib.util.spec_from_file_location("kuper_cli_script", CLI_PATH)
kuper_cli = importlib.util.module_from_spec(CLI_SPEC)
CLI_SPEC.loader.exec_module(kuper_cli)


def test_get_config_reads_token_and_excludes(tmp_path):
    service = kuper.KuperService()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        'token: "abc123"\nexcludes:\n  - group/repo\n', encoding="utf-8"
    )

    config = service.get_config(str(config_path))

    assert config["token"] == "abc123"
    assert config["excludes"] == ["group/repo"]


def test_get_config_exits_when_file_missing(tmp_path, capsys):
    service = kuper.KuperService()
    missing_path = tmp_path / "missing.yaml"

    with pytest.raises(SystemExit) as exc:
        service.get_config(str(missing_path))

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert f"Error: Config file not found at '{missing_path}'" in captured.out


def test_get_config_exits_when_token_missing(tmp_path, capsys):
    service = kuper.KuperService()
    config_path = tmp_path / "config.yaml"
    config_path.write_text("excludes: []\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        service.get_config(str(config_path))

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert "Error: 'token' not found in config file." in captured.out


def test_get_config_raises_yaml_error_on_invalid_yaml(tmp_path):
    service = kuper.KuperService()
    config_path = tmp_path / "config.yaml"
    config_path.write_text('token: "abc123"\nexcludes: [repo-a\n', encoding="utf-8")

    with pytest.raises(yaml.YAMLError):
        service.get_config(str(config_path))


def test_get_config_raises_type_error_when_file_is_empty(tmp_path):
    service = kuper.KuperService()
    config_path = tmp_path / "config.yaml"
    config_path.write_text("", encoding="utf-8")

    with pytest.raises(TypeError):
        service.get_config(str(config_path))


def test_get_current_user_returns_json(monkeypatch):
    service = kuper.KuperService()
    expected_user = {"email": "dev@example.com"}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return expected_user

    def fake_get(url, headers, timeout):
        assert url == "https://gitlab.example/api/v4/user"
        assert headers["PRIVATE-TOKEN"] == "token-1"
        assert timeout == 10
        return DummyResponse()

    monkeypatch.setattr(kuper.requests, "get", fake_get)

    user = service.get_current_user("https://gitlab.example", "token-1")
    assert user == expected_user


def test_get_current_user_returns_none_on_request_error(monkeypatch, capsys):
    service = kuper.KuperService()

    def fake_get(url, headers, timeout):
        raise requests.exceptions.Timeout("request timed out")

    monkeypatch.setattr(kuper.requests, "get", fake_get)

    user = service.get_current_user("https://gitlab.example", "token-1")

    captured = capsys.readouterr()
    assert user is None
    assert "Error fetching current user details" in captured.out


def test_get_current_user_returns_none_when_raise_for_status_fails(monkeypatch, capsys):
    service = kuper.KuperService()

    class DummyResponse:
        def raise_for_status(self):
            raise requests.exceptions.HTTPError("401 Client Error")

    def fake_get(url, headers, timeout):
        return DummyResponse()

    monkeypatch.setattr(kuper.requests, "get", fake_get)

    user = service.get_current_user("https://gitlab.example", "token-1")

    captured = capsys.readouterr()
    assert user is None
    assert "Error fetching current user details" in captured.out


def test_get_gitlab_commits_returns_empty_when_events_request_fails(monkeypatch):
    service = kuper.KuperService()

    def fake_get(*args, **kwargs):
        raise requests.exceptions.ConnectionError("network issue")

    monkeypatch.setattr(kuper.requests, "get", fake_get)

    commits = service.get_gitlab_commits(
        "https://gitlab.example",
        "token-1",
        datetime.datetime.now(),
        "dev@example.com",
    )

    assert commits == []


def test_generate_report_creates_html(tmp_path, monkeypatch):
    output = kuper.KuperOutput()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "template.html").write_text(
        "<html><body><h1>{{ report_title }}</h1>{{ commits }}</body></html>",
        encoding="utf-8",
    )
    (templates / "commit_template.html").write_text(
        "<article>{{ sha }} {{ branch }} {{ date }} {{ commit_message }} {{ diff }}</article>",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    output.generate_report(
        commits=[
            {
                "repo_name": "team/repo-a",
                "url": "https://example/commit/1",
                "message": "Initial commit\nextra details",
                "diff": "",
                "short_sha": "abc12345",
                "branch": "main",
                "date": "2026-04-19 10:00",
            },
            {
                "repo_name": "team/repo-b",
                "url": "https://example/commit/2",
                "message": "Second commit",
                "diff": "diff --git a b",
                "short_sha": "def67890",
                "branch": "feature/x",
                "date": "2026-04-19 10:15",
            },
        ],
        report_title="Unit Test Report",
        output_filename="report.html",
    )

    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Unit Test Report" in report
    assert "<h2>team/repo-a</h2>" in report
    assert "<h2>team/repo-b</h2>" in report
    assert "Initial commit" in report
    assert "Diff not available." in report
    assert "diff --git a b" in report


def test_generate_report_handles_missing_templates(tmp_path, monkeypatch, capsys):
    output = kuper.KuperOutput()
    monkeypatch.chdir(tmp_path)

    output.generate_report([], "Empty Report", "report.html")

    captured = capsys.readouterr()
    assert "Error reading templates:" in captured.out
    assert not (tmp_path / "report.html").exists()


def test_print_console_output_for_list_and_diff_modes(capsys):
    renderer = kuper.KuperOutput()
    commits = [
        {
            "repo_name": "team/repo",
            "date": "2026-04-19 10:00",
            "branch": "main",
            "short_sha": "abc12345",
            "url": "https://example/commit/1",
            "message": "Commit title\nDetails",
            "diff": "",
        }
    ]

    renderer.print_console_output(commits, fetch_diffs=False)
    rendered_output = capsys.readouterr().out
    assert "===> REPOSITORY: team/repo" in rendered_output
    assert "abc12345" in rendered_output
    assert "'Commit title'" in rendered_output

    renderer.print_console_output(commits, fetch_diffs=True)
    rendered_output = capsys.readouterr().out
    assert "https://example/commit/1" in rendered_output


def test_main_exits_for_invalid_date(monkeypatch):
    monkeypatch.setattr(
        kuper_cli.sys,
        "argv",
        ["kuper.py", "--instance", "https://gitlab.com", "--start-date", "2026/04/19"],
    )

    with pytest.raises(SystemExit) as exc:
        kuper_cli.main()

    assert str(exc.value) == "Error: date must be YYYY-MM-DD"


def test_main_exits_for_too_old_date(monkeypatch):
    old_date = (datetime.datetime.now() - datetime.timedelta(days=40)).strftime(
        "%Y-%m-%d"
    )
    monkeypatch.setattr(
        kuper_cli.sys,
        "argv",
        ["kuper.py", "--instance", "https://gitlab.com", "--start-date", old_date],
    )

    with pytest.raises(SystemExit) as exc:
        kuper_cli.main()

    assert "Error: start-date must be on or after" in str(exc.value)


def test_main_prints_when_no_commits(monkeypatch, capsys):
    start_date = datetime.datetime.now().strftime("%Y-%m-%d")
    monkeypatch.setattr(
        kuper_cli.sys,
        "argv",
        ["kuper.py", "--instance", "https://gitlab.com", "--start-date", start_date],
    )
    monkeypatch.setattr(
        kuper_cli.KuperService,
        "get_config",
        lambda self: {"token": "t1", "excludes": []},
    )
    monkeypatch.setattr(
        kuper_cli.KuperService,
        "get_current_user",
        lambda self, instance, token: {
            "email": "dev@example.com",
            "username": "devuser",
        },
    )
    monkeypatch.setattr(
        kuper_cli.KuperService, "get_gitlab_commits", lambda self, *args, **kwargs: []
    )

    kuper_cli.main()

    out = capsys.readouterr().out
    assert "Fetching commits for dev@example.com since" in out
    assert "No new commits found." in out


def test_main_exits_when_user_profile_is_unavailable(monkeypatch):
    start_date = datetime.datetime.now().strftime("%Y-%m-%d")
    monkeypatch.setattr(
        kuper_cli.sys,
        "argv",
        ["kuper.py", "--instance", "https://gitlab.com", "--start-date", start_date],
    )
    monkeypatch.setattr(
        kuper_cli.KuperService,
        "get_config",
        lambda self: {"token": "t1", "excludes": []},
    )
    monkeypatch.setattr(
        kuper_cli.KuperService, "get_current_user", lambda self, instance, token: None
    )

    with pytest.raises(SystemExit) as exc:
        kuper_cli.main()

    assert str(exc.value) == "Error: Could not fetch user profile"


def test_main_report_flow_calls_report_generation(monkeypatch):
    start_date = datetime.datetime.now().strftime("%Y-%m-%d")
    monkeypatch.setattr(
        kuper_cli.sys,
        "argv",
        [
            "kuper.py",
            "--instance",
            "https://gitlab.com",
            "--start-date",
            start_date,
            "--report",
        ],
    )

    monkeypatch.setattr(
        kuper_cli.KuperService,
        "get_config",
        lambda self: {"token": "t1", "excludes": []},
    )
    monkeypatch.setattr(
        kuper_cli.KuperService,
        "get_current_user",
        lambda self, instance, token: {
            "email": "dev@example.com",
            "username": "devuser",
        },
    )
    monkeypatch.setattr(
        kuper_cli.KuperService,
        "get_gitlab_commits",
        lambda self, *args, **kwargs: [
            {
                "repo_name": "team/repo",
                "date": "2026-04-19 10:00",
                "branch": "main",
                "short_sha": "abc12345",
                "url": "https://example/commit/1",
                "message": "msg",
                "diff": "",
            }
        ],
    )

    called = {"print_console_output": False, "report_args": None}

    def fake_print_console_output(self, commits, fetch_diffs=False):
        called["print_console_output"] = True
        assert fetch_diffs is True
        assert len(commits) == 1

    def fake_generate_report(self, commits, report_title, output_filename):
        called["report_args"] = (commits, report_title, output_filename)

    monkeypatch.setattr(
        kuper_cli.KuperOutput, "print_console_output", fake_print_console_output
    )
    monkeypatch.setattr(kuper_cli.KuperOutput, "generate_report", fake_generate_report)

    kuper_cli.main()

    assert called["print_console_output"] is True
    assert called["report_args"] is not None
    _, report_title, output_filename = called["report_args"]
    assert "Commit Report for dev@example.com" in report_title
    assert output_filename.startswith("commit_report_devuser_")
    assert output_filename.endswith(".html")


def test_main_uses_empty_excludes_when_missing_in_config(monkeypatch):
    start_date = datetime.datetime.now().strftime("%Y-%m-%d")
    monkeypatch.setattr(
        kuper_cli.sys,
        "argv",
        ["kuper.py", "--instance", "https://gitlab.com", "--start-date", start_date],
    )

    monkeypatch.setattr(
        kuper_cli.KuperService, "get_config", lambda self: {"token": "t1"}
    )
    monkeypatch.setattr(
        kuper_cli.KuperService,
        "get_current_user",
        lambda self, instance, token: {
            "email": "dev@example.com",
            "username": "devuser",
        },
    )

    captured = {"excludes": None}

    def fake_get_gitlab_commits(
        self, instance_url, token, start_date_obj, user_email, excludes, fetch_diffs
    ):
        captured["excludes"] = excludes
        return []

    monkeypatch.setattr(
        kuper_cli.KuperService, "get_gitlab_commits", fake_get_gitlab_commits
    )

    kuper_cli.main()

    assert captured["excludes"] == []
