from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth
from googleapiclient.discovery import build
from google.oauth2 import service_account
import mysql.connector
from datetime import datetime
import uuid

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app, origins="*")

@app.after_request
def add_ngrok_header(response):
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response
# Trello credentials
TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
TRELLO_TOKEN   = os.getenv("TRELLO_TOKEN")
TRELLO_BASE    = "https://api.trello.com/1"

# Firebase init (auth only)
cred = credentials.Certificate("serviceaccount.json")
firebase_admin.initialize_app(cred)

# Google Drive init
SCOPES = ["https://www.googleapis.com/auth/drive"]
drive_creds = service_account.Credentials.from_service_account_file(
    "serviceaccount.json", scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=drive_creds)

# MySQL connection
def get_db():
    return mysql.connector.connect(
        host="127.0.0.1",
        user="smartcollab",
        password="smartcollab123",
        database="smartcollab"
    )

def create_drive_folder(folder_name):
    file_metadata = {
        "name":     folder_name,
        "mimeType": "application/vnd.google-apps.folder"
    }
    folder = drive_service.files().create(
        body=file_metadata,
        fields="id, webViewLink"
    ).execute()
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

    # 4. Save to MySQL
    group_id = str(uuid.uuid4())
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO groups_table 
        (id, group_name, unit, board_id, board_url, drive_folder_id, drive_folder_url)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (group_id, group_name, unit, board_id, board_url, drive_folder_id, drive_folder_url))

    # 5. Save members to MySQL
    for email in members:
        cursor.execute("""
            INSERT INTO group_members (group_id, user_email)
            VALUES (%s, %s)
        """, (group_id, email))

    db.commit()
    cursor.close()
    db.close()

    return jsonify({
        "message":          "Group created successfully",
        "group_id":         group_id,
        "board_url":        board_url,
        "drive_folder_url": drive_folder_url
    })

# ── GET ALL GROUPS ──
@app.route("/groups", methods=["GET"])
def get_groups():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM groups_table")
    groups = cursor.fetchall()
    cursor.close()
    db.close()
    return jsonify(groups)

# ── SAVE USER TO DB ON LOGIN ──
@app.route("/save-user", methods=["POST"])
def save_user():
    data  = request.json
    uid   = data.get("uid")
    name  = data.get("name")
    email = data.get("email")
    role  = data.get("role", "student")

    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO users (id, name, email, role)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE name=%s, role=%s
    """, (uid, name, email, role, name, role))
    db.commit()
    cursor.close()
    db.close()

    return jsonify({"message": "User saved"})
# ── TRELLO WEBHOOK ──
@app.route("/trello-webhook", methods=["POST", "HEAD", "GET"])
def trello_webhook():
    if request.method in ["HEAD", "GET"]:
        return "", 200

    data        = request.json
    action_type = data.get("action", {}).get("type", "")
    member      = data.get("action", {}).get("memberCreator", {}).get("username", "unknown")
    card_name   = data.get("action", {}).get("data", {}).get("card", {}).get("name", "")
    board_id    = data.get("action", {}).get("data", {}).get("board", {}).get("id", "")

    # Map action type to description
    descriptions = {
        "updateCard":           f"moved card: {card_name}",
        "commentCard":          f"commented on card: {card_name}",
        "addAttachmentToCard":  f"uploaded file to card: {card_name}",
        "createCard":           f"created card: {card_name}",
    }
    description = descriptions.get(action_type, action_type)

    # Save to activity_logs
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO activity_logs (group_id, user_email, action_type, description)
        SELECT id, %s, %s, %s FROM groups_table WHERE board_id = %s LIMIT 1
    """, (member, action_type, description, board_id))
    db.commit()
    cursor.close()
    db.close()

    # Update contribution scores
    update_scores(board_id, member, action_type)

    return jsonify({"status": "ok"})

# ── UPDATE CONTRIBUTION SCORES ──
def update_scores(board_id, user_email, action_type):
    weights = {
        "updateCard":          30,
        "addAttachmentToCard": 20,
        "commentCard":         20,
        "createCard":          10,
    }
    points = weights.get(action_type, 5)

    db = get_db()
    cursor = db.cursor()

    # Get group_id from board_id
    cursor.execute("SELECT id FROM groups_table WHERE board_id = %s LIMIT 1", (board_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        db.close()
        return
    group_id = row[0]

    # Upsert contribution score
    cursor.execute("""
        INSERT INTO contribution_scores (group_id, user_email, tasks_score)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
        tasks_score = tasks_score + %s,
        total_score = total_score + %s
    """, (group_id, user_email, points, points, points))

    db.commit()
    cursor.close()
    db.close()
 # ── GET CONTRIBUTION SCORES ──
@app.route("/scores/<group_id>", methods=["GET"])
def get_scores(group_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT user_email, tasks_score, files_score, 
               comments_score, activity_score, peer_score, total_score
        FROM contribution_scores
        WHERE group_id = %s
        ORDER BY total_score DESC
    """, (group_id,))
    scores = cursor.fetchall()
    cursor.close()
    db.close()
    return jsonify(scores)  
if __name__ == "__main__":
    app.run(debug=True, port=5000)
