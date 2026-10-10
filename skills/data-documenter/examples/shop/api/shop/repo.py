import sqlite3


class OrderRepo:
    """Stores orders."""

    def __init__(self, path):
        self.conn = sqlite3.connect(path)

    def save(self, order):
        self.conn.execute("INSERT INTO orders (id, total) VALUES (?, ?)", (order["id"], order["total"]))
        return order


def make_repo(path):
    return OrderRepo(path)
