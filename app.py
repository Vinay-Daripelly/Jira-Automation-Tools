import os
import re
import json
import requests
from flask import Flask, request, render_template_string, jsonify
from requests.auth import HTTPBasicAuth

app = Flask(__name__)
UPLOAD_FOLDER = os.path.dirname(__file__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# === HTML FORM UI ===
HTML_FORM = '''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Jira MOM Issue Creator</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      padding: 20px;
      background: #f5f5f5;
    }
    .container {
      max-width: 700px;
      margin: auto;
      background: #fff;
      padding: 25px;
      box-shadow: 0 0 10px rgba(0,0,0,0.1);
      border-radius: 10px;
    }
    h2 {
      text-align: center;
    }
    input, textarea, button, select {
      width: 100%;
      margin: 10px 0;
      padding: 10px;
      font-size: 1rem;
    }
    label {
      margin-top: 10px;
      display: block;
      font-weight: bold;
    }
    .success {
      color: green;
    }
    .error {
      color: red;
    }
    pre {
      background-color: #eee;
      padding: 10px;
      border-radius: 8px;
      overflow-x: auto;
    }
  </style>
</head>
<body>
  <div class="container">
    <h2>Upload Meeting Transcript to Create Jira Issues</h2>
    <form id="jiraForm">
      <label>Email</label>
      <input type="email" name="jira_email" required />

      <label>Jira API Token</label>
      <input type="password" name="jira_api_token" required />

      <label>Jira Instance URL</label>
      <input type="text" name="jira_api_instance" placeholder="https://your-domain.atlassian.net" required />

      <label>Jira Project Name</label>
      <input type="text" name="project_name" required />

      <label>Meeting Transcript (.txt)</label>
      <input type="file" name="meeting_file" accept=".txt" required />

      <button type="submit">Submit</button>
    </form>

    <div id="output"></div>
  </div>

  <script>
    document.getElementById('jiraForm').addEventListener('submit', async function(event) {
      event.preventDefault();

      const form = event.target;
      const formData = new FormData(form);
      const output = document.getElementById('output');
      output.innerHTML = '<p>Submitting...</p>';

      try {
        const response = await fetch('/process', {
          method: 'POST',
          body: formData
        });

        const result = await response.json();
        if (response.ok) {
          output.innerHTML = `
            <p class="success">✅ Jira issues created successfully.</p>
            <h3>Generated MoM:</h3>
            <pre>${result.mom}</pre>
            <h3>Assignees & Account IDs:</h3>
            <pre>${JSON.stringify(result.account_ids, null, 2)}</pre>
            <h3>Created Issues:</h3>
            <pre>${JSON.stringify(result.created_issues, null, 2)}</pre>
          `;
        } else {
          output.innerHTML = `<p class="error">❌ Error: ${result.error}</p>`;
        }
      } catch (err) {
        output.innerHTML = `<p class="error">❌ Request failed: ${err}</p>`;
      }
    });
  </script>
</body>
</html>
'''
 # Keep the HTML_FORM content from your previous message here

# === Helper Functions ===

def generate_mom(meeting_text: str) -> str:
    """
    Call Moonshot's Chat Completion endpoint directly.
    """
    api_key = os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        raise RuntimeError("MOONSHOT_API_KEY environment variable is missing")

    payload = {
        "model": "moonshot-v1-8k",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You will be given a meeting transcript. "
                    "Extract all project-related action items and assign them to the respective persons."
                ),
            },
            {"role": "user", "content": meeting_text},
        ],
        "temperature": 0.3,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    resp = requests.post(
        "https://api.moonshot.cn/v1/chat/completions",
        headers=headers,
        data=json.dumps(payload),
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

# ---------- 2. TEXT PARSING ----------
def extract_relevant_points(mom_text: str) -> list[tuple[str, str]]:
    """
    Return list of (description, assignee_name) tuples from the generated MoM.
    """
    pattern = re.compile(
        r"\d+\.\s+\*\*Issue:\*\*\s+(.*?)\s*\n\s*-\s+\*\*Assigned to:\*\*\s+(\w+)",
        re.MULTILINE,
    )
    return pattern.findall(mom_text)

d# ---------- 3. JIRA HELPERS ----------
def get_project_key_by_name(cfg: dict, project_name: str) -> str:
    url = f"{cfg['jira_api_instance']}/rest/api/3/project/search"
    auth = HTTPBasicAuth(cfg["jira_email"], cfg["jira_api_token"])
    resp = requests.get(url, headers={"Accept": "application/json"}, auth=auth, timeout=30)
    resp.raise_for_status()
    for proj in resp.json().get("values", []):
        if proj["name"].strip().lower() == project_name.strip().lower():
            return proj["key"]
    raise RuntimeError("Project not found in Jira")

def get_account_id_by_name(cfg: dict, assignee_name: str) -> str:
    url = f"{cfg['jira_api_instance']}/rest/api/3/user/search?query={assignee_name}"
    auth = HTTPBasicAuth(cfg["jira_email"], cfg["jira_api_token"])
    resp = requests.get(url, headers={"Accept": "application/json"}, auth=auth, timeout=30)
    resp.raise_for_status()
    users = resp.json()
    if not users:
        raise RuntimeError(f"No Jira user matched: {assignee_name}")
    return users[0]["accountId"]

def create_jira_issue(cfg: dict, issue_data: dict) -> dict:
    """
    Create the Jira issue if it doesn't already exist (simple duplicate check by summary).
    """
    auth = HTTPBasicAuth(cfg["jira_email"], cfg["jira_api_token"])
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    # duplicate check
    jql = f'project = "{issue_data["project_key"]}" AND summary ~ "{issue_data["summary"]}"'
    search_url = f"{cfg['jira_api_instance']}/rest/api/3/search"
    if requests.get(search_url, headers=headers, params={"jql": jql}, auth=auth).json().get("issues"):
        return {"skipped": "duplicate", "summary": issue_data["summary"]}

    payload = {
        "fields": {
            "project": {"key": issue_data["project_key"]},
            "summary": issue_data["summary"],
            "description": {
                "version": 1,
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": issue_data["description"]}]}
                ],
            },
            "issuetype": {"name": "Task"},
            "assignee": {"accountId": issue_data["assignee_account_id"]},
        }
    }

    create_url = f"{cfg['jira_api_instance']}/rest/api/3/issue"
    resp = requests.post(create_url, headers=headers, json=payload, auth=auth, timeout=30)
    if resp.status_code == 201:
        return resp.json()
    return {"error": resp.text, "summary": issue_data["summary"]}


# ---------- 4. ROUTES ----------
@app.route("/")
def index():
    return render_template_string(HTML_FORM)


@app.route("/process", methods=["POST"])
def process():
    """
    Receive form data, generate MoM, create Jira issues.
    """
    try:
        # 1. Save uploaded file
        uploaded = request.files["meeting_file"]
        path = os.path.join(app.config["UPLOAD_FOLDER"], "meeting.txt")
        uploaded.save(path)

        # 2. Basic config from form fields
        cfg = {
            "jira_email": request.form["jira_email"],
            "jira_api_token": request.form["jira_api_token"],
            "jira_api_instance": request.form["jira_api_instance"].rstrip("/"),
            "project_name": request.form["project_name"],
        }

        with open(path, "r", encoding="utf-8") as f:
            meeting_text = f.read()

        # 3. AI → MoM
        mom = generate_mom(meeting_text)

        # 4. Parse items
        points = extract_relevant_points(mom)
        project_key = get_project_key_by_name(cfg, cfg["project_name"])

        account_ids = {}
        created_issues = []

        for desc, assignee in points:
            try:
                acc_id = get_account_id_by_name(cfg, assignee)
                account_ids[assignee] = acc_id
                issue_data = {
                    "project_key": project_key,
                    "summary": f"Action Item: {desc}",
                    "description": desc,
                    "assignee_account_id": acc_id,
                }
                created_issues.append(create_jira_issue(cfg, issue_data))
            except Exception as e:
                account_ids[assignee] = f"Error: {e}"
                created_issues.append({"assignee": assignee, "error": str(e)})

        return jsonify({"mom": mom, "account_ids": account_ids, "created_issues": created_issues})

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ---------- 5. ENTRY POINT ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
