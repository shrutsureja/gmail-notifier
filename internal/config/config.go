package config

import (
	"encoding/json"
	"log"
	"os"
	"path/filepath"
	"sync"
)

type Account struct {
	IMAPServer  string `json:"imap_server"`
	IMAPPort    int    `json:"imap_port"`
	Email       string `json:"email"`
	AppPassword string `json:"app_password"`
}

type Config struct {
	Accounts []Account `json:"accounts"`
}

var (
	cfg  *Config
	once sync.Once
)

// GetConfig return the config,
func GetConfig() (*Config, error) {
	var err error
	once.Do(func() {
		cfg, err = loadConfig()
	})
	return cfg, err
}

func loadConfig() (*Config, error) {
	configPath, err := getConfigPath()
	if err != nil {
		return nil, err
	}

	// Creating config dir if it does not exist's
	if err := os.MkdirAll(filepath.Dir(configPath), 0755); err != nil {
		return nil, err
	}

	// Creating default config file if does not exists
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		log.Printf("Creating default config file at :%s", configPath)
		defaultConfig := &Config{Accounts: []Account{}}
		if err := SaveConfig(defaultConfig); err != nil {
			return nil, err
		}
		return defaultConfig, nil
	}
	log.Printf("Loading config from :%s", configPath)

	data, err := os.ReadFile(configPath)
	if err != nil {
		return nil, err
	}

	var cfg Config
	err = json.Unmarshal(data, &cfg)
	if err != nil {
		return nil, err
	}

	log.Printf("Loaded config and number of accounts are: %d", len(cfg.Accounts))
	return &cfg, nil
}

func SaveConfig(updatedCfg *Config) error {
	if updatedCfg == nil {
		return nil
	}

	homeDir, err := os.UserHomeDir()
	if err != nil {
		return err
	}

	configDir := filepath.Join(homeDir, ".config", "gmail-notifier")
	configPath := filepath.Join(configDir, "config.json")

	// Creating dir if it does not exist's
	if err := os.MkdirAll(configDir, 0755); err != nil {
		return err
	}

	data, err := json.MarshalIndent(updatedCfg, "", "  ")
	if err != nil {
		return err
	}
	cfg = updatedCfg
	return os.WriteFile(configPath, data, 0644)
}

func getConfigPath() (string, error) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(homeDir, ".config", "gmail-notifier", "config.json"), nil
}
