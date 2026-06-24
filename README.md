# SmartCollab

## Overview

SmartCollab is a web-based collaborative project management platform developed using Flask. The application enables users to create and manage groups, collaborate with team members, track contributions, and integrate with external productivity services such as Trello, Firebase, and Google Drive.

The project aims to improve team coordination by providing a centralized workspace where users can organize tasks, manage memberships, and evaluate individual contributions using AI-assisted scoring mechanisms.

---

## Features

### User Management

* User registration and authentication
* Secure login system
* User profile management

### Group Collaboration

* Create and manage project groups
* Add and remove group members
* View group information and member lists

### AI Contribution Scoring

* Analyze and evaluate team member contributions
* Generate contribution scores using AI-based assessment techniques
* Support fair evaluation of group participation

### Third-Party Integrations

* Trello integration for task management
* Firebase integration for cloud services
* Google Drive integration for file storage and sharing

### Database Management

* Store user and group information in a relational database
* Maintain project and collaboration records

---

## System Architecture

The application follows a client-server architecture:

* **Frontend:** HTML, CSS, and JavaScript
* **Backend:** Flask (Python)
* **Database:** MySQL
* **Cloud Services:** Firebase and Google Drive APIs
* **Project Management Integration:** Trello API

---

## Technologies Used

* Python
* Flask
* MySQL
* HTML5
* CSS3
* JavaScript
* Firebase
* Google Drive API
* Trello API
* Git
* GitHub

---

## Installation and Setup

### Prerequisites

Before running the application, ensure the following are installed:

* Python 3.x
* pip
* MySQL
* Git

### Clone the Repository

```bash
git clone https://github.com/linuseli98-ngunjiri/smartcollab.git
cd smartcollab
```

### Create a Virtual Environment

```bash
python -m venv venv
```

Activate the virtual environment:

**Linux/macOS**

```bash
source venv/bin/activate
```

**Windows**

```bash
venv\Scripts\activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Configure Environment Variables

Create a `.env` file and add the required configuration values:

```env
DATABASE_HOST=your_host
DATABASE_USER=your_username
DATABASE_PASSWORD=your_password
DATABASE_NAME=your_database
```

### Run the Application

```bash
python app.py
```

The application will be available at:

```
http://127.0.0.1:5000
```

---

## Project Structure

```text
smartcollab/
│
├── static/
├── templates/
├── app.py
├── .gitignore
├── README.md
└── requirements.txt
```

---

## Future Improvements

* Real-time team collaboration features
* Advanced analytics dashboard
* Notification and messaging system
* Mobile-responsive user interface
* Expanded AI-based performance evaluation
* Role-based access control

---

## Author

**Linus Eli**

GitHub: https://github.com/linuseli98-ngunjiri

---

## License

This project is intended for educational and learning purposes.
