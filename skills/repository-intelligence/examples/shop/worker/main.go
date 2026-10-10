package main

import (
	"net/http"
	"os"

	"os"
)

func main() {
	broker := os.Getenv("KAFKA_BROKER")
	queue.Consume(broker)
	http.HandleFunc("/healthz", nil)
}
