# FDM User Panel

Flask web panel for managing Firebase Authentication users. Firebase Authentication stores login credentials; Firestore stores usernames, expiry dates, and timestamps. The Windows client software should write the device MAC address to the user's Firestore document after login. User passwords are never written to Firestore or displayed by the panel.

## Local setup (Windows)

1. Create a Firebase project and enable Firebase Authentication and Firestore. The admin identity used by the app needs Firebase Authentication and Firestore access.
2. If `.env` does not exist, copy `.env.example` to `.env`; otherwise, add its Firebase settings to the existing `.env` without replacing existing values. Set a private `FLASK_SECRET_KEY`.
3. To run locally without a service-account JSON key, install the Google Cloud CLI and run `gcloud auth application-default login` using a Google account that has access to the Firebase project. The app uses these Application Default Credentials automatically. Alternatively, `FIREBASE_SERVICE_ACCOUNT` can point to a private service-account key; never put that key in browser code or commit it.
4. Install and run:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   python app.py
   ```

5. Open `http://127.0.0.1:5000` to create and manage accounts. Choose a 7-day, 15-day, 1-month, 3-month, or 6-month package. Expiry is stored as an exact timestamp; while the web process is running, a background task checks once a minute and removes expired accounts from Firebase Authentication and Firestore. The panel does not request or generate a MAC address; the Windows client should save it after the user logs in.

## Render deployment

Deploy this folder as a Render Blueprint using `render.yaml`. Set `FLASK_SECRET_KEY` and provide `FIREBASE_SERVICE_ACCOUNT` credentials in Render, or deploy on a host that supports an attached Google service identity. Set `FIREBASE_PROJECT_ID` and `FIRESTORE_USERS_COLLECTION` if your project uses different values.

The panel follows the old behavior: its management page is directly accessible without an admin login. `/health` checks Firebase Auth and Firestore access. `COOKIE_SECURE` is enabled for Render and should remain enabled for HTTPS deployments.

## Data storage

The application uses Firebase Authentication for account credentials and Firestore for user profiles, expiry dates, and timestamps. The Windows client owns recording device MAC addresses after login. It does not use a SQL database. Existing users from another database must be recreated or imported into Firebase before they appear in this panel.

The user details view shows the username and the MAC address saved by the Windows client. Firebase Authentication does not expose existing passwords, so the panel cannot display them; set a new password through a password-reset flow if one is needed.

## User management CLI

`register_user.py` uses the same Firebase project and credentials as the web app. Run `python register_user.py` to list, add, or remove accounts.
