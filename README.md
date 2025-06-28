# 📝 Jira MoM Issue Creator

Automatically convert your **meeting transcripts** into **Jira issues** using NLP and Jira REST APIs. Just upload a `.txt` file of your meeting notes, and this app will generate and assign Jira tasks to the appropriate users — no manual entry required!

---

## 🚀 Features

- Upload raw `.txt` transcript from a meeting.
- Automatically generate **Minutes of Meeting (MoM)** using AI.
- Extract actionable **issues** with responsible **assignees**.
- Create Jira issues via API.
- Avoid duplicate issues by checking summaries.
- Clean UI for file and credential submission.

---

## 🛠 Built With

- **Python** (Flask)
- **OpenAI Moonshot API** for MoM generation
- **Jira REST API** for task creation
- **HTML + JS** frontend form
- **Regex** for issue-assignee extraction

---

## 📦 Prerequisites

### 1. Jira Account with API Access
- Generate a Jira **API Token** from [https://id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)

### 2. Moonshot API Key (already integrated in app)
- Using static API key (`sk-...`) for demo purposes.

---

## 📁 Folder Structure

```bash
.
├── app.py                  # Main Flask application
├── sample_transcript.txt   # Sample transcript to test
├── requirements.txt        # Python dependencies
└── README.md               # This file
