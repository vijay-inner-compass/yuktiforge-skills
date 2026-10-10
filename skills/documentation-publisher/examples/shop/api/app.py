from flask import Flask

from shop.service import OrderService

app = Flask(__name__)
service = OrderService()


@app.route("/orders", methods=["POST"])
def create_order():
    return service.place({"id": 1, "total": 5})


@app.get("/health")
def health():
    return "ok"


if __name__ == "__main__":
    app.run()
