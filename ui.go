package main

import (
	"fmt"
	"log"

	"github.com/getlantern/systray"
)

// TrayUI manages the system tray UI
type TrayUI struct {
	clients       []*IMAPClient
	state         *State
	titleItem     *systray.MenuItem
	accountItems  map[string]*systray.MenuItem
	quitItem      *systray.MenuItem
	refreshItem   *systray.MenuItem
}

// NewTrayUI creates a new TrayUI
func NewTrayUI() *TrayUI {
	return &TrayUI{
		clients:      []*IMAPClient{},
		state:        GetState(),
		accountItems: make(map[string]*systray.MenuItem),
	}
}

// onReady is called when the system tray is ready
func (ui *TrayUI) onReady() {
	// Set icon and title
	systray.SetIcon(getIcon())
	ui.updateTitle()

	// Add menu items
	ui.titleItem = systray.AddMenuItem("Gmail Notifier", "Gmail Notifier for Ubuntu")
	ui.titleItem.Disable()

	systray.AddSeparator()

	// Load config and setup accounts
	config, err := LoadConfig()
	if err != nil {
		log.Printf("Error loading config: %v", err)
		systray.AddMenuItem("Error loading config", "Check config file")
	} else {
		if len(config.Accounts) == 0 {
			noAccountsItem := systray.AddMenuItem("No accounts configured", "Add accounts to config")
			noAccountsItem.Disable()
		} else {
			// Create menu items for each account
			for _, account := range config.Accounts {
				item := systray.AddMenuItem(account.Email, fmt.Sprintf("Unread: 0"))
				item.Disable()
				ui.accountItems[account.Email] = item

				// Create IMAP client for this account
				client := NewIMAPClient(account, ui.onUnreadUpdate)
				ui.clients = append(ui.clients, client)

				// Connect and start monitoring
				go func(c *IMAPClient, email string) {
					if err := c.Connect(); err != nil {
						log.Printf("Error connecting to %s: %v", email, err)
						return
					}

					if err := c.StartMonitoring(); err != nil {
						log.Printf("Error monitoring %s: %v", email, err)
					}
				}(client, account.Email)
			}
		}
	}

	systray.AddSeparator()

	// Add refresh button
	ui.refreshItem = systray.AddMenuItem("Refresh", "Refresh all accounts")

	systray.AddSeparator()

	// Add quit button
	ui.quitItem = systray.AddMenuItem("Quit", "Quit the application")

	// Handle menu item clicks
	go ui.handleMenuClicks()
}

// onExit is called when the application is exiting
func (ui *TrayUI) onExit() {
	// Disconnect all clients
	for _, client := range ui.clients {
		client.Disconnect()
	}
}

// handleMenuClicks handles menu item clicks
func (ui *TrayUI) handleMenuClicks() {
	for {
		select {
		case <-ui.quitItem.ClickedCh:
			systray.Quit()
			return
		case <-ui.refreshItem.ClickedCh:
			ui.refreshAll()
		}
	}
}

// refreshAll refreshes all accounts
func (ui *TrayUI) refreshAll() {
	for _, client := range ui.clients {
		go func(c *IMAPClient) {
			count, err := c.GetUnreadCount()
			if err != nil {
				log.Printf("Error getting unread count: %v", err)
				return
			}
			ui.onUnreadUpdate(c.account.Email, count)
		}(client)
	}
}

// onUnreadUpdate is called when unread count is updated
func (ui *TrayUI) onUnreadUpdate(email string, count uint32) {
	// Update state
	ui.state.UpdateUnreadCount(email, count)

	// Update menu item
	if item, ok := ui.accountItems[email]; ok {
		item.SetTitle(fmt.Sprintf("%s: %d unread", email, count))
	}

	// Update tray title
	ui.updateTitle()
}

// updateTitle updates the tray title with total unread count
func (ui *TrayUI) updateTitle() {
	total := ui.state.GetTotalUnread()
	if total > 0 {
		systray.SetTitle(fmt.Sprintf("%d", total))
		systray.SetTooltip(fmt.Sprintf("Gmail Notifier - %d unread emails", total))
	} else {
		systray.SetTitle("")
		systray.SetTooltip("Gmail Notifier - No unread emails")
	}
}

// Run starts the system tray UI
func (ui *TrayUI) Run() {
	systray.Run(ui.onReady, ui.onExit)
}

// getIcon returns a simple icon for the system tray
func getIcon() []byte {
	// Simple envelope icon in PNG format (base64 decoded)
	// This is a minimal 16x16 PNG icon
	return []byte{
		0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
		0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x10,
		0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0xF3, 0xFF, 0x61, 0x00, 0x00, 0x00,
		0x4E, 0x49, 0x44, 0x41, 0x54, 0x38, 0x8D, 0x63, 0x60, 0x18, 0x05, 0xA3,
		0x60, 0x14, 0x8C, 0x82, 0x51, 0x30, 0x0A, 0x46, 0xC1, 0x28, 0x18, 0x05,
		0xA3, 0x60, 0x14, 0x8C, 0x82, 0x51, 0x30, 0x0A, 0x46, 0xC1, 0x28, 0x18,
		0x05, 0xA3, 0x60, 0x14, 0x8C, 0xC2, 0xFF, 0xFF, 0xFF, 0x0C, 0x03, 0x03,
		0x03, 0xE3, 0xFF, 0xFF, 0xFF, 0x19, 0x06, 0x06, 0x06, 0x46, 0x00, 0x00,
		0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
		0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x8B, 0x1A,
		0x04, 0x5D, 0x62, 0xB7, 0x3E, 0x97, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,
		0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
	}
}
