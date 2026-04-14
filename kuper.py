#!/usr/bin/env python3

import os
import sys
import yaml
import requests
import argparse
import datetime

RUNNER = r"""
⠀⠀⠀⠀⠀⠀⠀⢀⣀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⢀⣴⣿⣿⣿⣿⣿⣿⣦⡀⠀⠀⠀⠀⠀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⣰⣿⣿⠸⢿⣿⣿⣿⣿⣿⣿⣦⡀⠀⠰⠯⠟⠛⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⢰⣿⡏⣴⢸⣶⣼⣿⣿⣿⡿⠿⠿⣷⡄⢿⣟⣖⠒⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⣿⣿⣿⣶⢠⣬⢹⣿⡿⠋⣠⣶⣦⣈⠻⣦⠈⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⢻⣿⣈⠻⠸⢋⣼⡿⠁⣼⡿⠻⣿⣿⣷⣄⣠⣴⠆⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠻⣿⣿⢸⣿⡟⠀⢸⣿⣿⣦⣄⡉⠛⠛⠛⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠈⠛⠿⠋⠀⠀⢻⣿⣿⣿⣿⣿⣧⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⣀⣀⣤⣶⣄⠀⠀⠈⠿⢿⣿⣿⣿⣿⣿⣶⣤⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠸⠟⠛⠉⠻⣿⣧⡀⣼⣶⣤⣄⠉⠉⠛⠛⠻⢿⣿⣦⡀⠀⠀⠀⣠⡀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠙⢿⣿⣿⡿⠋⠁⠀⠀⠀⠀⠀⠀⠙⢿⣿⣆⣠⣾⠟⠁⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠻⣿⡿⠁⠀⠀⠀⠀
KUPer :: run for your commmits :: (c) 2026
"""


def get_config(config_path="config.yaml"):
    """Reads the configuration file."""
    if not os.path.exists(config_path):
        print(f"Error: Config file not found at '{config_path}'")
        sys.exit(1)
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    if "token" not in config:
        print("Error: 'token' not found in config file.")
        sys.exit(1)
    return config


def get_current_user(instance_url, token):
    """Fetches the current user's profile details."""
    headers = {"PRIVATE-TOKEN": token}
    user_url = f"{instance_url}/api/v4/user"
    try:
        response = requests.get(user_url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching current user details: {e}")
        return None


def get_gitlab_commits(
    instance_url, token, start_date, user_email, excludes=None, fetch_diffs=False
):
    """Fetches user's commits from GitLab API by discovering active projects,
    scanning authored MRs, and exploring member projects."""
    if excludes is None:
        excludes = []
    headers = {"PRIVATE-TOKEN": token}

    # mapping of project_id -> { "path_with_namespace": "...", "branches": {"...", "..."} }
    projects_to_scan = {}
    skipped_repos = set()
    mr_commits = []  # Explicitly store commits found in MRs
    squashed_shas = set()

    # --- Step 1: Discovery ---

    # 1.1 Events API
    events_params = {"after": start_date.strftime("%Y-%m-%d"), "per_page": 100}
    events_url = f"{instance_url}/api/v4/events"
    while events_url:
        try:
            response = requests.get(events_url, headers=headers, params=events_params, timeout=20)
            response.raise_for_status()
            for event in response.json():
                project_id = event.get("project_id")
                if not project_id: continue
                if project_id not in projects_to_scan: projects_to_scan[project_id] = {"branches": set()}
                if "pushed" in event.get("action_name", ""):
                    branch = event.get("push_data", {}).get("ref", "").replace("refs/heads/", "")
                    if branch: projects_to_scan[project_id]["branches"].add(branch)
            events_url = response.links.get("next", {}).get("url")
            events_params = None
        except requests.exceptions.RequestException: break

    # 1.2 Authored Merge Requests (Crucial for squashed/merged work)
    mr_params = {
        "scope": "created_by_me",
        "updated_after": start_date.strftime("%Y-%m-%dT00:00:00Z"),
        "per_page": 100,
    }
    mr_url = f"{instance_url}/api/v4/merge_requests"
    try:
        response = requests.get(mr_url, headers=headers, params=mr_params, timeout=20)
        if response.status_code == 200:
            for mr in response.json():
                pid = mr.get("project_id")
                if not pid: continue
                if pid not in projects_to_scan: projects_to_scan[pid] = {"branches": set()}
                projects_to_scan[pid]["branches"].add(mr.get("target_branch"))
                
                # Record squash SHA to exclude it later
                if mr.get("squash_commit_sha"):
                    squashed_shas.add(mr.get("squash_commit_sha")[:8])

                # Fetch original commits from the MR itself (works even if branch is deleted)
                mr_commits_url = f"{instance_url}/api/v4/projects/{pid}/merge_requests/{mr['iid']}/commits"
                try:
                    mrc_resp = requests.get(mr_commits_url, headers=headers, timeout=15)
                    if mrc_resp.status_code == 200:
                        for c in mrc_resp.json():
                            if c.get("author_email") == user_email:
                                c["project_id"] = pid
                                c["branch_hint"] = f"mr-{mr['iid']}"
                                mr_commits.append(c)
                except Exception: pass
    except requests.exceptions.RequestException: pass

    # 1.3 Membership
    try:
        response = requests.get(f"{instance_url}/api/v4/projects?membership=true&per_page=100", headers=headers, timeout=20)
        if response.status_code == 200:
            for proj in response.json():
                pid = proj.get("id")
                if pid not in projects_to_scan: projects_to_scan[pid] = {"branches": set()}
                projects_to_scan[pid]["branches"].add(proj.get("default_branch"))
                projects_to_scan[pid]["path_with_namespace"] = proj.get("path_with_namespace")
    except Exception: pass

    # --- Step 2: Resolve names and finalize branch list ---
    branch_order = ["master", "main", "prod", "nonprod", "develop", "development"]
    active_branches = []

    for pid, data in projects_to_scan.items():
        if "path_with_namespace" not in data:
            try:
                r = requests.get(f"{instance_url}/api/v4/projects/{pid}", headers=headers, timeout=10)
                if r.status_code == 200:
                    data["path_with_namespace"] = r.json().get("path_with_namespace")
                    data["branches"].add(r.json().get("default_branch"))
            except Exception: data["path_with_namespace"] = "Unknown Project"
        
        repo_name = data.get("path_with_namespace", "Unknown Project")
        
        # Excludes
        if any(repo_name.startswith(ex) for ex in excludes):
            if repo_name not in skipped_repos:
                print(f"INFO: Skipping repository '{repo_name}' (excluded).")
                skipped_repos.add(repo_name)
            continue

        # Add priority branches to every project
        for b in branch_order: data["branches"].add(b)
        for b in data["branches"]:
            if b: active_branches.append((pid, repo_name, b))

    # --- Step 3: Fetch and Deduplicate Commits ---
    all_commits = []
    processed_shas = set()

    def process_commit(commit, pid, repo_name, branch):
        short_sha = commit["short_id"]
        if short_sha in processed_shas:
            print(f"INFO: Skipping duplicate commit {short_sha} in {repo_name} (already processed)")
            return
        if short_sha in squashed_shas:
            print(f"INFO: Skipping squashed commit {short_sha} in {repo_name}")
            return
        
        processed_shas.add(short_sha)
        
        # Diff handling
        diff_text = ""
        if fetch_diffs:
            try:
                d_resp = requests.get(f"{instance_url}/api/v4/projects/{pid}/repository/commits/{commit['id']}/diff", headers=headers, timeout=15)
                if d_resp.status_code == 200:
                    diff_parts = []
                    for d in d_resp.json():
                        header = f"--- {d.get('new_path') or d.get('old_path')} ---"
                        diff_parts.append(f"{header}\n{d.get('diff')}")
                    diff_text = "\n\n".join(diff_parts)
            except Exception: pass

        all_commits.append({
            "repo_name": repo_name,
            "date": datetime.datetime.fromisoformat(commit["created_at"].replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M"),
            "branch": branch,
            "short_sha": short_sha,
            "url": commit["web_url"],
            "message": commit["message"].strip(),
            "diff": diff_text
        })

    # Process MR commits first (they are specific targets)
    for c in mr_commits:
        pid = c["project_id"]
        repo = projects_to_scan.get(pid, {}).get("path_with_namespace", "Unknown")
        process_commit(c, pid, repo, c["branch_hint"])

    # Process discovered branches
    sorted_branches = sorted(active_branches, key=lambda x: (x[1], branch_order.index(x[2]) if x[2] in branch_order else 99, x[2]))
    for pid, repo, branch in sorted_branches:
        print(f"Fetching commits for '{repo}' on branch '{branch}'...")
        params = {"ref_name": branch, "since": start_date.isoformat(), "author": user_email, "per_page": 100}
        url = f"{instance_url}/api/v4/projects/{pid}/repository/commits"
        while url:
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=20)
                resp.raise_for_status()
                commits = resp.json()
                if not commits: break
                for c in commits: process_commit(c, pid, repo, branch)
                url = resp.links.get("next", {}).get("url")
                params = None
            except Exception: break

    return sorted(all_commits, key=lambda x: (x["repo_name"], x["date"]))


def generate_report(commits, report_title, output_filename="commits_report.html"):
    """Generates an HTML report from the commits."""
    try:
        with open("templates/template.html", "r") as f: main_template = f.read()
        with open("templates/commit_template.html", "r") as f: commit_template = f.read()
    except Exception as e:
        print(f"Error reading templates: {e}")
        return

    blocks = []
    last_repo = None
    for c in commits:
        if c["repo_name"] != last_repo:
            if last_repo: blocks.append("</div>")
            blocks.append(f"<h2>{c['repo_name']}</h2><div class='repo-block'>")
            last_repo = c["repo_name"]
        
        html = commit_template.replace("{{ commit_url }}", c["url"])
        html = html.replace("{{ commit_message }}", c["message"].split("\n")[0])
        html = html.replace("{{ diff }}", c.get("diff") or "Diff not available.")
        html = html.replace("{{ sha }}", c["short_sha"])
        html = html.replace("{{ branch }}", c["branch"])
        html = html.replace("{{ date }}", c["date"])
        blocks.append(html)
    
    if last_repo: blocks.append("</div>")
    
    final = main_template.replace("{{ report_title }}", report_title) \
                        .replace("{{ commits }}", "\n".join(blocks))
    with open(output_filename, "w") as f: f.write(final)


def print_console_output(commits, fetch_diffs=False):
    """Prints the commits to the console."""
    last_repo = None
    for c in commits:
        if c["repo_name"] != last_repo:
            print(f"\n===> REPOSITORY: {c['repo_name']}")
            last_repo = c["repo_name"]
        if fetch_diffs: print(c["url"])
        else: print(f"{c['date']}  |  {c['short_sha']}  |  {c['branch']}  |  {c['url']}  |  '{c['message'].splitlines()[0]}'")


def main():
    """Main function."""
    print(RUNNER)
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=True)
    parser.add_argument("--start-date", "-s", required=True)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    try: start_date = datetime.datetime.strptime(args.start_date, "%Y-%m-%d")
    except ValueError: sys.exit("Error: date must be YYYY-MM-DD")

    limit = datetime.datetime.now() - datetime.timedelta(days=32)
    if start_date < limit: sys.exit(f"Error: start-date must be on or after {limit.strftime('%Y-%m-%d')}")

    config = get_config()
    token, excludes = config.get("token"), config.get("excludes", [])
    user = get_current_user(args.instance.rstrip("/"), token)
    if not user: sys.exit("Error: Could not fetch user profile")

    print(f"Fetching commits for {user['email']} since {args.start_date}...")
    commits = get_gitlab_commits(args.instance.rstrip("/"), token, start_date, user["email"], excludes, args.report)

    if not commits:
        print("No new commits found.")
        return

    print_console_output(commits, args.report)
    if args.report:
        now = datetime.datetime.now()
        fname = f"commit_report_{user['username']}_{now.strftime('%Y-%m-%d_%H-%M-%S')}.html"
        report_title = f"Commit Report for {user['email']} - Period: {args.start_date} to {now.strftime('%Y-%m-%d')}"
        generate_report(commits, report_title, fname)
        print(f"\nReport generated: {fname}")


if __name__ == "__main__":
    main()
