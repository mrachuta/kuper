## Project name
kuper - a python script that collects users' commit history and detailed commit information from GitLab instances.

## Table of contents
- [Project name](#project-name)
- [Table of contents](#table-of-contents)
- [General info](#general-info)
- [Technologies](#technologies)
- [Setup](#setup)
- [Usage](#usage)
- [Thanks](#thanks)

## General info
A simple script written with extensive AI support to collect information about user activity on the Gitlab platform. The script retrieves information about user activity using the "Events API," then searches for all user commits during a given time period. It presents them with details and optionally generates a report, omitting duplicates (the same commits existing in different branches).

## Technologies
- python

## Setup

1) Generate Personal Gitlab Token with read API permissions
2) Setup environment
    ```
    pip install -r requirements.txt
    cp config.example.yaml config.yaml
    chmod +x kuper.py
    ```
3) Edit config file and paste token


## Usage

```
./kuper.py  --instance https://gitlab.com/ --start-date 2026-04-12 --report
```
required arguments:
```
--instance INSTANCE      GitLab instance URL (e.g., https://gitlab.com)
--start-date YYYY-MM-DD  Start date for commit search (YYYY-MM-DD).
```
optional arguments:
```
--report             Generate an interactive HTML report with commit details and diffs.
```

## Thanks

To Gemini 2.5 PRO for fantastic job over the code xD