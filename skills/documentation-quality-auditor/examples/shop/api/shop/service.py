import os

import requests
from .repo import OrderRepo, make_repo
from . import repo as repo_module


class OrderService:
    def __init__(self):
        self.repo = make_repo(os.environ["DB_PATH"])

    def place(self, order):
        self.validate(order)
        requests.post("https://billing.example.com/charge", json=order)
        repo_module.make_repo("x")
        return self.repo.save(order)

    def validate(self, order):
        return bool(order)
