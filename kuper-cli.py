#!/usr/bin/env python3

"""CLI script orchestration for KUPer.

This script keeps CLI-only concerns (argument parsing and flow control)
outside of the ``kuper`` package business logic.
"""

import argparse
import datetime
import sys

from kuper import (
    RUNNER,
    KuperOutput,
    KuperService,
)


def main():
    """Main CLI workflow."""
    service = KuperService()
    output = KuperOutput()

    print(RUNNER)
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=True)
    parser.add_argument("--start-date", "-s", required=True)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    try:
        start_date = datetime.datetime.strptime(args.start_date, "%Y-%m-%d")
    except ValueError:
        sys.exit("Error: date must be YYYY-MM-DD")

    limit = datetime.datetime.now() - datetime.timedelta(days=32)
    if start_date < limit:
        sys.exit(f"Error: start-date must be on or after {limit.strftime('%Y-%m-%d')}")

    config = service.get_config()
    token, excludes = config.get("token"), config.get("excludes", [])
    user = service.get_current_user(args.instance.rstrip("/"), token)
    if not user:
        sys.exit("Error: Could not fetch user profile")

    print(f"Fetching commits for {user['email']} since {args.start_date}...")
    commits = service.get_gitlab_commits(
        args.instance.rstrip("/"),
        token,
        start_date,
        user["email"],
        excludes,
        args.report,
    )

    if not commits:
        print("No new commits found.")
        return

    output.print_console_output(commits, args.report)
    if args.report:
        now = datetime.datetime.now()
        fname = (
            f"commit_report_{user['username']}_{now.strftime('%Y-%m-%d_%H-%M-%S')}.html"
        )
        report_title = (
            f"Commit Report for {user['email']} - Period: "
            f"{args.start_date} to {now.strftime('%Y-%m-%d')}"
        )
        output.generate_report(commits, report_title, fname)
        print(f"\nReport generated: {fname}")


if __name__ == "__main__":
    main()
