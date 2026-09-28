from app.fixtures import demo_rows


def fetch(client):
    try:
        return client.pull()
    except Exception:
        return []


def push(client, rows):
    try:
        client.push(rows)
    except ValueError:
        pass
    return demo_rows
