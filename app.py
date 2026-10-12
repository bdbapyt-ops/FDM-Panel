from flask import Flask, abort, jsonify, render_template_string, request, redirect, session, url_for
import hmac
import os
import re
import secrets
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from firebase_admin import auth, firestore
from firebase_admin.exceptions import FirebaseError
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud.firestore_v1 import FieldFilter

from firebase_service import (
    auth_email,
    get_users_collection,
    initialize_firebase,
    load_environment,
)

load_environment()
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get(
        "COOKIE_SECURE", "true" if os.environ.get("RENDER") else "false"
    ).lower() == "true",
)


def firebase_unavailable(error):
    app.logger.error("Firebase request failed: %s", error)
    message = (
        "Firebase Admin could not access this project. Locally, sign in with "
        "'gcloud auth application-default login' and grant that identity Firebase "
        "Authentication and Firestore access. Deployments need an attached Google "
        "service identity or FIREBASE_SERVICE_ACCOUNT credentials."
    )
    if request.accept_mimetypes.best == "application/json":
        return jsonify({"error": message}), 503
    return (
        render_template_string(
            """
            <!doctype html>
            <html lang="en">
            <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Firebase setup required</title></head>
            <body style="font-family: Segoe UI, Arial, sans-serif; max-width: 680px; margin: 60px auto; padding: 0 20px; line-height: 1.6">
              <h1>Firebase setup required</h1>
              <p>{{ message }}</p>
              <p>See the Firebase setup steps in <code>README.md</code>, then restart the app.</p>
            </body>
            </html>
            """,
            message=message,
        ),
        503,
    )


app.register_error_handler(DefaultCredentialsError, firebase_unavailable)
app.register_error_handler(FirebaseError, firebase_unavailable)
app.register_error_handler(GoogleAPIError, firebase_unavailable)


def csrf_token():
    token = session.get("_csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf():
    token = request.form.get("csrf_token", "")
    expected = session.get("_csrf_token", "")
    if not expected or not hmac.compare_digest(token, expected):
        abort(400, description="Invalid or missing CSRF token.")


def cleanup_expired_users():
    collection = get_users_collection()
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    expired_documents = {}
    for document in collection.where(filter=FieldFilter("expires_at", "<=", now)).stream():
        expired_documents[document.id] = document
    for document in collection.where(filter=FieldFilter("expiry_date", "<", today)).stream():
        expired_documents[document.id] = document

    deleted = 0
    for document in expired_documents.values():
        try:
            auth.delete_user(document.id)
        except auth.UserNotFoundError:
            pass
        except Exception:
            app.logger.exception("Could not delete expired Firebase Auth user %s.", document.id)
            continue
        try:
            document.reference.delete()
            deleted += 1
        except Exception:
            app.logger.exception("Could not delete expired Firestore user %s.", document.id)
    return deleted


def calculate_expiry(package, now=None):
    now = now or datetime.now(timezone.utc)
    if package == "7d":
        return now + timedelta(days=7)
    if package == "15d":
        return now + timedelta(days=15)

    month_durations = {"1m": 1, "3m": 3, "6m": 6}
    if package not in month_durations:
        raise ValueError("Select a valid expiry package.")

    month_index = now.month - 1 + month_durations[package]
    year = now.year + month_index // 12
    month = month_index % 12 + 1
    day = min(now.day, monthrange(year, month)[1])
    return now.replace(year=year, month=month, day=day)


def scheduled_expiry_cleanup():
    try:
        cleanup_expired_users()
    except Exception:
        app.logger.exception("Scheduled expired-user cleanup failed.")


expiry_scheduler = BackgroundScheduler(timezone="UTC", daemon=True)
expiry_scheduler.add_job(
    scheduled_expiry_cleanup,
    "interval",
    minutes=1,
    id="firebase-expiry-cleanup",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)
expiry_scheduler.start()


HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>FDM User Panel</title>
  <style>
    :root {
      --bg: #07111f;
      --panel: #101c31;
      --accent: #00d4ff;
      --accent-2: #5f7cff;
      --text: #f4f7fb;
      --muted: #9fb0c9;
      --danger: #ff5d73;
      --success: #2ed573;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: radial-gradient(circle at top left, #17304f, var(--bg));
      color: var(--text);
      min-height: 100vh;
    }
    .container {
      max-width: 1200px;
      margin: 0 auto;
      padding: 24px;
    }
    .hero {
      background: rgba(255,255,255,0.08);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 24px;
      padding: 28px;
      margin-bottom: 24px;
      box-shadow: 0 16px 40px rgba(0,0,0,0.25);
    }
    .hero h1 { margin: 0 0 8px; font-size: 30px; }
    .hero p { color: var(--muted); margin: 0; font-size: 15px; }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
    }
    .card {
      background: linear-gradient(145deg, #14213d, #0d1628);
      border-radius: 22px;
      padding: 22px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.25);
      border: 1px solid rgba(255,255,255,0.08);
    }
    .card h2 { margin-top: 0; margin-bottom: 14px; font-size: 22px; }
    form { display: flex; flex-direction: column; gap: 12px; }
    input, select {
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid #2b3d5a;
      background: #0b1424;
      color: var(--text);
      outline: none;
    }
    button {
      padding: 12px 16px;
      border: none;
      border-radius: 12px;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
      color: white;
      font-weight: 700;
      cursor: pointer;
      transition: transform 0.2s ease;
    }
    button:hover { transform: translateY(-1px); }
    .message {
      padding: 10px 12px;
      border-radius: 10px;
      margin-bottom: 12px;
      font-weight: 600;
    }
    .success { background: rgba(46,213,115,0.16); color: var(--success); }
    .error { background: rgba(255,93,115,0.16); color: var(--danger); }
    table { width: 100%; border-collapse: collapse; margin-top: 10px; }
    th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid #24344f; }
    th { color: var(--muted); font-weight: 600; }
    .copy-btn {
      padding: 8px 12px;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,0.12);
      background: rgba(0,212,255,0.12);
      color: var(--accent);
      font-weight: 700;
      cursor: pointer;
    }
    .copy-btn.success {
      background: rgba(46,213,115,0.16);
      color: var(--success);
    }
    .copy-btn:hover {
      background: rgba(0,212,255,0.18);
    }
    .details-btn {
      padding: 8px 12px;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,0.12);
      background: rgba(95,124,255,0.16);
      color: #aebcff;
      font-weight: 700;
      cursor: pointer;
    }
    .details-dialog {
      width: min(440px, calc(100% - 32px));
      border: 1px solid #2b3d5a;
      border-radius: 18px;
      padding: 24px;
      background: #101c31;
      color: var(--text);
      box-shadow: 0 20px 60px rgba(0,0,0,0.5);
    }
    .details-dialog::backdrop { background: rgba(0,0,0,0.7); }
    .details-dialog dl { display: grid; grid-template-columns: 120px 1fr; gap: 12px; }
    .details-dialog dt { color: var(--muted); }
    .details-dialog dd { margin: 0; overflow-wrap: anywhere; }
    .details-dialog .password-note { color: var(--muted); font-size: 13px; }
    .details-dialog form { margin-top: 20px; }
    .remove-btn {
      padding: 8px 12px;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,0.12);
      background: rgba(255,93,115,0.14);
      color: var(--danger);
      font-weight: 700;
      cursor: pointer;
      margin-left: 8px;
    }
    .remove-btn:hover {
      background: rgba(255,93,115,0.2);
    }
    .pill {
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(0,212,255,0.16);
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 8px;
    }
    @media (max-width: 820px) {
      .grid { grid-template-columns: 1fr; }
      .container { padding: 16px; }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="hero">
      <h1>FDM User Management</h1>
      <p>Manage user registration, removal, and active user listing with a clean responsive interface.</p>
    </div>

    <div class="grid">
      <div class="card">
        <h2>Create User</h2>
        {% if message %}
          <div class="message {{ message_type }}">{{ message }}</div>
        {% endif %}
        <form method="post" action="{{ url_for('index') }}">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
          <input type="text" name="username" placeholder="Username" required />
          <input type="password" name="password" placeholder="Password" required />
          <select name="expiry_package" required>
            <option value="7d">7 days</option>
            <option value="15d">15 days</option>
            <option value="1m">1 month</option>
            <option value="3m">3 months</option>
            <option value="6m">6 months</option>
          </select>
          <button type="button" class="copy-btn" onclick="copyRegistrationDetails(this)">Copy details</button>
          <button type="submit">Register User</button>
        </form>
      </div>

      <div class="card" id="active-users">
        <h2>Active Users</h2>
        <form method="post" action="{{ url_for('remove_user') }}" style="margin-bottom: 10px;">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
          <input type="text" name="username" placeholder="Username to remove" required />
          <button type="submit">Remove User</button>
        </form>
        <span class="pill">Total: {{ users|length }}</span>
        <table>
          <thead>
            <tr><th>Username</th><th>MAC address</th><th>Expires</th><th>Status</th><th>Action</th></tr>
          </thead>
          <tbody>
            {% for user in users %}
              <tr data-username="{{ user['username'] }}" data-mac="{{ user['mac_address'] or '' }}" data-exp="{{ user['expiry_date'] or 'No expiry' }}" data-last-seen="{{ user['last_seen'] or '' }}">
                <td>{{ user['username'] }}</td>
                <td>{{ user['mac_address'] or 'Not set' }}</td>
                <td>{{ user['expiry_date'] or 'No expiry' }}</td>
                <td class="status-cell"></td>
                <td>
                  <button type="button" class="details-btn" onclick="showUserDetails(this)">View details</button>
                  <form method="post" action="{{ url_for('remove_user') }}" style="display:inline; margin:0; padding:0;">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
                    <input type="hidden" name="username" value="{{ user['username'] }}" />
                    <button type="submit" class="remove-btn">Remove</button>
                  </form>
                </td>
              </tr>
            {% else %}
              <tr><td colspan="5">No users found.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
  <dialog class="details-dialog" id="user-details">
    <h2>User details</h2>
    <dl>
      <dt>Username</dt><dd id="details-username"></dd>
      <dt>Password</dt><dd>Not available</dd>
      <dt>Device MAC</dt><dd id="details-mac"></dd>
      <dt>Expires</dt><dd id="details-expiry"></dd>
    </dl>
    <p class="password-note">Firebase Authentication does not allow existing passwords to be viewed. Reset the password to set a new one.</p>
    <form method="dialog"><button type="submit">Close</button></form>
  </dialog>
  <script>
    function showUserDetails(button) {
      var row = button.closest('tr');
      document.getElementById('details-username').textContent = row.dataset.username || 'Not set';
      document.getElementById('details-mac').textContent = row.dataset.mac || 'Not set';
      document.getElementById('details-expiry').textContent = row.dataset.exp || 'No expiry';
      document.getElementById('user-details').showModal();
    }

    function formatStatus(lastSeen) {
      if (!lastSeen) {
        return 'Never seen';
      }
      var last = new Date(lastSeen);
      var now = new Date();
      var delta = Math.max(0, Math.floor((now - last) / 1000));
      if (delta <= 300) {
        return 'Online';
      }
      var minutes = Math.floor(delta / 60);
      var hours = Math.floor(minutes / 60);
      var days = Math.floor(hours / 24);
      if (days > 0) {
        return 'Offline ' + days + 'd ' + (hours % 24) + 'h ago';
      }
      if (hours > 0) {
        return 'Offline ' + hours + 'h ' + (minutes % 60) + 'm ago';
      }
      return 'Offline ' + minutes + 'm ago';
    }

    function updateStatusCells() {
      document.querySelectorAll('tbody tr').forEach(function(row) {
        var lastSeen = row.dataset.lastSeen;
        var statusCell = row.querySelector('.status-cell');
        if (statusCell) {
          statusCell.textContent = formatStatus(lastSeen);
        }
      });
    }

    function updateStatusFromServer() {
      fetch('{{ url_for('status') }}')
        .then(function(response) { return response.json(); })
        .then(function(data) {
          data.users.forEach(function(user) {
            var row = document.querySelector('tbody tr[data-username="' + CSS.escape(user.username) + '"]');
            if (row) {
              row.dataset.lastSeen = user.last_seen || '';
            }
          });
          updateStatusCells();
        })
        .catch(function() {
          console.warn('Unable to refresh user status.');
        });
    }

    function copyRegistrationDetails(button) {
      var form = button.closest('form');
      var username = form.elements.username.value.trim();
      var password = form.elements.password.value;
      var expiryOption = form.elements.expiry_package.selectedOptions[0];
      var expiry = expiryOption.textContent + ' (until ' + calculateExpiryDate(form.elements.expiry_package.value) + ')';
      if (!username || !password) {
        window.alert('Enter the username and password before copying details.');
        return;
      }
      var text = 'USER: ' + username + ' PASS: ' + password + ' EXP: ' + expiry;

      function calculateExpiryDate(packageValue) {
        var expiryDate = new Date();
        if (packageValue === '7d') {
          expiryDate.setUTCDate(expiryDate.getUTCDate() + 7);
        } else if (packageValue === '15d') {
          expiryDate.setUTCDate(expiryDate.getUTCDate() + 15);
        } else {
          var months = { '1m': 1, '3m': 3, '6m': 6 }[packageValue];
          var day = expiryDate.getUTCDate();
          expiryDate.setUTCDate(1);
          expiryDate.setUTCMonth(expiryDate.getUTCMonth() + months);
          var lastDay = new Date(Date.UTC(
            expiryDate.getUTCFullYear(),
            expiryDate.getUTCMonth() + 1,
            0
          )).getUTCDate();
          expiryDate.setUTCDate(Math.min(day, lastDay));
        }
        return expiryDate.toISOString().slice(0, 10);
      }

      function showCopied() {
        var original = button.textContent;
        button.textContent = 'Copied!';
        button.classList.add('success');
        setTimeout(function() {
          button.textContent = original;
          button.classList.remove('success');
        }, 1500);
      }

      function copyFallback(textValue) {
        var textarea = document.createElement('textarea');
        textarea.value = textValue;
        textarea.style.position = 'fixed';
        textarea.style.top = '0';
        textarea.style.left = '0';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        try {
          var successful = document.execCommand('copy');
          if (successful) {
            showCopied();
          } else {
            window.alert('Copy failed. Please copy manually.');
          }
        } catch (err) {
          window.alert('Copy failed. Please copy manually.');
        } finally {
          document.body.removeChild(textarea);
        }
      }

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function() {
          showCopied();
        }).catch(function() {
          copyFallback(text);
        });
      } else {
        copyFallback(text);
      }
    }

    document.addEventListener('DOMContentLoaded', function() {
      updateStatusCells();
      updateStatusFromServer();
      setInterval(updateStatusFromServer, 300000);
    });
  </script>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def index():
    message = session.pop("message", None)
    message_type = session.pop("message_type", "")
    if request.method == "POST":
        validate_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        expiry_package = request.form.get("expiry_package", "").strip()

        if not username or not password:
            message = "Username and password are required."
            message_type = "error"
        elif len(username) < 3 or len(username) > 32:
            message = "Username must be between 3 and 32 characters."
            message_type = "error"
        elif any(char.isspace() for char in username):
            message = "Username cannot contain spaces."
            message_type = "error"
        elif not re.fullmatch(r"[A-Za-z0-9_.-]+", username):
            message = "Username can only contain letters, numbers, dot, underscore, or dash."
            message_type = "error"
        elif len(password) < 6:
            message = "Password must be at least 6 characters long."
            message_type = "error"
        else:
            try:
                expires_at = calculate_expiry(expiry_package)
            except ValueError as exc:
                message = str(exc)
                message_type = "error"
                expires_at = None

            if message is None:
                firebase_user = None
                try:
                    firebase_user = auth.create_user(
                        email=auth_email(username),
                        password=password,
                        display_name=username,
                    )
                    get_users_collection().document(firebase_user.uid).set(
                        {
                            "username": username,
                            "expiry_package": expiry_package,
                            "expiry_date": expires_at.date().isoformat(),
                            "expires_at": expires_at,
                            "created_at": firestore.SERVER_TIMESTAMP,
                            "last_seen": firestore.SERVER_TIMESTAMP,
                        }
                    )
                    message = (
                        f"User '{username}' registered successfully. "
                        f"Package: {expiry_package}; expires on {expires_at.date().isoformat()}."
                    )
                    message_type = "success"
                except Exception as exc:
                    if firebase_user is not None:
                        try:
                            auth.delete_user(firebase_user.uid)
                        except Exception:
                            app.logger.exception("Could not roll back Firebase Auth user after Firestore write failed.")
                    app.logger.exception("Firebase user registration failed.")
                    message = f"Registration failed: {exc}"
                    message_type = "error"

    cleanup_expired_users()
    metadata = {
        document.id: document.to_dict()
        for document in get_users_collection().stream()
    }
    users = []
    for firebase_user in auth.list_users().iterate_all():
        data = metadata.get(firebase_user.uid, {})
        last_seen = data.get("last_seen")
        users.append(
            {
                "username": firebase_user.display_name or data.get("username") or firebase_user.email or firebase_user.uid,
                "mac_address": data.get("mac_address"),
                "expiry_date": data.get("expiry_date"),
                "last_seen": last_seen.isoformat() if hasattr(last_seen, "isoformat") else None,
            }
        )
    users.sort(key=lambda user: user["username"].casefold())
    return render_template_string(
        HTML_TEMPLATE,
        users=users,
        message=message,
        message_type=message_type,
        csrf_token=csrf_token(),
    )


@app.route("/status", methods=["GET"])
def status():
    metadata = {
        document.id: document.to_dict()
        for document in get_users_collection().stream()
    }
    users = []
    for firebase_user in auth.list_users().iterate_all():
        last_seen = metadata.get(firebase_user.uid, {}).get("last_seen")
        users.append(
            {
                "username": firebase_user.display_name or firebase_user.email or firebase_user.uid,
                "last_seen": last_seen.isoformat() if hasattr(last_seen, "isoformat") else None,
            }
        )
    return jsonify({"users": users})


@app.route("/remove", methods=["POST"])
def remove_user():
    validate_csrf()
    username = request.form.get("username", "").strip()
    try:
        cleanup_expired_users()
        firebase_user = auth.get_user_by_email(auth_email(username))
        auth.delete_user(firebase_user.uid)
        get_users_collection().document(firebase_user.uid).delete()
        message = f"User '{username}' removed successfully."
        message_type = "success"
    except auth.UserNotFoundError:
        message = f"User '{username}' not found."
        message_type = "error"
    except Exception as exc:
        app.logger.exception("Firebase user removal failed.")
        message = f"Removal failed: {exc}"
        message_type = "error"

    session["message"] = message
    session["message_type"] = message_type
    return redirect(url_for("index", _anchor="active-users"))


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": csrf_token}


@app.route("/health")
def health():
    try:
        initialize_firebase()
        get_users_collection().limit(1).get()
        list(auth.list_users(max_results=1).iterate_all())
    except Exception:
        app.logger.exception("Firebase health check failed.")
        return jsonify({"status": "error", "service": "firebase"}), 503
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "").lower() == "true")
