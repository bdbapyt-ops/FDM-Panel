from flask import Flask, jsonify, render_template_string, request, redirect, url_for
import os
import re
import sys
from datetime import date
from pathlib import Path

try:
    import psycopg2
except Exception:
    psycopg2 = None

app = Flask(__name__)


def load_environment():
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.getenv(key):
            os.environ[key] = value


load_environment()


def get_database_url():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Set it before running the app.")
    return database_url


def get_db():
    database_url = get_database_url()
    if psycopg2 is None:
        raise RuntimeError("Missing dependency 'psycopg2'. Install with: pip install -r requirements.txt")
    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    return conn


def init_db():
    try:
        conn = get_db()
    except Exception as exc:
        print(f"Database initialization skipped: {exc}", file=sys.stderr)
        return False

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    expiry_date DATE,
                    last_seen TIMESTAMP WITH TIME ZONE
                )
                """
            )
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS expiry_date DATE")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP WITH TIME ZONE")
        conn.commit()
    finally:
        conn.close()

    return True


def cleanup_expired_users(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE expiry_date IS NOT NULL AND expiry_date < CURRENT_DATE")
        deleted = cur.rowcount
    conn.commit()
    return deleted


def normalize_expiry_date(raw_value):
    if not raw_value:
        return None
    try:
        expiry_date = date.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError("Please select a valid expiry date") from exc
    if expiry_date < date.today():
        raise ValueError("Expiry date must be today or a future date")
    return expiry_date


init_db()

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
    input {
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
          <input type="text" name="username" placeholder="Username" required />
          <input type="password" name="password" placeholder="Password" required />
          <input type="date" name="expiry_date" />
          <button type="submit">Register User</button>
        </form>
      </div>

      <div class="card" id="active-users">
        <h2>Active Users</h2>
        <form method="post" action="{{ url_for('remove_user') }}" style="margin-bottom: 10px;">
          <input type="text" name="username" placeholder="Username to remove" required />
          <button type="submit">Remove User</button>
        </form>
        <span class="pill">Total: {{ users|length }}</span>
        <table>
          <thead>
            <tr><th>Username</th><th>Expires</th><th>Status</th><th>Action</th></tr>
          </thead>
          <tbody>
            {% for user in users %}
              <tr data-username="{{ user['username'] }}" data-password="{{ user['password'] }}" data-exp="{{ user['expiry_date'] or 'No expiry' }}" data-last-seen="{{ user['last_seen'] or '' }}">
                <td>{{ user['username'] }}</td>
                <td>{{ user['expiry_date'] or 'No expiry' }}</td>
                <td class="status-cell"></td>
                <td>
                  <button type="button" class="copy-btn" onclick="copyUser(this)">Copy</button>
                  <form method="post" action="{{ url_for('remove_user') }}" style="display:inline; margin:0; padding:0;">
                    <input type="hidden" name="username" value="{{ user['username'] }}" />
                    <button type="submit" class="remove-btn">Remove</button>
                  </form>
                </td>
              </tr>
            {% else %}
              <tr><td colspan="3">No users found.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
  <script>
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

    function copyUser(button) {
      var row = button.closest('tr');
      var username = row.dataset.username || '';
      var password = row.dataset.password || '';
      var expiry = row.dataset.exp || 'No expiry';
      var text = 'USER: ' + username + ' PASS: ' + password + ' EXP: ' + expiry;

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
    message = None
    message_type = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        expiry_date_raw = request.form.get("expiry_date", "").strip()

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
                expiry_date = normalize_expiry_date(expiry_date_raw)
            except ValueError as exc:
                message = str(exc)
                message_type = "error"
                expiry_date = None

            if message is None:
                conn = get_db()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO users (username, password, expiry_date, last_seen) VALUES (%s, %s, %s, now())",
                            (username, password, expiry_date),
                        )
                    conn.commit()
                    if expiry_date is None:
                        message = f"User '{username}' registered successfully."
                    else:
                        message = f"User '{username}' registered successfully. It will expire on {expiry_date.strftime('%Y-%m-%d')}."
                    message_type = "success"
                except Exception as exc:
                    message = f"Registration failed: {exc}"
                    message_type = "error"
                finally:
                    conn.close()

    conn = get_db()
    try:
        cleanup_expired_users(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT username, password, created_at, expiry_date, last_seen FROM users ORDER BY username")
            users = [
                {
                    "username": row[0],
                    "password": row[1],
                    "created_at": row[2],
                    "expiry_date": row[3].strftime("%Y-%m-%d") if row[3] else None,
                    "last_seen": row[4].isoformat() if row[4] else None,
                }
                for row in cur.fetchall()
            ]
    finally:
        conn.close()
    return render_template_string(HTML_TEMPLATE, users=users, message=message, message_type=message_type)


@app.route("/status", methods=["GET"])
def status():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT username, last_seen FROM users ORDER BY username")
            users = [
                {
                    "username": row[0],
                    "last_seen": row[1].isoformat() if row[1] else None,
                }
                for row in cur.fetchall()
            ]
    finally:
        conn.close()
    return jsonify({"users": users})


@app.route("/remove", methods=["POST"])
def remove_user():
    username = request.form.get("username", "").strip()
    conn = get_db()
    try:
        cleanup_expired_users(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE username = %s", (username,))
            deleted = cur.rowcount
        conn.commit()
        if deleted > 0:
            message = f"User '{username}' removed successfully."
            message_type = "success"
        else:
            message = f"User '{username}' not found."
            message_type = "error"
    except Exception as exc:
        message = f"Removal failed: {exc}"
        message_type = "error"
    finally:
        conn.close()

    return redirect(url_for("index", _anchor="active-users"))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
