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

#@app.after_request
#def add_ngrok_header(response):
#    response.headers["ngrok-skip-brolikewser-warning"] = "true"
#    return response

@app.after_request
def after_request(response):
    response.headers["ngrok-skip-browser-warning"] = "true"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return response

# Trello credentials
TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
TRELLO_TOKEN   = os.getenv("TRELLO_TOKEN")
TRELLO_BASE    = "https://api.trello.com/1"

# Firebase init (auth only)
cred = credentials.Certificate(os.getenv("FIREBASE_CRED_PATH", "serviceaccount.json"))
firebase_admin.initialize_app(cred)

# Google Drive init
SCOPES = ["https://www.googleapis.com/auth/drive"]
drive_creds = service_account.Credentials.from_service_account_file(
    os.getenv("FIREBASE_CRED_PATH", "serviceaccount.json"), scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=drive_creds)

# MySQL connection
def get_db():
    db_host = os.getenv("DB_HOST", "127.0.0.1")
    db_port = os.getenv("DB_PORT", "3306")
    
    if db_host.startswith("/cloudsql/"):
        return mysql.connector.connect(
            unix_socket=db_host,
            user=os.getenv("DB_USER", "smartcollab"),
            password=os.getenv("DB_PASSWORD", "smartcollab123"),
            database=os.getenv("DB_NAME", "smartcollab")
        )
    else:
        return mysql.connector.connect(
            host=db_host,
            port=db_port,
            user=os.getenv("DB_USER", "smartcollab"),
            password=os.getenv("DB_PASSWORD", "smartcollab123"),
            database=os.getenv("DB_NAME", "smartcollab")
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


@app.route("/")
def home():
    return jsonify({"status": "SmartCollab backend running"})


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

    # 3.Register Trello Webhook for this board automatically
    webhook_url = os.getenv("BACKEND_URL", "https://smartcollab-backend-781602191566.us-central1.run.app")
    requests.post(f"{TRELLO_BASE}/webhooks", json={
        "key":         TRELLO_API_KEY,
        "token":       TRELLO_TOKEN,
        "callbackURL": f"{webhook_url}/trello-webhook",
        "idModel":     board_id,
        "description": f"SmartCollab webhook - {group_name}"
    })

    # 4. Add members to Trello board
    member_trello_usernames = {}
    for email in members:
        member_res = requests.get(f"{TRELLO_BASE}/members/{email}", params={
            "key":   TRELLO_API_KEY,
            "token": TRELLO_TOKEN
        })
        if member_res.status_code == 200:
            member_data = member_res.json()
            member_id = member_data.get("id")
            member_trello_usernames[email] = member_data.get("username")
            if member_id:
                requests.put(f"{TRELLO_BASE}/boards/{board_id}/members/{member_id}", params={
                    "key":   TRELLO_API_KEY,
                    "token": TRELLO_TOKEN,
                    "type":  "normal"
                })

    # 5. Create Google Drive folder
    folder_name = f"{unit} — {group_name}"
    drive_folder_id, drive_folder_url = create_drive_folder(folder_name)

    # 6. Save to MySQL
    group_id = str(uuid.uuid4())
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO groups_table 
        (id, group_name, unit, board_id, board_url, drive_folder_id, drive_folder_url)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (group_id, group_name, unit, board_id, board_url, drive_folder_id, drive_folder_url))

    # 7. Save members to MySQL
    for email in members:
        cursor.execute("""
            INSERT INTO group_members (group_id, user_email, trello_username)
            VALUES (%s, %s, %s)
        """, (group_id, email, member_trello_usernames.get(email)))

    db.commit()
    cursor.close()
    db.close()

    return jsonify({
        "message":          "Group created successfully",
        "group_id":         group_id,
        "board_url":        board_url,
        "drive_folder_url": drive_folder_url
    })


@app.route("/groups", methods=["GET"])
def get_groups():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM groups_table")
    groups = cursor.fetchall()
    cursor.close()
    db.close()
    return jsonify(groups)


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
        ON DUPLICATE KEY UPDATE name=%s
    """, (uid, name, email, role, name))
    db.commit()
    cursor.close()
    db.close()

    return jsonify({"message": "User saved"})

@app.route("/trello-webhook", methods=["POST", "HEAD", "GET"])
def trello_webhook():
    if request.method in ["HEAD", "GET"]:
        return "", 200

    data        = request.json
    action_type = data.get("action", {}).get("type", "")
    member      = data.get("action", {}).get("memberCreator", {}).get("username", "unknown")
    # Resolve Trello username to the student's real email
    db_lookup = get_db()
    cursor_lookup = db_lookup.cursor()
    cursor_lookup.execute("SELECT user_email FROM group_members WHERE trello_username = %s LIMIT 1", (member,))
    email_row = cursor_lookup.fetchone()
    cursor_lookup.close()
    db_lookup.close()
    if email_row:
        member = email_row[0]
    card_name   = data.get("action", {}).get("data", {}).get("card", {}).get("name", "")
    board_id    = data.get("action", {}).get("data", {}).get("board", {}).get("id", "")
    list_before = data.get("action", {}).get("data", {}).get("listBefore", {}).get("name", "")
    list_after  = data.get("action", {}).get("data", {}).get("listAfter", {}).get("name", "")

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
    update_scores(board_id, member, action_type, list_before, list_after)

    return jsonify({"status": "ok"})

# ---
def update_scores(board_id, user_email, action_type, list_before="", list_after=""):
    # Define workflow order — used to detect forward vs backward movement
    workflow_order = {"To Do": 0, "In Progress": 1, "Done": 2, "Submitted": 3}

    weights = {
        "updateCard":          30,
        "addAttachmentToCard": 20,
        "commentCard":         20,
        "createCard":          10,
    }

    # For card moves, only award points if the card moved forward in the workflow
    if action_type == "updateCard":
        before_rank = workflow_order.get(list_before, None)
        after_rank  = workflow_order.get(list_after, None)
        if before_rank is None or after_rank is None or after_rank <= before_rank:
            # Not a genuine forward move (e.g. same list, backward move, or non-list update) — skip scoring
            return

    points = weights.get(action_type, 5)

    column_map = {
        "updateCard":          "tasks_score",
        "createCard":          "tasks_score",
        "addAttachmentToCard": "files_score",
        "commentCard":         "comments_score",
    }
    score_column = column_map.get(action_type, "tasks_score")

    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id FROM groups_table WHERE board_id = %s LIMIT 1", (board_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        db.close()
        return
    group_id = row[0]

    cursor.execute(f"""
        INSERT INTO contribution_scores (group_id, user_email, {score_column})
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
        {score_column} = {score_column} + %s,
        total_score = total_score + %s
    """, (group_id, user_email, points, points, points))

    db.commit()
    cursor.close()
    db.close()
 # ---
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

@app.route("/peer-rating", methods=["POST"])
def peer_rating():
    data        = request.json
    group_id    = data.get("group_id")
    rater_email = data.get("rater_email")
    rated_email = data.get("rated_email")
    score       = data.get("score")

    db = get_db()
    cursor = db.cursor()

    # Check if already rated
    cursor.execute("""
        SELECT id FROM activity_logs
        WHERE group_id = %s AND user_email = %s
        AND action_type = 'peerRating'
        AND description LIKE %s
    """, (group_id, rater_email, f"%{rated_email}%"))
    existing = cursor.fetchone()

    if existing:
        cursor.close()
        db.close()
        return jsonify({"message": "Already rated this member"}), 400

    # Save peer score
    cursor.execute("""
        INSERT INTO contribution_scores (group_id, user_email, peer_score, total_score)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        peer_score = peer_score + %s,
        total_score = total_score + %s
    """, (group_id, rated_email, score, score, score, score))

    # Log the rating action
    cursor.execute("""
        INSERT INTO activity_logs (group_id, user_email, action_type, description)
        VALUES (%s, %s, 'peerRating', %s)
    """, (group_id, rater_email, f"rated {rated_email}: {score}/5"))

    db.commit()
    cursor.close()
    db.close()

    return jsonify({"message": "Rating submitted"})


@app.route("/my-group/<email>", methods=["GET"])
def my_group(email):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT g.*, gm.role as member_role
        FROM groups_table g
        JOIN group_members gm ON g.id = gm.group_id
        WHERE gm.user_email = %s
    """, (email,))
    groups = cursor.fetchall()
    cursor.close()
    db.close()
    return jsonify(groups)


@app.route("/group-members/<path:group_id>", methods=["GET", "OPTIONS"])
def get_group_members(group_id):
    if request.method == "OPTIONS":
        return "", 200
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT user_email, role FROM group_members
        WHERE group_id = %s
    """, (group_id,))
    members = cursor.fetchall()
    cursor.close()
    db.close()
    return jsonify(members)


@app.route("/my-score/<group_id>/<email>", methods=["GET"])
def my_score(group_id, email):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM contribution_scores
        WHERE group_id = %s AND user_email = %s
    """, (group_id, email))
    rows = cursor.fetchall()
    cursor.close()
    db.close()
    return jsonify(rows[0] if rows else {})


# GET USER ROLE POST
@app.route("/get-role", methods=["POST", "OPTIONS"])
def get_role():
    if request.method == "OPTIONS":
        return "", 200
    email = request.json.get("email")
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT role FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    db.close()
    return jsonify(user or {"role": "student"})

# UPDATE GROUP
@app.route("/update-group/<group_id>", methods=["PUT"])
def update_group(group_id):
    data       = request.json
    group_name = data.get("group_name")
    unit       = data.get("unit")
    db         = get_db()
    cursor     = db.cursor()
    cursor.execute("""
        UPDATE groups_table SET group_name = %s, unit = %s
        WHERE id = %s
    """, (group_name, unit, group_id))
    db.commit()
    cursor.close()
    db.close()
    return jsonify({"message": "Group updated"})

# ADD MEMBER
@app.route("/add-member", methods=["POST", "OPTIONS"])
def add_member():
    if request.method == "OPTIONS":
        return "", 200
    data       = request.json
    group_id   = data.get("group_id")
    user_email = data.get("user_email")
    role       = data.get("role", "member")
    db         = get_db()
    cursor     = db.cursor(dictionary=True)

    # Check if already a member
    cursor.execute("""
        SELECT id FROM group_members
        WHERE group_id = %s AND user_email = %s
    """, (group_id, user_email))
    existing = cursor.fetchone()
    if existing:
        cursor.close()
        db.close()
        return jsonify({"message": "Already a member"}), 400

    # Get the board_id for this group
    cursor.execute("SELECT board_id FROM groups_table WHERE id = %s", (group_id,))
    group_row = cursor.fetchone()
    board_id = group_row["board_id"] if group_row else None

    trello_username = None

    # Add to Trello board if board_id exists
    if board_id:
        member_res = requests.get(f"{TRELLO_BASE}/members/{user_email}", params={
            "key":   TRELLO_API_KEY,
            "token": TRELLO_TOKEN
        })
        if member_res.status_code == 200:
            member_data = member_res.json()
            trello_member_id = member_data.get("id")
            trello_username = member_data.get("username")
            if trello_member_id:
                requests.put(f"{TRELLO_BASE}/boards/{board_id}/members/{trello_member_id}", params={
                    "key":   TRELLO_API_KEY,
                    "token": TRELLO_TOKEN,
                    "type":  "normal"
                })

    # Insert into MySQL
    cursor2 = db.cursor()
    cursor2.execute("""
        INSERT INTO group_members (group_id, user_email, role, trello_username)
        VALUES (%s, %s, %s, %s)
    """, (group_id, user_email, role, trello_username))
    db.commit()
    cursor.close()
    cursor2.close()
    db.close()
    return jsonify({"message": "Member added"})

# REMOVE MEMBER
@app.route("/remove-member", methods=["DELETE", "OPTIONS"])
def remove_member():
    data       = request.json
    group_id   = data.get("group_id")
    user_email = data.get("user_email")
    db         = get_db()
    cursor     = db.cursor()
    cursor.execute("""
        DELETE FROM group_members
        WHERE group_id = %s AND user_email = %s
    """, (group_id, user_email))
    db.commit()
    cursor.close()
    db.close()
    return jsonify({"message": "Member removed"})

@app.route("/log-activity", methods=["POST", "OPTIONS"])
def log_activity():
    if request.method == "OPTIONS":
        return "", 200
    data       = request.json
    group_id   = data.get("group_id")
    user_email = data.get("user_email")
    action     = data.get("action", "dashboard_view")

    db = get_db()
    cursor = db.cursor()

    # Log to activity_logs
    cursor.execute("""
        INSERT INTO activity_logs (group_id, user_email, action_type, description)
        VALUES (%s, %s, %s, %s)
    """, (group_id, user_email, "app_activity", action))

    # Update activity_score (5 points per event, cap handled client-side if needed)
    cursor.execute("""
        INSERT INTO contribution_scores (group_id, user_email, activity_score, total_score)
        VALUES (%s, %s, 5, 5)
        ON DUPLICATE KEY UPDATE
        activity_score = activity_score + 5,
        total_score = total_score + 5
    """, (group_id, user_email))

    db.commit()
    cursor.close()
    db.close()
    return jsonify({"message": "Activity logged"})
if __name__ == "__main__":
    app.run(debug=True, port=5000)