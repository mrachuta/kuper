#!/usr/bin/env python3

import datetime
import os
import sys

import requests
import yaml

RUNNER = r"""
⠀⠀⠀⠀⠀⠀⠀⢀⣀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⢀⣴⣿⣿⣿⣿⣿⣿⣦⡀⠀⠀⠀⠀⠀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⣰⣿⣿⠸⢿⣿⣿⣿⣿⣿⣿⣦⡀⠀⠰⠯⠟⠛⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⢰⣿⡏⣴⢸⣶⣼⣿⣿⣿⡿⠿⠿⣷⡄⢿⣟⣖⠒⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⣿⣿⣿⣶⢠⣬⢹⣿⡿⠋⣠⣶⣦⣈⠻⣦⠈⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⢻⣿⣈⠻⠸⢋⣼⡿⠁⣼⡿⠻⣿⣿⣷⣄⣠⣴⠆⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠻⣿⣿⢸⣿⡟⠀⢸⣿⣿⣦⣄⡉⠛⠛⠛⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠈⠛⠿⠋⠀⠀⢻⣿⣿⣿⣿⣿⣧⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⣀⣀⣤⣶⣄⠀⠀⠈⠿⢿⣿⣿⣿⣿⣿⣶⣤⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠸⠟⠛⠉⠻⣿⣧⡀⣼⣶⣤⣄⠉⠉⠛⠛⠻⢿⣿⣦⡀⠀⠀⠀⣠⡀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠙⢿⣿⣿⡿⠋⠁⠀⠀ ⠀⠀⠀ ⠀⠙⢿⣿⣆⣠⣾⠟⠁⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠁⠀⠀⠀⠀⠀⠀⠀ ⠀⠀⠀  ⠀ ⠻⣿⡿⠁⠀⠀⠀⠀
KUPer :: run for your commmits :: (c) 2026
"""


class KuperService:
    """Business operations for config loading and GitLab commit collection."""

    def __init__(self, http_client=requests, yaml_module=yaml):
        self.http_client = http_client
        self.yaml_module = yaml_module

    def get_config(self, config_path="config.yaml"):
        """Read the configuration file."""
        if not os.path.exists(config_path):
            print(f"Error: Config file not found at '{config_path}'")
            sys.exit(1)

        with open(config_path, "r") as config_file:
            config = self.yaml_module.safe_load(config_file)

        if "token" not in config:
            print("Error: 'token' not found in config file.")
            sys.exit(1)

        return config

    def get_current_user(self, instance_url, token):
        """Fetch current user's profile details."""
        headers = {"PRIVATE-TOKEN": token}
        user_url = f"{instance_url}/api/v4/user"
        try:
            response = self.http_client.get(user_url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as error:
            print(f"Error fetching current user details: {error}")
            return None

    def get_gitlab_commits(
        self,
        instance_url,
        token,
        start_date,
        user_email,
        excludes=None,
        fetch_diffs=False,
    ):
        """Fetch user's commits from GitLab API."""
        if excludes is None:
            excludes = []
        headers = {"PRIVATE-TOKEN": token}

        projects_to_scan = {}
        skipped_repos = set()
        mr_commits = []
        squashed_shas = set()

        events_params = {"after": start_date.strftime("%Y-%m-%d"), "per_page": 100}
        events_url = f"{instance_url}/api/v4/events"
        while events_url:
            try:
                response = self.http_client.get(
                    events_url, headers=headers, params=events_params, timeout=20
                )
                response.raise_for_status()
                for event in response.json():
                    project_id = event.get("project_id")
                    if not project_id:
                        continue
                    if project_id not in projects_to_scan:
                        projects_to_scan[project_id] = {"branches": set()}
                    push_ref = event.get("push_data", {}).get("ref")
                    if push_ref and push_ref.startswith("refs/heads/"):
                        branch = push_ref.replace("refs/heads/", "", 1)
                        projects_to_scan[project_id]["branches"].add(branch)
                events_url = response.links.get("next", {}).get("url")
                events_params = None
            except requests.exceptions.RequestException:
                break

        for pid in list(projects_to_scan.keys()):
            mr_url = f"{instance_url}/api/v4/projects/{pid}/merge_requests"
            mr_params = {
                "updated_after": start_date.strftime("%Y-%m-%dT00:00:00Z"),
                "per_page": 100,
            }
            try:
                response = self.http_client.get(
                    mr_url, headers=headers, params=mr_params, timeout=20
                )
                if response.status_code == 200:
                    for mr in response.json():
                        projects_to_scan[pid]["branches"].add(mr.get("target_branch"))
                        if mr.get("squash_commit_sha"):
                            squashed_shas.add(mr.get("squash_commit_sha")[:8])

                        mrc_url = (
                            f"{instance_url}/api/v4/projects/{pid}/"
                            f"merge_requests/{mr['iid']}/commits"
                        )
                        try:
                            mrc_resp = self.http_client.get(
                                mrc_url, headers=headers, timeout=15
                            )
                            if mrc_resp.status_code == 200:
                                for commit in mrc_resp.json():
                                    if commit.get("author_email") == user_email:
                                        commit["project_id"] = pid
                                        commit["target_branch"] = mr.get(
                                            "target_branch"
                                        )
                                        mr_commits.append(commit)
                        except Exception:
                            pass
            except Exception:
                pass

        try:
            response = self.http_client.get(
                f"{instance_url}/api/v4/projects?membership=true&per_page=100",
                headers=headers,
                timeout=20,
            )
            if response.status_code == 200:
                for project in response.json():
                    pid = project.get("id")
                    if pid not in projects_to_scan:
                        projects_to_scan[pid] = {"branches": set()}
                    projects_to_scan[pid]["path_with_namespace"] = project.get(
                        "path_with_namespace"
                    )
        except Exception:
            pass

        active_branches = []
        for pid, data in projects_to_scan.items():
            if "path_with_namespace" not in data:
                try:
                    response = self.http_client.get(
                        f"{instance_url}/api/v4/projects/{pid}",
                        headers=headers,
                        timeout=10,
                    )
                    if response.status_code == 200:
                        data["path_with_namespace"] = response.json().get(
                            "path_with_namespace"
                        )
                except Exception:
                    data["path_with_namespace"] = "Unknown Project"

            repo_name = data.get("path_with_namespace", "Unknown Project")
            if any(repo_name.startswith(exclude) for exclude in excludes):
                if repo_name not in skipped_repos:
                    print(f"INFO: Skipping repository '{repo_name}' (excluded).")
                    skipped_repos.add(repo_name)
                continue

            for branch in data["branches"]:
                if branch:
                    active_branches.append((pid, repo_name, branch))

        all_commits = []
        processed_shas = {}

        def process_commit(commit, pid, repo_name, branch, is_mr=False):
            short_sha = commit["short_id"]
            if short_sha in processed_shas:
                previous_branch = processed_shas[short_sha]
                reason = f"already processed in branch '{previous_branch}'"
                if is_mr:
                    reason = (
                        "already processed as part of MR to target branch "
                        f"'{previous_branch}'"
                    )
                print(
                    f"INFO: Skipping duplicate commit {short_sha} "
                    f"in {repo_name} ({reason})"
                )
                return

            if short_sha in squashed_shas:
                print(
                    f"INFO: Skipping squashed commit {short_sha} in {repo_name} "
                    "(result of merge request with squash)"
                )
                return

            processed_shas[short_sha] = branch
            diff_text = ""
            if fetch_diffs:
                try:
                    response = self.http_client.get(
                        f"{instance_url}/api/v4/projects/{pid}/repository/commits/"
                        f"{commit['id']}/diff",
                        headers=headers,
                        timeout=15,
                    )
                    if response.status_code == 200:
                        diff_parts = []
                        for diff in response.json():
                            old_path = diff.get("old_path")
                            new_path = diff.get("new_path")
                            if diff.get("renamed_file"):
                                header = f"--- [RENAMED] {old_path} -> {new_path} ---"
                            elif diff.get("deleted_file"):
                                header = f"--- [DELETED] {old_path} ---"
                            elif diff.get("new_file"):
                                header = f"--- [ADDED] {new_path} ---"
                            else:
                                header = f"--- [MODIFIED] {new_path or old_path} ---"

                            old_mode = diff.get("a_mode")
                            new_mode = diff.get("b_mode")
                            if old_mode and new_mode and old_mode != new_mode:
                                header = f"{header}\nmode: {old_mode} -> {new_mode}"
                            diff_parts.append(f"{header}\n{diff.get('diff')}")
                        diff_text = "\n\n".join(diff_parts)
                except Exception:
                    pass

            all_commits.append(
                {
                    "repo_name": repo_name,
                    "date": datetime.datetime.fromisoformat(
                        commit["created_at"].replace("Z", "+00:00")
                    ).strftime("%Y-%m-%d %H:%M"),
                    "branch": branch,
                    "short_sha": short_sha,
                    "url": commit["web_url"],
                    "message": commit["message"].strip(),
                    "diff": diff_text,
                }
            )

        for commit in mr_commits:
            pid = commit["project_id"]
            repo_name = projects_to_scan.get(pid, {}).get(
                "path_with_namespace", "Unknown"
            )
            process_commit(commit, pid, repo_name, commit["target_branch"], is_mr=True)

        for pid, repo_name, branch in active_branches:
            print(f"Fetching commits for '{repo_name}' on branch '{branch}'...")
            params = {
                "ref_name": branch,
                "since": start_date.isoformat(),
                "author": user_email,
                "per_page": 100,
            }
            url = f"{instance_url}/api/v4/projects/{pid}/repository/commits"
            while url:
                try:
                    response = self.http_client.get(
                        url, headers=headers, params=params, timeout=20
                    )
                    response.raise_for_status()
                    commits = response.json()
                    if not commits:
                        break
                    for commit in commits:
                        process_commit(commit, pid, repo_name, branch)
                    url = response.links.get("next", {}).get("url")
                    params = None
                except Exception:
                    break

        return sorted(all_commits, key=lambda item: (item["repo_name"], item["date"]))


class KuperOutput:
    """Output concerns for rendering report and console display."""

    def generate_report(
        self, commits, report_title, output_filename="commits_report.html"
    ):
        """Generate an HTML report from commits."""
        try:
            with open("templates/template.html", "r") as main_file:
                main_template = main_file.read()
            with open("templates/commit_template.html", "r") as commit_file:
                commit_template = commit_file.read()
        except Exception as error:
            print(f"Error reading templates: {error}")
            return

        blocks = []
        last_repo = None
        for commit in commits:
            if commit["repo_name"] != last_repo:
                if last_repo:
                    blocks.append("</div>")
                blocks.append(f"<h2>{commit['repo_name']}</h2><div class='repo-block'>")
                last_repo = commit["repo_name"]

            html = commit_template.replace("{{ commit_url }}", commit["url"])
            html = html.replace(
                "{{ commit_message }}", commit["message"].split("\n")[0]
            )
            html = html.replace(
                "{{ diff }}", commit.get("diff") or "Diff not available."
            )
            html = html.replace("{{ sha }}", commit["short_sha"])
            html = html.replace("{{ branch }}", commit["branch"])
            html = html.replace("{{ date }}", commit["date"])
            blocks.append(html)

        if last_repo:
            blocks.append("</div>")

        final_report = main_template.replace(
            "{{ report_title }}", report_title
        ).replace("{{ commits }}", "\n".join(blocks))
        with open(output_filename, "w") as out_file:
            out_file.write(final_report)

    def print_console_output(self, commits, fetch_diffs=False):
        """Print commits to console."""
        last_repo = None
        for commit in commits:
            if commit["repo_name"] != last_repo:
                print(f"\n===> REPOSITORY: {commit['repo_name']}")
                last_repo = commit["repo_name"]
            if fetch_diffs:
                print(commit["url"])
            else:
                message = commit["message"].splitlines()[0]
                print(
                    f"{commit['date']}  |  {commit['short_sha']}  |  "
                    f"{commit['branch']}  |  {commit['url']}  |  '{message}'"
                )
