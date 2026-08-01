package main

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// Account represents a Gmail account configuration
type Account struct {
	Email    string `json:"email"`
	Password string `json:"password"` // App Password
}

// Config represents the application configuration
type Config struct {
	Accounts []Account `json:"accounts"`
}

// LoadConfig loads configuration from the config file
func LoadConfig() (*Config, error) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return nil, err
	}

	configDir := filepath.Join(homeDir, ".config", "gmail-notifier")
	configPath := filepath.Join(configDir, "config.json")

	// Create config directory if it doesn't exist
	if err := os.MkdirAll(configDir, 0700); err != nil {
		return nil, err
	}

	// If config file doesn't exist, create a default one
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		defaultConfig := &Config{
			Accounts: []Account{},
		}
		if err := SaveConfig(defaultConfig); err != nil {
			return nil, err
		}
		return defaultConfig, nil
	}

	// Read config file
	data, err := os.ReadFile(configPath)
	if err != nil {
		return nil, err
	}

	var config Config
	if err := json.Unmarshal(data, &config); err != nil {
		return nil, err
	}

	// Decrypt passwords
	for i := range config.Accounts {
		decrypted, err := DecryptPassword(config.Accounts[i].Password)
		if err != nil {
			return nil, err
		}
		config.Accounts[i].Password = decrypted
	}

	return &config, nil
}

// SaveConfig saves the configuration to the config file
func SaveConfig(config *Config) error {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return err
	}

	configDir := filepath.Join(homeDir, ".config", "gmail-notifier")
	configPath := filepath.Join(configDir, "config.json")

	// Create config directory if it doesn't exist
	if err := os.MkdirAll(configDir, 0700); err != nil {
		return err
	}

	// Create a copy of config with encrypted passwords
	configCopy := &Config{
		Accounts: make([]Account, len(config.Accounts)),
	}

	for i, account := range config.Accounts {
		encrypted, err := EncryptPassword(account.Password)
		if err != nil {
			return err
		}
		configCopy.Accounts[i] = Account{
			Email:    account.Email,
			Password: encrypted,
		}
	}

	data, err := json.MarshalIndent(configCopy, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(configPath, data, 0600)
}
