#!/usr/bin/env python3
"""
Kuper: A script to generate commit reports from a GitLab instance.
"""
import argparse
import datetime
import html
import os
import sys
from urllib.parse import urlparse
import requests
import yaml

# --- Constants ---
MAX_DAYS = 31
API_VERSION = "v4"
TEMPLATES_DIR_NAME = "templates"
MAIN_TEMPLATE_FILE = "template.html"
COMMIT_TEMPLATE_FILE = "commit_template.html"
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
# --- Helper Functions ---

def _parse_arguments():
    """Parses and validates command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Collect commit information from a GitLab instance."
    )
    parser.add_argument(
        "--instance",
        required=True,
        help="GitLab instance URL (e.g., https://gitlab.com)",
    )
    parser.add_argument(
        "--days",
        type=int,
        required=True,
        help=f"Number of days from today to search for commits (max: {MAX_DAYS})",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate an interactive HTML report with commit details and diffs.",
    )
    args = parser.parse_args()

    if not (1 <= args.days <= MAX_DAYS):
        print(f"Error: --days must be between 1 and {MAX_DAYS}.", file=sys.stderr)
        sys.exit(1)
        
    parsed_url = urlparse(args.instance)
    if not all([parsed_url.scheme, parsed_url.netloc]):
        print("Error: Invalid instance URL provided. It should be in the format 'https://gitlab.example.com'", file=sys.stderr)
        sys.exit(1)

    return args, f"{parsed_url.scheme}://{parsed_url.netloc}/api/{API_VERSION}"

def _load_config():
    """Loads configuration from config.yaml."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file_path = os.path.join(script_dir, 'config.yaml')
    try:
        with open(config_file_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            if not isinstance(config, dict):
                print(f"Error: {config_file_path} is not a valid YAML dictionary.", file=sys.stderr)
                sys.exit(1)
        return config
    except FileNotFoundError:
        print(f"Error: Configuration file 'config.yaml' not found in {script_dir}.", file=sys.stderr)
        print("Please create it and add a 'token' key with your GitLab Personal Access Token.", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error parsing 'config.yaml': {e}", file=sys.stderr)
        sys.exit(1)

def _get_gitlab_session(token):
    """
    Creates a requests Session authenticated with a GitLab token.
    """
    if not token or not isinstance(token, str):
        print("Error: GitLab 'token' is missing or invalid in 'config.yaml'.", file=sys.stderr)
        sys.exit(1)
    
    session = requests.Session()
    session.headers.update({"PRIVATE-TOKEN": token})
    return session

def _get_user_info(session, api_url):
    """Fetches authenticated user's info and primary email."""
    try:
        print("Verifying authentication and fetching user info...", file=sys.stderr)
        user_response = session.get(f"{api_url}/user")
        user_response.raise_for_status()
        user_info = user_response.json()
        print("Authentication successful.", file=sys.stderr)
        
        user_email = user_info.get("email")
        if not user_email:
             emails_response = session.get(f"{api_url}/user/emails")
             emails_response.raise_for_status()
             emails = emails_response.json()
             if emails:
                 user_email = emails[0]['email']
             else:
                print("Could not determine user email from GitLab API.", file=sys.stderr)
                sys.exit(1)
        
        user_info['email'] = user_email
        return user_info

    except requests.exceptions.RequestException as e:
        print(f"Error fetching user information: {e}", file=sys.stderr)
        sys.exit(1)

def _get_commit_branch_name(session, api_url, project_id, commit_sha):
    """Fetches the first branch name associated with a commit."""
    try:
        refs_response = session.get(f"{api_url}/projects/{project_id}/repository/commits/{commit_sha}/refs")
        refs_response.raise_for_status()
        refs = refs_response.json()
        for ref in refs:
            if ref['type'] == 'branch':
                return ref['name']
    except requests.exceptions.RequestException:
        pass
    return "(unknown)"

def _get_commit_diff(session, api_url, project_id, commit_sha):
    """Fetches the diff for a commit."""
    try:
        diff_response = session.get(f"{api_url}/projects/{project_id}/repository/commits/{commit_sha}/diff")
        diff_response.raise_for_status()
        diffs = diff_response.json()
        if diffs:
            return "\n".join([d['diff'] for d in diffs])
    except requests.exceptions.RequestException as e:
        return f"Could not fetch diff: {e}"
    return ""

def _format_diff_for_html(full_diff):
    """Formats a raw diff string into color-coded HTML."""
    formatted_diff = ""
    for line in full_diff.split('\n'):
        escaped_line = html.escape(line)
        if line.startswith('+++') or line.startswith('---') or line.startswith('@@'):
            formatted_diff += f'<span class="diff-info">{escaped_line}</span>\n'
        elif line.startswith('+'):
            formatted_diff += f'<span class="diff-add">{escaped_line}</span>\n'
        elif line.startswith('-'):
            formatted_diff += f'<span class="diff-rem">{escaped_line}</span>\n'
        else:
            formatted_diff += f'{escaped_line}\n'
    return formatted_diff

def _load_templates():
    """Loads HTML templates from the templates directory."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(script_dir, TEMPLATES_DIR_NAME)
    try:
        with open(os.path.join(templates_dir, MAIN_TEMPLATE_FILE), 'r', encoding='utf-8') as f:
            main_template = f.read()
        with open(os.path.join(templates_dir, COMMIT_TEMPLATE_FILE), 'r', encoding='utf-8') as f:
            commit_template = f.read()
        return main_template, commit_template
    except FileNotFoundError as e:
        print(f"Error: Template file not found in '{TEMPLATES_DIR_NAME}/' directory.", file=sys.stderr)
        print(f"Original error: {e}", file=sys.stderr)
        sys.exit(1)


# --- Main Execution ---

def main():
    print(RUNNER)
    """Orchestrates the script's execution."""
    args, api_url = _parse_arguments()
    config = _load_config()
    session = _get_gitlab_session(config.get('token'))
    user_info = _get_user_info(session, api_url)
    
    since_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=args.days)
    commits_by_project = {}

    excludes = config.get('excludes', [])
    if not isinstance(excludes, list):
        print("Warning: 'excludes' in config.yaml is not a list, ignoring.", file=sys.stderr)
        excludes = []

    # 1. Fetch all projects and their commits
    try:
        print("Fetching projects...", file=sys.stderr)
        projects_response = session.get(f"{api_url}/projects", params={"membership": "true", "per_page": 100})
        projects_response.raise_for_status()
        projects = projects_response.json()
        print(f"Found {len(projects)} projects.", file=sys.stderr)
        
        for i, project in enumerate(projects):
            project_path = project['path_with_namespace']
            if any(project_path == p or project_path.startswith(p + '/') for p in excludes):
                print(f"  - Skipping project {i+1}/{len(projects)}: {project_path} (excluded by config)", file=sys.stderr)
                continue

            print(f"  - Checking project {i+1}/{len(projects)}: {project['name_with_namespace']}", file=sys.stderr)
            page = 1
            while True:
                params = { "author_email": user_info['email'], "since": since_date.isoformat(), "per_page": 100, "page": page }
                commits_response = session.get(f"{api_url}/projects/{project['id']}/repository/commits", params=params)
                if not commits_response.ok: break
                
                commits = commits_response.json()
                if not commits: break

                project_id = project['id']
                if project_id not in commits_by_project:
                    commits_by_project[project_id] = {'name': project['name_with_namespace'], 'commits': []}
                
                commits_by_project[project_id]['commits'].extend(commits)
                page += 1
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from GitLab: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. Sort projects and commits
    for project_id in commits_by_project:
        commits_by_project[project_id]['commits'].sort(key=lambda c: c['created_at'], reverse=True)
    sorted_project_ids = sorted(commits_by_project.keys(), key=lambda pid: commits_by_project[pid]['name'].lower())

    if not any(p['commits'] for p in commits_by_project.values()):
        print("No commits found in the specified period.")
        sys.exit(0)

    # 3. Process and output the data
    main_template, commit_template = _load_templates() if args.report else (None, None)
    all_commit_html_blocks = []

    for project_id in sorted_project_ids:
        project_data = commits_by_project[project_id]
        project_name = project_data['name']
        
        print(f"\n{'='*10} {project_name} {'='*10}\n")
        if args.report:
            all_commit_html_blocks.append(f"<h2>{html.escape(project_name)}</h2>")

        for commit in project_data['commits']:
            branch_name = _get_commit_branch_name(session, api_url, project_id, commit['id'])
            
            # Print to console
            date_str = datetime.datetime.fromisoformat(commit['created_at'].replace('Z', '+00:00')).strftime("%Y-%m-%d %H:%M")
            print(f"{date_str} => [{branch_name}] {commit['short_id']} {commit['web_url']} \"{commit['title']}\"")

            if args.report:
                full_diff = _get_commit_diff(session, api_url, project_id, commit['id'])
                formatted_diff = _format_diff_for_html(full_diff)
                
                commit_block = commit_template.replace('{{ commit_url }}', html.escape(commit['web_url']))
                commit_block = commit_block.replace('{{ repo_name }}', html.escape(project_name))
                commit_block = commit_block.replace('{{ commit_message }}', html.escape(commit['title']))
                commit_block = commit_block.replace('{{ diff }}', formatted_diff)
                commit_block = commit_block.replace('{{ sha }}', html.escape(commit['short_id']))
                commit_block = commit_block.replace('{{ branch }}', html.escape(branch_name))
                commit_block = commit_block.replace('{{ date }}', html.escape(date_str))
                all_commit_html_blocks.append(commit_block)

    # 4. Finalize and write the report file
    if args.report:
        # Create date range string for the title
        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=args.days)
        date_range_str = f"({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})"
        
        report_title = f"Commit Report for {user_info.get('name', '')} {date_range_str}"
        final_html = main_template.replace('{{ report_title }}', html.escape(report_title))
        final_html = final_html.replace('{{ commits }}', "\n".join(all_commit_html_blocks))
        
        report_filename = datetime.datetime.now().strftime("report_%Y-%m-%d-%H-%M-%S.html")
        print(f"\nGenerating HTML report to {report_filename}", file=sys.stderr)
        with open(report_filename, 'w', encoding='utf-8') as f:
            f.write(final_html)
        print("HTML Report generation complete.", file=sys.stderr)

if __name__ == "__main__":
    main()