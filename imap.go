package main

import (
	"fmt"
	"log"
	"time"

	idle "github.com/emersion/go-imap-idle"
	"github.com/emersion/go-imap/client"
)

const (
	imapServer = "imap.gmail.com:993"
)

// IMAPClient represents an IMAP client for a single account
type IMAPClient struct {
	account  Account
	client   *client.Client
	idleStop chan struct{}
	onUpdate func(email string, count uint32)
}

// NewIMAPClient creates a new IMAP client
func NewIMAPClient(account Account, onUpdate func(email string, count uint32)) *IMAPClient {
	return &IMAPClient{
		account:  account,
		idleStop: make(chan struct{}),
		onUpdate: onUpdate,
	}
}

// Connect connects to the IMAP server
func (ic *IMAPClient) Connect() error {
	// Connect to server
	c, err := client.DialTLS(imapServer, nil)
	if err != nil {
		return fmt.Errorf("failed to connect: %w", err)
	}

	// Login
	if err := c.Login(ic.account.Email, ic.account.Password); err != nil {
		c.Logout()
		return fmt.Errorf("failed to login: %w", err)
	}

	ic.client = c
	log.Printf("Connected to %s for %s", imapServer, ic.account.Email)

	return nil
}

// GetUnreadCount returns the current unread count
func (ic *IMAPClient) GetUnreadCount() (uint32, error) {
	if ic.client == nil {
		return 0, fmt.Errorf("client not connected")
	}

	// Select INBOX
	mbox, err := ic.client.Select("INBOX", true)
	if err != nil {
		return 0, err
	}

	return mbox.Unseen, nil
}

// StartMonitoring starts monitoring for new emails using IDLE
func (ic *IMAPClient) StartMonitoring() error {
	if ic.client == nil {
		return fmt.Errorf("client not connected")
	}

	// Get initial unread count
	count, err := ic.GetUnreadCount()
	if err != nil {
		return err
	}

	// Notify initial count
	if ic.onUpdate != nil {
		ic.onUpdate(ic.account.Email, count)
	}

	// Create IDLE client
	idleClient := idle.NewClient(ic.client)
	idleClient.LogoutTimeout = 10 * time.Minute

	go func() {
		for {
			select {
			case <-ic.idleStop:
				return
			default:
				// Select INBOX
				_, err := ic.client.Select("INBOX", false)
				if err != nil {
					log.Printf("Error selecting INBOX for %s: %v", ic.account.Email, err)
					time.Sleep(30 * time.Second)
					continue
				}

				// Create updates channel
				updates := make(chan client.Update, 10)
				ic.client.Updates = updates

				// Create stop channel for IDLE
				stopIdle := make(chan struct{})

				// Start IDLE in goroutine
				done := make(chan error, 1)
				go func() {
					done <- idleClient.IdleWithFallback(stopIdle, 0)
				}()

				// Wait for updates or timeout
				timer := time.NewTimer(5 * time.Minute)
				shouldStop := false

				for !shouldStop {
					select {
					case <-updates:
						// Mailbox updated, get new count
						count, err := ic.GetUnreadCount()
						if err != nil {
							log.Printf("Error getting unread count for %s: %v", ic.account.Email, err)
						} else if ic.onUpdate != nil {
							ic.onUpdate(ic.account.Email, count)
						}
					case err := <-done:
						if err != nil {
							log.Printf("IDLE error for %s: %v", ic.account.Email, err)
						}
						shouldStop = true
					case <-timer.C:
						// Refresh IDLE every 5 minutes
						close(stopIdle)
						shouldStop = true
					case <-ic.idleStop:
						close(stopIdle)
						return
					}
				}

				timer.Stop()

				// Small delay before restarting IDLE
				time.Sleep(1 * time.Second)
			}
		}
	}()

	return nil
}

// Disconnect disconnects from the IMAP server
func (ic *IMAPClient) Disconnect() {
	close(ic.idleStop)
	if ic.client != nil {
		ic.client.Logout()
		ic.client = nil
	}
}

// Reconnect reconnects to the IMAP server
func (ic *IMAPClient) Reconnect() error {
	ic.Disconnect()
	time.Sleep(5 * time.Second)
	if err := ic.Connect(); err != nil {
		return err
	}
	return ic.StartMonitoring()
}
