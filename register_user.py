#!/usr/bin/env python3
import argparse
import getpass
import os
import re
import sqlite3
import sys

try:
    import psycopg2
except Exception:
    psycopg2 = None


def get_database_url():
    return os.getenv("DATABASE_URL", "").strip() or None


def connect_db():
    database_url = get_database_url()
    if database_url:
        if psycopg2 is None:
            raise RuntimeError("Missing dependency 'psycopg2'. Install with: pip install -r requirements.txt")
        conn = psycopg2.connect(database_url)
        return conn, "postgres"

    conn = sqlite3.connect("users.db")
    return conn, "sqlite"


def close_connection(conn, db_type):
    if conn is None:
        return
    conn.close()


def ensure_table(conn, db_type):
    if db_type == "postgres":
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                );
                """
            )
        conn.commit()
        return

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()


def validate_username(username):
    username = username.strip()
    if not username:
        raise ValueError("Username is required")
    if len(username) < 3 or len(username) > 32:
        raise ValueError("Username must be between 3 and 32 characters")
    if any(char.isspace() for char in username):
        raise ValueError("Username cannot contain spaces")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", username):
        raise ValueError("Username can only contain letters, numbers, dot, underscore, or dash")
    return username


def validate_password(password):
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long")
    return password


def user_exists(conn, db_type, username):
    if db_type == "postgres":
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE username = %s LIMIT 1", (username,))
            return cur.fetchone() is not None

    row = conn.execute("SELECT 1 FROM users WHERE username = ? LIMIT 1", (username,)).fetchone()
    return row is not None


def create_user(conn, db_type, username, password):
    if db_type == "postgres":
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
        conn.commit()
        return

    conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
    conn.commit()


def delete_user(conn, db_type, username):
    if db_type == "postgres":
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE username = %s", (username,))
            deleted = cur.rowcount
        conn.commit()
        return deleted

    cursor = conn.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    return cursor.rowcount


def list_users(conn, db_type):
    if db_type == "postgres":
        with conn.cursor() as cur:
            cur.execute("SELECT username, created_at FROM users ORDER BY username")
            return [
                {"username": row[0], "created_at": row[1]}
                for row in cur.fetchall()
            ]

    rows = conn.execute("SELECT username, created_at FROM users ORDER BY username").fetchall()
    return [{"username": row[0], "created_at": row[1]} for row in rows]


def parse_args():
    parser = argparse.ArgumentParser(description="Manage FDM users")
    parser.add_argument("--list", action="store_true", help="List all registered users")
    parser.add_argument("--remove", metavar="USERNAME", help="Remove a user")
    return parser.parse_args()


def main():
    args = parse_args()
    conn = None
    db_type = "sqlite"

    try:
        conn, db_type = connect_db()
        ensure_table(conn, db_type)

        if args.list:
            users = list_users(conn, db_type)
            if users:
                print("\nRegistered users:")
                for user in users:
                    print(f"- {user['username']}")
            else:
                print("No users found.")
            return

        if args.remove is not None:
            username = validate_username(args.remove)
            deleted = delete_user(conn, db_type, username)
            if deleted:
                print(f"✅ User '{username}' removed successfully.")
            else:
                print(f"User '{username}' not found.")
            return

        print("FDM user management")
        print("1. View all users")
        print("2. Register user")
        print("3. Remove user")
        choice = input("Choose option (1/2/3): ").strip()

        if choice == "1":
            users = list_users(conn, db_type)
            if users:
                print("\nRegistered users:")
                for user in users:
                    print(f"- {user['username']}")
            else:
                print("No users found.")
            return

        if choice == "3":
            username = input("Username to remove: ").strip()
            username = validate_username(username)
            deleted = delete_user(conn, db_type, username)
            if deleted:
                print(f"✅ User '{username}' removed successfully.")
            else:
                print(f"User '{username}' not found.")
            return

        username = validate_username(input("Username: ").strip())
        password = getpass.getpass("Password: ")
        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            print("Passwords do not match", file=sys.stderr)
            sys.exit(1)
        validate_password(password)

        if user_exists(conn, db_type, username):
            print("Error: username already exists", file=sys.stderr)
            sys.exit(1)

        create_user(conn, db_type, username, password)
        print(f"✅ User '{username}' created successfully.")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if conn is not None:
            close_connection(conn, db_type)


if __name__ == "__main__":
    main()
