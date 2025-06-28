from flask import Flask, request, render_template_string, jsonify
import os
import requests
import re
from requests.auth import HTTPBasicAuth
from openai import OpenAI

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
client = None

def generate_mom(meeting_text: str) -> str:
    try:
        completion = client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=[
                {"role": "system", "content": "You will be given a meeting transcript under the '##transcript'. Extract all project-related action items and assign them to the respective persons."},
                {"role": "user", "content": meeting_text}
            ],
            temperature=0.3,
        )
        return completion.choices[0].message.content
    except Exception as e:
        raise Exception(f"Failed to generate MOM: {e}")

def extract_relevant_points(mom_text: str) -> list:
    pattern = re.compile(r"\d+\.\s+\*\*Issue:\*\*\s+(.*?)\s*\n\s*-\s+\*\*Assigned to:\*\*\s+(\w+)", re.MULTILINE)
    return pattern.findall(mom_text)

def get_project_key_by_name(config_data, project_name):
    url = f"{config_data['jira_api_instance']}/rest/api/3/project/search"
    headers = {"Accept": "application/json"}
    auth = HTTPBasicAuth(config_data['jira_email'], config_data['jira_api_token'])
    resp = requests.get(url, headers=headers, auth=auth)
    for proj in resp.json().get("values", []):
        if proj["name"].strip().lower() == project_name.strip().lower():
            return proj["key"]
    raise Exception("Project not found.")

def get_account_id_by_name(config_data, assignee_name):
    url = f"{config_data['jira_api_instance']}/rest/api/3/user/search?query={assignee_name}"
    headers = {"Accept": "application/json"}
    auth = HTTPBasicAuth(config_data['jira_email'], config_data['jira_api_token'])
    resp = requests.get(url, headers=headers, auth=auth)
    users = resp.json()
    if not users:
        raise Exception(f"No user: {assignee_name}")
    return users[0]["accountId"]

def create_jira_issue(config_data, issue_data):
    search_url = f"{config_data['jira_api_instance']}/rest/api/3/search"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = HTTPBasicAuth(config_data['jira_email'], config_data['jira_api_token'])
    params = {"jql": f'project = "{issue_data["project_key"]}" AND summary ~ "{issue_data["summary"]}"'}
    if requests.get(search_url, headers=headers, params=params, auth=auth).json().get("issues"):
        return {"message": "Duplicate skipped", "summary": issue_data['summary']}

    payload = {
        "fields": {
            "project": {"key": issue_data['project_key']},
            "summary": issue_data['summary'],
            "description": {
                "version": 1,
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"text": issue_data['description'], "type": "text"}]}]
            },
            "issuetype": {"name": "Task"},
            "assignee": {"accountId": issue_data['assignee_account_id']}
        }
    }

    create_url = f"{config_data['jira_api_instance']}/rest/api/3/issue"
    resp = requests.post(create_url, headers=headers, json=payload, auth=auth)
    return resp.json() if resp.status_code == 201 else {"error": resp.text}

# === Routes ===
@app.route('/')
def index():
    return render_template_string(HTML_FORM)

@app.route('/process', methods=['POST'])
def process():
    global client
    try:
        file = request.files['meeting_file']
        path = os.path.join(app.config['UPLOAD_FOLDER'], 'meeting.txt')
        file.save(path)

        config = {
            "jira_email": request.form['jira_email'],
            "jira_api_token": request.form['jira_api_token'],
            "jira_api_instance": request.form['jira_api_instance'],
            "project_name": request.form['project_name']
        }

        with open(path, 'r', encoding='utf-8') as f:
            meeting_text = f.read()

        client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url="https://api.moonshot.cn/v1"
        )

        mom = generate_mom(meeting_text)
        points = extract_relevant_points(mom)
        project_key = get_project_key_by_name(config, config["project_name"])

        account_ids = {}
        issues = []

        for desc, assignee in points:
            try:
                acc_id = get_account_id_by_name(config, assignee)
                account_ids[assignee] = acc_id
                issue_data = {
                    "project_key": project_key,
                    "summary": f"Action Item: {desc}",
                    "description": desc,
                    "assignee_account_id": acc_id
                }
                issues.append(create_jira_issue(config, issue_data))
            except Exception as e:
                account_ids[assignee] = f"Error: {e}"
                issues.append(f"Issue failed for {assignee}: {e}")

        return jsonify({"mom": mom, "account_ids": account_ids, "created_issues": issues})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === Run in Production ===
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
