from getpass import getpass
from server_pull import configure, status, pull
configure("https://gp3-bandit-2026.onrender.com")
username = input("Group username: ").strip()
password = getpass("Group password: ")
print(status(username, password))  # Uses no pulls