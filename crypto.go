package main

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"io"
	"os"
	"path/filepath"
)

// getEncryptionKey retrieves or creates the encryption key
func getEncryptionKey() ([]byte, error) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return nil, err
	}

	keyDir := filepath.Join(homeDir, ".config", "gmail-notifier")
	keyPath := filepath.Join(keyDir, ".encryption_key")

	// Create key directory if it doesn't exist
	if err := os.MkdirAll(keyDir, 0700); err != nil {
		return nil, err
	}

	// Try to read existing key
	if keyData, err := os.ReadFile(keyPath); err == nil {
		// Decode the base64-encoded key
		key, err := base64.StdEncoding.DecodeString(string(keyData))
		if err == nil && len(key) == 32 {
			return key, nil
		}
		// If key is invalid, generate a new one
	}

	// Generate a new 32-byte encryption key
	key := make([]byte, 32)
	if _, err := io.ReadFull(rand.Reader, key); err != nil {
		return nil, err
	}

	// Save the key (base64 encoded for readability)
	keyData := base64.StdEncoding.EncodeToString(key)
	if err := os.WriteFile(keyPath, []byte(keyData), 0600); err != nil {
		return nil, err
	}

	return key, nil
}

// EncryptPassword encrypts a password using AES-GCM
func EncryptPassword(plaintext string) (string, error) {
	if plaintext == "" {
		return "", nil
	}

	// Get the encryption key (persistent, user-specific)
	key, err := getEncryptionKey()
	if err != nil {
		return "", err
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		return "", err
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}

	ciphertext := gcm.Seal(nonce, nonce, []byte(plaintext), nil)
	return base64.StdEncoding.EncodeToString(ciphertext), nil
}

// DecryptPassword decrypts a password using AES-GCM
func DecryptPassword(ciphertext string) (string, error) {
	if ciphertext == "" {
		return "", nil
	}

	// Get the encryption key (persistent, user-specific)
	key, err := getEncryptionKey()
	if err != nil {
		return "", err
	}

	data, err := base64.StdEncoding.DecodeString(ciphertext)
	if err != nil {
		// If it's not base64, assume it's plaintext (for backward compatibility)
		return ciphertext, nil
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		return "", err
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}

	nonceSize := gcm.NonceSize()
	if len(data) < nonceSize {
		return "", errors.New("ciphertext too short")
	}

	nonce, cipherData := data[:nonceSize], data[nonceSize:]
	plaintext, err := gcm.Open(nil, nonce, cipherData, nil)
	if err != nil {
		// If decryption fails, assume it's plaintext (for backward compatibility)
		return ciphertext, nil
	}

	return string(plaintext), nil
}
