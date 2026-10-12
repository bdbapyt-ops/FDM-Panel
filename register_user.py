#!/usr/bin/env python3
import getpass
import sys

try:
    from firebase_admin import auth
    from firebase_admin import firestore
    from firebase_service import (
        auth_email,
        get_users_collection,
        initialize_firebase,
    )
except ImportError:
    print("Missing Firebase dependencies. From this folder run: python -m pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


def user_exists(username):
    try:
        auth.get_user_by_email(auth_email(username))
        return True
    except auth.UserNotFoundError:
        return False


def create_user(username, password):
    return auth.create_user(
        email=auth_email(username),
        password=password,
        display_name=username,
    )


def delete_user(username):
    try:
        user = auth.get_user_by_email(auth_email(username))
    except auth.UserNotFoundError:
        return False
    auth.delete_user(user.uid)
    return True


def list_users():
    return sorted(user.display_name for user in auth.list_users().iterate_all() if user.display_name)


def migrate_firestore_users(users):
    migrated = 0
    skipped = 0
    target_collection = get_users_collection()
    for document in list(users.stream()):
        data = document.to_dict()
        username = data.get("username")
        password = data.get("password")
        if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
            print(f"Skipped Firestore document '{document.id}': username or password is missing.")
            skipped += 1
            continue
        if user_exists(username):
            print(f"Skipped '{username}': Firebase Authentication account already exists.")
            skipped += 1
            continue
        firebase_user = create_user(username, password)
        try:
            target_collection.document(firebase_user.uid).set(
                {
                    "username": username,
                    "expiry_date": data.get("expiry_date"),
                    "created_at": data.get("created_at") or firestore.SERVER_TIMESTAMP,
                    "last_seen": data.get("last_seen"),
                }
            )
        except Exception:
            try:
                auth.delete_user(firebase_user.uid)
            except Exception:
                print(
                    f"Rollback failed for '{username}' (UID {firebase_user.uid}); "
                    "remove that Firebase Auth user manually.",
                    file=sys.stderr,
                )
            raise
        print(f"Migrated '{username}'.")
        migrated += 1
    return migrated, skipped


def main():
    print("FDM user management")
    print("1. View all users")
    print("2. Register user")
    print("3. Remove user")
    print("4. Migrate users from the old Firestore collection")
    choice = input("Choose option (1/2/3/4): ").strip()

    try:
        initialize_firebase()

        if choice == "1":
            usernames = list_users()
            if usernames:
                print("\nRegistered users:")
                for username in usernames:
                    print(f"- {username}")
            else:
                print("No users found.")
            return

        if choice == "3":
            username = input("Username to remove: ").strip()
            if not username:
                print("Username is required", file=sys.stderr)
                sys.exit(1)
            deleted = delete_user(username)
            if deleted:
                print(f"User '{username}' removed from Firebase Authentication.")
            else:
                print(f"User '{username}' not found in Firebase Authentication.")
            return

        if choice == "4":
            migrated, skipped = migrate_firestore_users(get_users_collection())
            print(f"Migration complete: {migrated} migrated, {skipped} skipped.")
            print("Old Firestore documents were left unchanged.")
            return

        if choice != "2":
            print("Invalid option", file=sys.stderr)
            sys.exit(1)

        username = input("Username: ").strip()
        if not username:
            print("Username is required", file=sys.stderr)
            sys.exit(1)

        password = getpass.getpass("Password: ")
        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            print("Passwords do not match", file=sys.stderr)
            sys.exit(1)
        if len(password) < 6:
            print("Password must be at least 6 characters.", file=sys.stderr)
            sys.exit(1)

        if user_exists(username):
            print("Error: username already exists", file=sys.stderr)
            sys.exit(1)

        firebase_user = create_user(username, password)
        try:
            get_users_collection().document(firebase_user.uid).set(
                {
                    "username": username,
                    "expiry_date": None,
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "last_seen": firestore.SERVER_TIMESTAMP,
                }
            )
        except Exception:
            try:
                auth.delete_user(firebase_user.uid)
            except Exception:
                print(
                    f"Rollback failed for '{username}' (UID {firebase_user.uid}); "
                    "remove that Firebase Auth user manually.",
                    file=sys.stderr,
                )
            raise
        print(f"User '{username}' created in Firebase Authentication and Firestore.")
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
