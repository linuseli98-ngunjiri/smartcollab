from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from googleapiclient.discovery import build
from google.oauth2 import service_account

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Trello credentials
TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
TRELLO_TOKEN   = os.getenv("TRELLO_TOKEN")
TRELLO_BASE    = "https://api.trello.com/1"

# Firebase init
cred = credentials.Certificate("serviceaccount.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Google Drive init
SCOPES = ["https://www.googleapis.com/auth/drive"]
drive_creds = service_account.Credentials.from_service_account_file(
    "serviceaccount.json", scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=drive_creds)

def create_drive_folder(folder_name):
    """Creates a folder in Google Drive and returns its ID and URL."""
    file_metadata = {
        "name":     folder_name,
        "mimeType": "application/vnd.google-apps.folder"
    }
    folder = drive_service.files().create(
        body=file_metadata,
        fields="id, webViewLink"
    ).execute()

    # Make folder accessible to anyone with the link
    drive_service.permissions().create(
        fileId=folder["id"],
        body={"type": "anyone", "role": "writer"}
    ).execute()

    return folder["id"], folder["webViewLink"]

# ── TEST ROUTE ──
@app.route("/")
def home():
    return jsonify({"status": "SmartCollab backend running"})

# ── CREATE GROUP ──
@app.route("/create-group", methods=["POST"])
def create_group():
    data       = request.json
    group_name = data.get("group_name")
    members    = data.get("members", [])
    unit       = data.get("unit", "General")

    # 1. Create Trello board
    board_res = requests.post(f"{TRELLO_BASE}/boards/", params={
        "name":         f"{unit} — {group_name}",
        "defaultLists": "false",
        "key":          TRELLO_API_KEY,
        "token":        TRELLO_TOKEN
    })
    board     = board_res.json()
    board_id  = board["id"]
    board_url = board["url"]

    # 2. Create default Trello lists
    for list_name in ["To Do", "In Progress", "Done", "Submitted"]:
        requests.post(f"{TRELLO_BASE}/lists", params={
            "name":    list_name,
            "idBoard": board_id,
            "key":     TRELLO_API_KEY,
            "token":   TRELLO_TOKEN
        })

    # 3. Create Google Drive folder
    folder_name = f"{unit} — {group_name}"
    drive_folder_id, drive_folder_url = create_drive_folder(folder_name)

    # 4. Save group to Firestore
    group_ref = db.collection("groups").document()
    group_ref.set({
        "group_name":       group_name,
        "unit":             unit,
        "members":          members,
        "board_id":         board_id,
        "board_url":        board_url,
        "drive_folder_id":  drive_folder_id,
        "drive_folder_url": drive_folder_url,
        "created_at":       firestore.SERVER_TIMESTAMP
    })

    return jsonify({
        "message":          "Group created successfully",
        "group_id":         group_ref.id,
        "board_url":        board_url,
        "drive_folder_url": drive_folder_url
    })

# ── GET ALL GROUPS ──
@app.route("/groups", methods=["GET"])
def get_groups():
    groups = db.collection("groups").stream()
    result = []
    for g in groups:
        data = g.to_dict()
        data["id"] = g.id
        result.append(data)
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
