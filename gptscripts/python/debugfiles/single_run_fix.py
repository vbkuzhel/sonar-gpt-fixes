import os
import requests
import json
import openai
import base64
import sys
import subprocess
import tempfile
import time
from git import Repo
from datetime import datetime

# PROD CONSTANTS
SONAR_API_URL = "https://sonarcloud.io/api"
SONAR_ORG_KEY = os.environ["SONAR_ORGANIZATION_KEY"]
SONAR_PROJECT_KEY = os.environ["SONAR_PROJECT_KEY"]
SONAR_TOKEN = os.environ["SONAR_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GITHUB_OWNER = os.environ["GITHUB_OWNER_ENV"]
GITHUB_REPO_NAME = os.environ["GITHUB_REPO_NAME_ENV"]
GITHUB_ACCESS_TOKEN = "os.environ['GITHUB_ACCESS_TOKEN_ENV']"
GITHUB_USERNAME = os.environ["GITHUB_USERNAME_ENV"]
GITHUB_EMAIL = os.environ["GITHUB_EMAIL_ENV"]
MAX_CYCLES = 5  # Max number of cycles to run the script
POLLING_INTERVAL = 15  # Seconds to wait between polling for new issues


def fetch_issues(sonar_token, source_directory, branch):    
    auth_header = base64.b64encode(f"{sonar_token}:".encode()).decode()

    # Define the function to fetch issues from the SonarCloud API
    def fetch_paged_issues(page_index):
        try:
            response = requests.get(
                f"{SONAR_API_URL}/issues/search",
                params={
                    "organization": SONAR_ORG_KEY,
                    "projects": SONAR_PROJECT_KEY,
                    "types": "CODE_SMELL, BUG, VULNERABILITY",
                    #"types": "BUG, VULNERABILITY",
                    "branch": "main",
                    "statuses": "OPEN, CONFIRMED, REOPENED",
                    "p": page_index,
                },
                headers={"Authorization": f"Basic {auth_header}"},
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            raise Exception(f"Error: Failed to fetch issues from SonarCloud API: {str(e)}")

    # Fetch all pages of issues
    issues_by_file = {}
    page_index = 1
    while True:
        try:
            result = fetch_paged_issues(page_index)
        except Exception as e:
            print(e)
            sys.exit(1)

        issues = result["issues"]

        if not issues:
            break

        for issue in issues:
            # Remove the project key from the component
            file_path = issue["component"].replace(SONAR_PROJECT_KEY + ":", "")
            file_path = os.path.join(source_directory, file_path)
            line = issue.get("line", 0)
            message = issue["message"]

            if file_path not in issues_by_file:
                issues_by_file[file_path] = []

            issues_by_file[file_path].append({
                "line": line,
                "message": message,
        })

        page_index += 1
    print(issues_by_file)

    return issues_by_file

# Generate the prompt for fixing all issues at once
def generate_all_issues_prompt(file_content, issues):
#    issues_text = "\n".join([f"Line {issue['line']}: {issue['message']}" for issue in issues])
#    return f"##### The SonarCloud found the following issues:\n{issues_text}\n \n### Code with issues\n{file_content}\n \n### Fixed Code that addresses all issues:"    
    # Add line numbers to the original code
    numbered_lines = [f"{i+1}: {line}" for i, line in enumerate(file_content.splitlines())]
    numbered_file_content = "\n".join(numbered_lines)
    

    issues_text = "\n".join([f"Line {issue['line']}: {issue['message']}" for issue in issues])

    # if issues:
    #     first_issue = issues[0]
    #     issue_text = f"Line {first_issue['line']}: {first_issue['message']}"
    # else:
    #     issue_text = "No issues found."


    #return f"##### The SonarCloud found the following issue:\n{issue_text}\nFix the issue for the code below (with line numbers) and return the corrected code. Remove line numbers in your response \n### Code with issues\n{numbered_file_content}\n \n### Fixed Code that addresses the issue:"
    #return f"##### The SonarCloud found the following issue:\n### {issue_text}\n The code with the issue is provided below with line numbers. Fix the issue, and return the corrected code without line numbers\n### Code with issues\n{numbered_file_content}\n \n### Fixed Code:"
    #return f"#### In the code below fix the following issue:\n### {issues_text}\n The code with the issue is provided below with line numbers. Fix the issue, and return the corrected code without line numbers\n### Code with issues\n{numbered_file_content}\n \n### Fixed Code:"
    return f"#### In the code below fix the following issue:\n### {issues_text}\n The code with the issue is provided below with line numbers. Fix the issue, and return the corrected code only without line numbers\n### Code with issues\n{numbered_file_content}\n \n### Fixed Code:"

def generate_prompt(file_content, issue):
    return f"##### The SonarCloud found the following issue on line {issue['line']}: {issue['message']}\n \n### Code with issues\n{file_content}\n \n### Fixed Code that only contains fixed block of lines of code and not the entire code:"

def apply_suggested_fix(file_content, issue, suggested_fix):
    lines = file_content.split('\n')
    issue_line = issue['line'] - 1
    suggested_lines = suggested_fix.split('\n')

    # Replace the affected lines with the suggested fix lines
    lines[issue_line : issue_line + len(suggested_lines)] = suggested_lines

    return '\n'.join(lines)

# Implement fixes using the GPT-4 API for all issues at once
def implement_fixes(issues_by_file):
    openai.api_key = OPENAI_API_KEY

    for file_path, issues in issues_by_file.items():
        # Read the file contents
        with open(file_path, 'r') as file:
            file_content = file.read()

        # Generate the prompt using the current file_content
        prompt = generate_all_issues_prompt(file_content, issues)
        print(f"\n")
        print(f"\n****************************************************************************************************")
        print(f"Generating suggestion for the following file: {file_path}")
        print(f"\n")
        print(f"Prompt: {prompt}")
        try:
            response = openai.Completion.create(
                model="text-davinci-003",
                prompt=prompt,
                temperature=0,
                max_tokens=3000,
                top_p=1.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                stop=["###"]
            )
            suggested_fix = response.choices[0].text.strip()
            print(f"Suggested fix for issues '{issues}': {response}")
        except Exception as e:
            print(f"Error: Failed to get a suggestion from GPT-4 for issues '{issues}': {str(e)}")
            continue

        # Write the suggested fix directly back to the file
        with open(file_path, 'w') as file:
            file.write(suggested_fix)
            print(f"Updated file: {file_path}")

def implement_fixes_gpt_3_5_turbo(issues_by_file):
    openai.api_key = OPENAI_API_KEY

    for file_path, issues in issues_by_file.items():
        # Read the file contents
        with open(file_path, 'r') as file:
            file_content = file.read()

        # Generate the prompt using the current file_content
        prompt = generate_all_issues_prompt(file_content, issues)
        print(f"\n")
        print(f"\n****************************************************************************************************")
        print(f"Generating suggestion for the following file: {file_path}")
        print(f"\n")
        print(f"Prompt: {prompt}")
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=3000,
                stop=["###"]
            )
            suggested_fix = response.choices[0].message['content'].strip()
            print(f"Suggested fix for issues '{issues}': {response}")
        except Exception as e:
            print(f"Error: Failed to get a suggestion from GPT-4 for issues '{issues}': {str(e)}")
            continue

        # Write the suggested fix directly back to the file
        with open(file_path, 'w') as file:
            file.write(suggested_fix)
            print(f"Updated file: {file_path}")


def analyze_branch_with_sonarcloud(branch_name):
    sonar_api_base_url = "https://sonarcloud.io/api"    
    project_key = SONAR_PROJECT_KEY
    auth_header = base64.b64encode(f"{SONAR_TOKEN}:".encode()).decode()

    try:
        response = requests.post(
            f"{sonar_api_base_url}/scanner/scan",
            params={
                "project": project_key,
                "branch": branch_name,
            },
            headers={"Authorization": f"Basic {auth_header}"},
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise Exception(f"Error: Failed to trigger SonarCloud analysis: {str(e)}")

    analysis = response.json()

    task_id = analysis['task']['id']
    print(f"Started analysis with task ID: {task_id}")

    # Poll the analysis task for completion
    elapsed_time = 0
    polling_interval = 10  # Adjust the polling interval if needed

    while True:
        time.sleep(POLLING_INTERVAL)
        elapsed_time += POLLING_INTERVAL

        try:
            response = requests.get(
                f"{sonar_api_base_url}/ce/task",
                params={
                    "id": task_id,
                },
                headers={"Authorization": f"Basic {auth_header}"},
            )
            response.raise_for_status()
        except requests.RequestException as e:
            raise Exception(f"Error: Failed to get analysis task status: {str(e)}")

        task = response.json()['task']

        if task['status'] in ['SUCCESS', 'FAILED', 'CANCELED']:
            print(f"Analysis task completed with status: {task['status']} (Elapsed time: {elapsed_time} seconds)")
            break
        else:
            print(f"Analysis task status: {task['status']} - waiting... (Elapsed time: {elapsed_time} seconds)")

def create_pr(base, head, title):
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO_NAME}/pulls"
    headers = {"Authorization": f"token {GITHUB_ACCESS_TOKEN}"}
    data = {
        "title": title,
        "head": head,
        "base": base,
    }

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()

    return response.json()

def setup_git_repo(tmp_dir):
    repo_url = f'https://{GITHUB_ACCESS_TOKEN}@github.com/{GITHUB_OWNER}/{GITHUB_REPO_NAME}.git'
    repo = Repo.clone_from(repo_url, tmp_dir, branch='main')

    # Fetch all remote branches
    repo.git.fetch("--all")

    repo.config_writer().set_value("user", "name", GITHUB_USERNAME).release()
    repo.config_writer().set_value("user", "email", GITHUB_EMAIL).release()

    return repo

def create_and_checkout_new_branch(repo):
    current_time = datetime.now().strftime("%Y%m%d%H%M%S")
    new_branch_name = f"fixes_{current_time}"
    new_branch = repo.create_head(new_branch_name)
    new_branch.checkout()

    # Add the following line to push the new branch to the remote repository
    repo.git.push("origin", new_branch_name)

    return new_branch

def apply_fixes_and_push_changes(repo, new_branch):
    try:
        issues_by_file = fetch_issues(SONAR_TOKEN, repo.working_dir, 'main')
        #implement_fixes(issues_by_file)
        implement_fixes_gpt_3_5_turbo(issues_by_file)
        repo.git.add(A=True)
        
        # Check if there are changes in the working tree
        if repo.is_dirty():
            repo.git.commit(m='-=TEST SINGLE RUN=- Apply automated fixes')
            repo.git.push('--set-upstream', 'origin', new_branch.name)
        else:
            print("No changes to commit. Skipping this cycle...")
            return False
        
        return True
    except Exception as e:
        print(f"Error: Failed to push changes: {str(e)}")
        sys.exit(1)

def main():
    print("************************************************************")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    print("Starting the automated code fixer...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = setup_git_repo(tmp_dir)
        new_branch = create_and_checkout_new_branch(repo)
        issues_by_file = fetch_issues(SONAR_TOKEN, tmp_dir, "main")

        # Call apply_fixes_and_push_changes and check if changes were committed and pushed
        if not apply_fixes_and_push_changes(repo, new_branch):
            raise Exception("GPT-4 failed to fix an issue and returned the same code. Stopping execution.")               

        pr = create_pr('main', new_branch.name, '-=TEST SINGLE RUN=- Apply automated fixes')
        print(f"Created PR: {pr['html_url']}")
        print(f"Created PR: null")

if __name__ == "__main__":
    main()