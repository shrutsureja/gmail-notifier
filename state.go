package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
)

// AccountState represents the state of a single account
type AccountState struct {
	Email       string `json:"email"`
	UnreadCount uint32 `json:"unread_count"`
}

// State represents the application state
type State struct {
	Accounts []AccountState `json:"accounts"`
	mu       sync.RWMutex
}

var globalState *State
var stateOnce sync.Once

// GetState returns the global state instance
func GetState() *State {
	stateOnce.Do(func() {
		globalState = &State{
			Accounts: []AccountState{},
		}
		// Try to load state from disk
		if err := globalState.Load(); err != nil {
			// If load fails, start with empty state
			globalState.Accounts = []AccountState{}
		}
	})
	return globalState
}

// GetUnreadCount returns the unread count for an account
func (s *State) GetUnreadCount(email string) uint32 {
	s.mu.RLock()
	defer s.mu.RUnlock()

	for _, acc := range s.Accounts {
		if acc.Email == email {
			return acc.UnreadCount
		}
	}
	return 0
}

// UpdateUnreadCount updates the unread count for an account
func (s *State) UpdateUnreadCount(email string, count uint32) {
	s.mu.Lock()
	defer s.mu.Unlock()

	found := false
	for i, acc := range s.Accounts {
		if acc.Email == email {
			s.Accounts[i].UnreadCount = count
			found = true
			break
		}
	}

	if !found {
		s.Accounts = append(s.Accounts, AccountState{
			Email:       email,
			UnreadCount: count,
		})
	}

	// Save state to disk
	go s.Save()
}

// GetTotalUnread returns the total unread count across all accounts
func (s *State) GetTotalUnread() uint32 {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var total uint32
	for _, acc := range s.Accounts {
		total += acc.UnreadCount
	}
	return total
}

// Save saves the state to disk
func (s *State) Save() error {
	s.mu.RLock()
	defer s.mu.RUnlock()

	homeDir, err := os.UserHomeDir()
	if err != nil {
		return err
	}

	stateDir := filepath.Join(homeDir, ".config", "gmail-notifier")
	statePath := filepath.Join(stateDir, "state.json")

	// Create state directory if it doesn't exist
	if err := os.MkdirAll(stateDir, 0755); err != nil {
		return err
	}

	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(statePath, data, 0644)
}

// Load loads the state from disk
func (s *State) Load() error {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return err
	}

	statePath := filepath.Join(homeDir, ".config", "gmail-notifier", "state.json")

	// If state file doesn't exist, return without error
	if _, err := os.Stat(statePath); os.IsNotExist(err) {
		return nil
	}

	data, err := os.ReadFile(statePath)
	if err != nil {
		return err
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	return json.Unmarshal(data, s)
}
