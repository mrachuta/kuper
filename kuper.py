#!/usr/bin/env python3

import argparse
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
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    if 'token' not in config:
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

def get_gitlab_commits(instance_url, token, start_date, user_email, excludes=None, fetch_diffs=False):
    """Fetches push events and their commit details from the GitLab API."""
    if excludes is None:
        excludes = []
    headers = {"PRIVATE-TOKEN": token}
    params = {
        "action": "pushed",
        "after": start_date.strftime('%Y-%m-%d'),
        "per_page": 100
    }
    events_url = f"{instance_url}/api/v4/events"
    
    all_commits = []
    project_cache = {}
    processed_shas = set() # To store processed short_shas and avoid duplicates
    skipped_repos = set() # To track repos we've already printed a skip message for

    while events_url:
        try:
            response = requests.get(events_url, headers=headers, params=params, timeout=20)
            response.raise_for_status()
            events = response.json()

            for event in events:
                if "pushed" not in event.get("action_name", ""):
                    continue

                project_id = event.get("project_id")
                if not project_id:
                    continue

                # Cache project details
                if project_id not in project_cache:
                    proj_url = f"{instance_url}/api/v4/projects/{project_id}"
                    try:
                        proj_resp = requests.get(proj_url, headers=headers, timeout=10)
                        if proj_resp.status_code == 200:
                            project_cache[project_id] = proj_resp.json().get("path_with_namespace", "Unknown Project")
                        else:
                            project_cache[project_id] = "Unknown Project"
                    except requests.exceptions.RequestException:
                        project_cache[project_id] = "Unknown Project"
                
                repo_name = project_cache[project_id]
                
                # Skip excluded repositories
                is_excluded = False
                matching_rule = None
                for excluded_path in excludes:
                    if repo_name.startswith(excluded_path):
                        is_excluded = True
                        matching_rule = excluded_path
                        break
                
                if is_excluded:
                    if repo_name not in skipped_repos:
                        print(f"INFO: Skipping repository '{repo_name}' because it matches exclude rule '{matching_rule}'.")
                        skipped_repos.add(repo_name)
                    continue

                push_data = event.get("push_data", {})
                branch = push_data.get("ref", "unknown-branch").replace("refs/heads/", "")
                
                commits_to_process = []
                commit_count = push_data.get("commit_count", 0)

                if commit_count > 0:
                    from_sha = push_data.get("commit_from")
                    to_sha = push_data.get("commit_to")

                    try:
                        # Case 1: A push with a range of commits
                        if from_sha and to_sha and commit_count > 1:
                            compare_url = f"{instance_url}/api/v4/projects/{project_id}/repository/compare?from={from_sha}&to={to_sha}"
                            compare_resp = requests.get(compare_url, headers=headers, timeout=15)
                            if compare_resp.status_code == 200:
                                commits_to_process = compare_resp.json().get("commits", [])
                        # Case 2: A new branch or a single commit push
                        elif to_sha:
                             # Fetch commits for the branch, limited by commit_count from the event
                            # Or more reliably, fetch the specific commit using its SHA if it's a single push
                            # For now, let's assume if to_sha exists and from_sha is None, it's a new branch head
                            commits_url = f"{instance_url}/api/v4/projects/{project_id}/repository/commits/{to_sha}"
                            commits_resp = requests.get(commits_url, headers=headers, timeout=15)
                            if commits_resp.status_code == 200:
                                # Mock single commit as a list
                                commits_to_process = [commits_resp.json()]

                    except requests.exceptions.RequestException as e:
                        print(f"  - Could not fetch commit details for {repo_name}: {e}")
                        continue
                
                for commit in commits_to_process:
                    if commit.get('author_email') != user_email:
                        continue # Skip commits not authored by the user

                    if commit['short_id'] in processed_shas:
                        print(f"WARNING: Skipping duplicate commit {commit['short_id']} in branch {branch} of {repo_name}") 
                        continue # Skip duplicate commit

                    commit_time = datetime.datetime.fromisoformat(commit['created_at'].replace('Z', '+00:00'))
                    if commit_time.replace(tzinfo=None) < start_date:
                        continue
                    
                    processed_shas.add(commit['short_id'])

                    diff_text = ""
                    if fetch_diffs:
                        try:
                            diff_url = f"{instance_url}/api/v4/projects/{project_id}/repository/commits/{commit['id']}/diff"
                            diff_resp = requests.get(diff_url, headers=headers, timeout=15)
                            if diff_resp.status_code == 200:
                                diffs = diff_resp.json()
                                diff_texts = [d.get('diff', '') for d in diffs]
                                diff_text = "\n".join(diff_texts)
                            else:
                                diff_text = "Could not retrieve diff."
                        except requests.exceptions.RequestException as e:
                            diff_text = f"Error fetching diff: {e}"

                    all_commits.append({
                        "repo_name": repo_name,
                        "date": commit_time.strftime('%Y-%m-%d %H:%M'),
                        "branch": branch,
                        "short_sha": commit['short_id'],
                        "url": commit['web_url'],
                        "message": commit['message'].strip(),
                        "diff": diff_text
                    })

            next_page = response.headers.get("X-Next-Page")
            if not next_page:
                break
            events_url = f"{instance_url}/api/v4/events?page={next_page}"

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from GitLab: {e}")
            break
            
    return sorted(all_commits, key=lambda x: (x['repo_name'], x['date']))

def generate_report(commits, report_title, output_filename="commits_report.html"):
    """Generates an HTML report from the commits."""
    try:
        with open("templates/template.html", "r") as f:
            main_template = f.read()
        with open("templates/commit_template.html", "r") as f:
            commit_template = f.read()
    except FileNotFoundError as e:
        print(f"Error: Could not find template file. Make sure you have the 'templates' directory. Details: {e}")
        return

    commit_html_blocks = []
    last_repo_name = None
    for commit in commits:
        # Add a repository header when it changes
        if commit['repo_name'] != last_repo_name:
            if last_repo_name is not None: # Add a closing tag for the previous repo block
                commit_html_blocks.append("</div>")
            commit_html_blocks.append(f"<h2>{commit['repo_name']}</h2><div class='repo-block'>")
            last_repo_name = commit['repo_name']

        # Populate the commit template
        commit_html = commit_template.replace("{{ commit_url }}", commit['url'])
        commit_html = commit_html.replace("{{ commit_message }}", commit['message'].split('\n')[0])
        commit_html = commit_html.replace("{{ diff }}", commit.get('diff', 'Diff not available.'))
        commit_html = commit_html.replace("{{ sha }}", commit['short_sha'])
        commit_html = commit_html.replace("{{ branch }}", commit['branch'])
        commit_html = commit_html.replace("{{ date }}", commit['date'])
        commit_html_blocks.append(commit_html)

    if last_repo_name is not None:
        commit_html_blocks.append("</div>") # Close the last repo block

    # Assemble the final HTML
    final_html = main_template.replace("{{ report_title }}", report_title)
    final_html = final_html.replace("{{ commits }}", "\n".join(commit_html_blocks))

    # Write the report to a file
    with open(output_filename, "w") as f:
        f.write(final_html)

def print_console_output(commits):
    """Prints the commits to the console."""
    last_repo_name = None
    for commit in commits:
        if commit['repo_name'] != last_repo_name:
            print(f"\n===== REPOSITORY: {commit['repo_name']}")
            last_repo_name = commit['repo_name']
        
        commit_message_first_line = commit['message'].split('\n')[0]

        # Print commit details
        print(
            f"{commit['date']}  |  {commit['short_sha']}  |  "
            f"{commit['url']}  |   {commit['branch']}  |  "
            f"'{commit_message_first_line}'"
        )

def main():
    """Main function."""
    print(RUNNER)
    parser = argparse.ArgumentParser(description="Collect commit information from a GitLab instance.")
    parser.add_argument('--instance', required=True, help="GitLab instance URL (e.g., https://gitlab.com)")
    parser.add_argument('--days', required=True, type=int, help="Number of days to search for commits (max 45).")
    parser.add_argument('--report', action='store_true', help="Generate an HTML report.")
    args = parser.parse_args()

    if not (1 <= args.days <= 45):
        print("Error: --days must be between 1 and 45.")
        sys.exit(1)

    instance_url = args.instance.rstrip('/')
    config = get_config()
    token = config.get("token")
    excludes = config.get("excludes", [])

    user_profile = get_current_user(instance_url, token)
    if not user_profile:
        print("Could not determine current user's profile. Aborting.")
        sys.exit(1)
    
    user_email = user_profile.get("email")
    username = user_profile.get("username", "user")

    print(f"Fetching commits for user {user_email} from the last {args.days} days...")
    if excludes:
        print(f"Excluding the following repositories: {', '.join(excludes)}")

    days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=args.days)
    
    # We need to fetch diffs if a report is requested
    fetch_diffs = args.report

    commits = get_gitlab_commits(instance_url, token, days_ago, user_email, excludes=excludes, fetch_diffs=fetch_diffs)

    if not commits:
        print("No new commits found for this user in the specified period.")
        return

    # Always print the console output
    print_console_output(commits)

    if args.report:
        report_title = f"Commit Report for {user_email} - Last {args.days} Days"
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
        output_filename = f"commit_report_{username}_{timestamp}.html"
        generate_report(commits, report_title, output_filename=output_filename)
        print(f"\nSuccessfully generated HTML report: {output_filename}")


if __name__ == "__main__":
    main()
