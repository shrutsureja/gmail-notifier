package main

import (
	"time"

	"github.com/shrutsureja/gmail-notifier/internal/config"
	"github.com/shrutsureja/gmail-notifier/internal/imap"
)

func main() {
	cfg, err := config.GetConfig()
	if err != nil {
		panic(err)
	}

	if len(cfg.Accounts) == 0 {
		panic("No accounts found in config.json")
	}

	imap.ConnectAndFetch(cfg.Accounts[0])
	time.Sleep(10 * time.Minute)
}
