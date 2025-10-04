package main

import (
	"log"
	"os"
)

func main() {
	// Setup logging
	log.SetFlags(log.LstdFlags | log.Lshortfile)

	// Create logs directory
	homeDir, err := os.UserHomeDir()
	if err != nil {
		log.Printf("Warning: could not get home directory: %v", err)
	} else {
		logDir := homeDir + "/.config/gmail-notifier"
		os.MkdirAll(logDir, 0755)
		logFile, err := os.OpenFile(logDir+"/gmail-notifier.log", os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
		if err == nil {
			log.SetOutput(logFile)
			defer logFile.Close()
		}
	}

	log.Println("Starting Gmail Notifier...")

	// Create and run the UI
	ui := NewTrayUI()
	ui.Run()
}
