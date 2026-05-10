import datetime
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import pytest
import requests

INSTANCE_URL = "https://gitlab.com"
PROJECT_PATH = "mrachuta-public/kuper-e2e"
TARGET_BRANCH = "main"


def _now_id(prefix):
    return f"{prefix}-{time.time_ns()}"


@pytest.fixture
def env_tokens():
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        pytest.skip("Missing .env file with GitLab token")

    tokens = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        tokens[key.strip()] = value.strip()
    return tokens


@pytest.fixture
def api_token(env_tokens):
    token = env_tokens.get("API_TEST_TOKEN")
    if not token:
        pytest.skip("API_TEST_TOKEN is missing in .env")
    return token


@pytest.fixture
def sa_token(env_tokens):
    token = env_tokens.get("API_E2E_TEST_SA_TOKEN")
    if not token:
        pytest.skip("API_E2E_TEST_SA_TOKEN is missing in .env")
    return token


def api_request(
    method, token, path, *, expected_status=200, params=None, json_data=None
):
    headers = {"PRIVATE-TOKEN": token}
    url = f"{INSTANCE_URL}{path}"
    response = requests.request(
        method,
        url,
        headers=headers,
        params=params,
        json=json_data,
        timeout=30,
    )

    assert response.status_code == expected_status, (
        f"{method} {path} failed with status {response.status_code}. "
        f"Response: {response.text}"
    )

    if response.text:
        return response.json()
    return {}


def merge_mr_with_retry(token, project_id, mr_iid, *, squash=False, timeout_seconds=90):
    headers = {"PRIVATE-TOKEN": token}
    merge_path = f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/merge"
    merge_url = f"{INSTANCE_URL}{merge_path}"
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        response = requests.put(
            merge_url,
            headers=headers,
            json={"should_remove_source_branch": True, "squash": squash},
            timeout=30,
        )
        if response.status_code == 200:
            return response.json()
        if response.status_code in (405, 406):
            time.sleep(2)
            continue
        raise AssertionError(
            f"PUT {merge_path} failed with status {response.status_code}. "
            f"Response: {response.text}"
        )

    raise AssertionError(
        f"Merge request {mr_iid} was not mergeable within {timeout_seconds}s"
    )


def close_mr_best_effort(token, project_id, mr_iid):
    try:
        requests.put(
            f"{INSTANCE_URL}/api/v4/projects/{project_id}/merge_requests/{mr_iid}",
            headers={"PRIVATE-TOKEN": token},
            params={"state_event": "close"},
            timeout=30,
        )
    except Exception:
        pass


def run_git(repo_dir, token, *args):
    result = subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()

    output = f"{result.stdout}\n{result.stderr}".replace(token, "***")
    raise AssertionError(
        f"git {' '.join(args)} failed with exit code {result.returncode}:\n{output}"
    )


def run_kuper_and_collect_output(tmp_path, api_token):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f'token: "{api_token}"\nexcludes: []\n', encoding="utf-8")

    start_date = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).strftime("%Y-%m-%d")
    script = Path(__file__).resolve().parents[2] / "kuper-cli.py"

    return subprocess.run(
        [
            sys.executable,
            str(script),
            "--instance",
            INSTANCE_URL,
            "--start-date",
            start_date,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def listed_commit_lines(output):
    return [line for line in output.splitlines() if " | " in line]


def duplicate_skip_lines(output):
    return [
        line
        for line in output.splitlines()
        if "INFO: Skipping duplicate commit " in line
    ]


def get_project_and_user(api_token):
    encoded_project = urllib.parse.quote_plus(PROJECT_PATH)
    project = api_request("GET", api_token, f"/api/v4/projects/{encoded_project}")
    assert (
        project.get("default_branch") == TARGET_BRANCH
    ), f"Expected default branch '{TARGET_BRANCH}', got '{project.get('default_branch')}'"
    user = api_request("GET", api_token, "/api/v4/user")
    return project["id"], user


def create_mr(api_token, project_id, branch_name, title):
    return api_request(
        "POST",
        api_token,
        f"/api/v4/projects/{project_id}/merge_requests",
        expected_status=201,
        json_data={
            "source_branch": branch_name,
            "target_branch": TARGET_BRANCH,
            "title": title,
            "remove_source_branch": True,
        },
    )


def create_and_push_flow_commits(tmp_path, api_token, user, run_id):
    branch_name = f"test/{run_id}"
    base_dir = f"tests-artifacts/{run_id}"

    repo_dir = tmp_path / f"repo-{run_id}"
    repo_dir.mkdir()

    safe_token = urllib.parse.quote(api_token, safe="")
    remote_url = f"https://oauth2:{safe_token}@gitlab.com/{PROJECT_PATH}.git"

    run_git(repo_dir, api_token, "init")
    run_git(
        repo_dir, api_token, "config", "user.name", user.get("name") or user["username"]
    )
    run_git(repo_dir, api_token, "config", "user.email", user["email"])
    run_git(repo_dir, api_token, "remote", "add", "origin", remote_url)
    run_git(repo_dir, api_token, "fetch", "origin", TARGET_BRANCH)
    run_git(
        repo_dir, api_token, "checkout", "-b", branch_name, f"origin/{TARGET_BRANCH}"
    )

    created_commits = []

    def commit(message):
        run_git(repo_dir, api_token, "add", "-A")
        run_git(repo_dir, api_token, "commit", "-m", f"[{run_id}] {message}")
        created_commits.append(
            run_git(repo_dir, api_token, "rev-parse", "--short=8", "HEAD")
        )

    artifact_dir = repo_dir / base_dir
    artifact_dir.mkdir(parents=True, exist_ok=True)

    (artifact_dir / "story.txt").write_text("line 1\n", encoding="utf-8")
    commit("Create story file")

    (artifact_dir / "story.txt").write_text("line 1\nline 2\n", encoding="utf-8")
    commit("Update story file")

    (artifact_dir / "draft.txt").write_text("draft\n", encoding="utf-8")
    commit("Create draft file")

    run_git(
        repo_dir,
        api_token,
        "mv",
        f"{base_dir}/draft.txt",
        f"{base_dir}/draft-renamed.txt",
    )
    commit("Rename draft file")

    run_git(repo_dir, api_token, "rm", f"{base_dir}/draft-renamed.txt")
    commit("Delete draft file")

    run_git(repo_dir, api_token, "push", "-u", "origin", branch_name)

    return branch_name, created_commits


def wait_for_kuper_output(tmp_path, api_token, required_shas, forbidden_sha=None):
    result = None
    commit_lines = []

    for _ in range(12):
        result = run_kuper_and_collect_output(tmp_path, api_token)
        commit_lines = listed_commit_lines(result.stdout)
        listed_text = "\n".join(commit_lines)

        if result.returncode != 0:
            time.sleep(5)
            continue

        originals_present = all(sha in listed_text for sha in required_shas)
        forbidden_absent = not forbidden_sha or forbidden_sha not in listed_text
        if originals_present and forbidden_absent:
            break

        time.sleep(5)

    assert result is not None
    assert result.returncode == 0, result.stdout + "\n" + result.stderr

    listed_text = "\n".join(commit_lines)
    for sha in required_shas:
        assert sha in listed_text, f"Missing commit {sha} in output:\n{result.stdout}"

    if forbidden_sha:
        assert (
            forbidden_sha not in listed_text
        ), f"Squash commit {forbidden_sha} should not be listed in output:\n{result.stdout}"
    return result


@pytest.mark.e2e
def test_first_e2e_flow_lists_all_commits_created_in_mr(tmp_path, api_token):
    project_id, user = get_project_and_user(api_token)
    run_id = _now_id("e2e")

    branch_name, created_commits = create_and_push_flow_commits(
        tmp_path, api_token, user, run_id
    )

    mr = create_mr(api_token, project_id, branch_name, f"[{run_id}] e2e flow")

    merge_mr_with_retry(api_token, project_id, mr["iid"], squash=False)
    wait_for_kuper_output(tmp_path, api_token, created_commits)


@pytest.mark.e2e
def test_second_e2e_flow_squash_merge_keeps_original_commits_and_skips_squash(
    tmp_path, api_token
):
    project_id, user = get_project_and_user(api_token)
    run_id = _now_id("e2e-squash")

    branch_name, created_commits = create_and_push_flow_commits(
        tmp_path, api_token, user, run_id
    )

    mr = create_mr(api_token, project_id, branch_name, f"[{run_id}] squash e2e flow")

    merge_response = merge_mr_with_retry(api_token, project_id, mr["iid"], squash=True)
    squash_sha = merge_response.get("squash_commit_sha")

    if not squash_sha:
        mr_details = api_request(
            "GET",
            api_token,
            f"/api/v4/projects/{project_id}/merge_requests/{mr['iid']}",
        )
        squash_sha = mr_details.get("squash_commit_sha")

    assert squash_sha, "Expected squash_commit_sha after squash merge"
    wait_for_kuper_output(
        tmp_path, api_token, created_commits, forbidden_sha=squash_sha[:8]
    )


@pytest.mark.e2e
def test_third_e2e_flow_excludes_duplicates_and_lists_commits_once(tmp_path, api_token):
    project_id, user = get_project_and_user(api_token)
    run_id = _now_id("e2e-dup")

    branch_name, created_commits = create_and_push_flow_commits(
        tmp_path, api_token, user, run_id
    )

    mr = create_mr(
        api_token, project_id, branch_name, f"[{run_id}] duplicate check flow"
    )

    merge_mr_with_retry(api_token, project_id, mr["iid"], squash=False)
    result = wait_for_kuper_output(tmp_path, api_token, created_commits)

    commit_lines = listed_commit_lines(result.stdout)
    for sha in created_commits:
        matching_rows = [line for line in commit_lines if f"|  {sha}  |" in line]
        assert (
            len(matching_rows) == 1
        ), f"Commit {sha} should be listed exactly once, output was:\n{result.stdout}"

    skips = duplicate_skip_lines(result.stdout)
    for sha in created_commits:
        matching_skip = [
            line
            for line in skips
            if sha in line and "already processed in branch 'main'" in line
        ]
        assert (
            matching_skip
        ), f"Expected duplicate skip info for commit {sha} pointing to 'main', output was:\n{result.stdout}"


@pytest.mark.e2e
def test_fourth_e2e_flow_commits_captured_when_mr_merged_by_another_user(
    tmp_path, api_token, sa_token
):
    project_id, user = get_project_and_user(api_token)
    run_id = _now_id("e2e-merged-by-sa")

    branch_name, created_commits = create_and_push_flow_commits(
        tmp_path, api_token, user, run_id
    )

    mr = create_mr(
        api_token, project_id, branch_name, f"[{run_id}] merged by service account flow"
    )

    try:
        merge_mr_with_retry(sa_token, project_id, mr["iid"], squash=False)
    except AssertionError as exc:
        message = str(exc)
        if "primary email address is not confirmed" in message:
            close_mr_best_effort(api_token, project_id, mr["iid"])
            pytest.skip(
                "API_E2E_TEST_SA_TOKEN account cannot merge yet because GitLab reports "
                "its primary email is not confirmed."
            )
        if "insufficient_scope" in message:
            close_mr_best_effort(api_token, project_id, mr["iid"])
            pytest.skip(
                "API_E2E_TEST_SA_TOKEN cannot merge MR because token scope/role is insufficient "
                "(GitLab returned insufficient_scope)."
            )
        raise

    wait_for_kuper_output(tmp_path, api_token, created_commits)


@pytest.mark.e2e
def test_fifth_e2e_flow_merger_does_not_get_merge_commit_as_contribution(
    tmp_path, api_token, sa_token
):
    project_id, sa_user = get_project_and_user(sa_token)
    run_id = _now_id("e2e-api-merger-no-credit")

    branch_name, sa_created_commits = create_and_push_flow_commits(
        tmp_path, sa_token, sa_user, run_id
    )
    mr = create_mr(
        sa_token, project_id, branch_name, f"[{run_id}] api merger should not get credit"
    )

    merge_response = None
    try:
        merge_response = merge_mr_with_retry(api_token, project_id, mr["iid"], squash=False)
    except AssertionError as exc:
        message = str(exc)
        if "primary email address is not confirmed" in message:
            close_mr_best_effort(sa_token, project_id, mr["iid"])
            pytest.skip(
                "API_TEST_TOKEN account cannot merge yet because GitLab reports "
                "its primary email is not confirmed."
            )
        if "insufficient_scope" in message:
            close_mr_best_effort(sa_token, project_id, mr["iid"])
            pytest.skip(
                "API_TEST_TOKEN cannot merge MR because token scope/role is insufficient "
                "(GitLab returned insufficient_scope)."
            )
        raise

    merge_commit_sha = merge_response.get("merge_commit_sha") if merge_response else None
    if not merge_commit_sha:
        mr_details = api_request(
            "GET",
            sa_token,
            f"/api/v4/projects/{project_id}/merge_requests/{mr['iid']}",
        )
        merge_commit_sha = mr_details.get("merge_commit_sha")

    assert merge_commit_sha, "Expected merge_commit_sha after regular merge"
    api_result = run_kuper_and_collect_output(tmp_path, api_token)
    assert api_result.returncode == 0, api_result.stdout + "\n" + api_result.stderr

    commit_lines = listed_commit_lines(api_result.stdout)
    listed_text = "\n".join(commit_lines)

    for sha in sa_created_commits:
        assert (
            sha not in listed_text
        ), f"API user should not see SA commit {sha} as own contribution:\n{api_result.stdout}"

    assert (
        merge_commit_sha[:8] not in listed_text
    ), f"API user should not see merge commit {merge_commit_sha[:8]} as own contribution:\n{api_result.stdout}"
