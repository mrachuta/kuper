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
    """Fetches user's commits from GitLab API by first finding active repositories
    from events and then fetching commits from those repositories."""
    if excludes is None:
        excludes = []
    headers = {"PRIVATE-TOKEN": token}

    # --- Step 1: Find active projects and branches from events ---
    active_repos_and_branches = set()
    project_cache = {}
    skipped_repos = set()

    events_params = {
        "action": "pushed",
        "after": start_date.strftime('%Y-%m-%d'),
        "per_page": 100
    }
    events_url = f"{instance_url}/api/v4/events"

    print("INFO: Scanning user events to find active repositories and branches...")
    while events_url:
        try:
            response = requests.get(events_url, headers=headers, params=events_params, timeout=20)
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
                if branch != "unknown-branch":
                    active_repos_and_branches.add((project_id, repo_name, branch))

            # Pagination for events
            if 'next' in response.links:
                events_url = response.links['next']['url']
                events_params = None  # Params are included in the 'next' URL
            else:
                break

        except requests.exceptions.RequestException as e:
            print(f"Error scanning GitLab events: {e}")
            break

    # --- Step 2: Fetch commits for each active repo/branch using the Commits API ---
    all_commits = []
    processed_shas = set()
    
    if active_repos_and_branches:
        print(f"INFO: Found {len(active_repos_and_branches)} active branch(es). Now fetching commits...")

    # Define the desired branch processing order
    branch_order = ['master', 'main', 'prod', 'nonprod', 'develop', 'development']

    def sort_key(item):
        _project_id, repo_name, branch = item
        try:
            # Assign a low number for priority branches, a high number for others
            branch_priority = branch_order.index(branch)
        except ValueError:
            branch_priority = len(branch_order)
        # Sort by repo name first, then by custom branch priority, then by branch name
        return (repo_name, branch_priority, branch)

    sorted_active_branches = sorted(list(active_repos_and_branches), key=sort_key)

    for project_id, repo_name, branch in sorted_active_branches:
        print(f"INFO: Fetching commits for '{repo_name}' on branch '{branch}'...")
        
        commits_url = f"{instance_url}/api/v4/projects/{project_id}/repository/commits"
        commits_params = {
            "ref_name": branch,
            "since": start_date.isoformat(),
            "author": user_email, # Filter by single user email
            "per_page": 100,
            "with_stats": "false"
        }

        while commits_url:
            try:
                response = requests.get(commits_url, headers=headers, params=commits_params, timeout=20)
                response.raise_for_status()
                commits_from_api = response.json()

                if not commits_from_api:
                    break
                
                for commit in commits_from_api:
                    # Client-side filtering is no longer needed since 'author' param is used
                    if commit['short_id'] in processed_shas:
                        print(f"INFO: Skipping duplicate commit {commit['short_id']} in branch {branch} of {repo_name}")
                        continue # Skip duplicate commit
                    
                    processed_shas.add(commit['short_id'])
                    
                    commit_time = datetime.datetime.fromisoformat(commit['created_at'].replace('Z', '+00:00'))
                    
                    diff_text = ""
                    if fetch_diffs:
                        try:
                            diff_url = f"{instance_url}/api/v4/projects/{project_id}/repository/commits/{commit['id']}/diff"
                            diff_resp = requests.get(diff_url, headers=headers, timeout=15)
                            if diff_resp.status_code == 200:
                                diffs = diff_resp.json()
                                diff_parts = []
                                for d in diffs:
                                    file_header = ""
                                    old_path = d.get('old_path')
                                    new_path = d.get('new_path')

                                    if d.get('new_file'):
                                        file_header = f"--- New file: {new_path} ---"
                                    elif d.get('deleted_file'):
                                        file_header = f"--- Deleted file: {old_path} ---"
                                    elif d.get('renamed_file'):
                                        file_header = f"--- Renamed: {old_path} -> {new_path} ---"
                                    else:
                                        file_header = f"--- Modified: {new_path} ---"
                                    
                                    diff_content = d.get('diff', 'Diff content not available.')
                                    diff_parts.append(f"{file_header}\n{diff_content}")
                                
                                diff_text = "\n\n".join(diff_parts)
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

                # Pagination for commits
                if 'next' in response.links:
                    commits_url = response.links['next']['url']
                    commits_params = None # Params are included in the 'next' URL
                else:
                    break

            except requests.exceptions.RequestException as e:
                print(f"  - Could not fetch commits for {repo_name} (branch: {branch}): {e}")
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
