"""Log a TestClient in without going through the login page: create the user + session via the stores."""
from redat.auth.principal import CSRF_COOKIE, SESSION_COOKIE


def login(client, *, username="tester", role="user", password="test123!") -> dict:
    users = client.app.state.users
    user = users.get_by_username(username)
    if user is None:
        user = users.create(username, password, role=role)
    token = users.create_session(user["id"], user_agent="pytest", ip="testclient")
    client.cookies.set(SESSION_COOKIE, token)
    return users.get(user["id"])


def csrf(client) -> str:
    """The double-submit token: read the cookie the app set, or plant one."""
    tok = client.cookies.get(CSRF_COOKIE)
    if not tok:
        tok = "test-csrf-token-0123456789abcdef"
        client.cookies.set(CSRF_COOKIE, tok)
    return tok
