package main

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"io"
)

// encryptionKey is set at build time via -ldflags
var encryptionKey = "default-insecure-key-change-me-build-time"

// EncryptPassword encrypts a password using AES-GCM
func EncryptPassword(plaintext string) (string, error) {
	if plaintext == "" {
		return "", nil
	}

	// Derive a 32-byte key from the build-time key
	key := deriveKey(encryptionKey)

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

	// Derive a 32-byte key from the build-time key
	key := deriveKey(encryptionKey)

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

// deriveKey derives a 32-byte key from the build-time key
func deriveKey(key string) []byte {
	// Simple key derivation: pad or truncate to 32 bytes
	derived := make([]byte, 32)
	keyBytes := []byte(key)

	if len(keyBytes) >= 32 {
		copy(derived, keyBytes[:32])
	} else {
		copy(derived, keyBytes)
		// Fill remaining with a predictable pattern based on the key
		for i := len(keyBytes); i < 32; i++ {
			derived[i] = keyBytes[i%len(keyBytes)] ^ byte(i)
		}
	}

	return derived
}
