package main

import (
	"testing"
)

func TestEncryptDecrypt(t *testing.T) {
	tests := []struct {
		name     string
		password string
	}{
		{"simple password", "mypassword123"},
		{"app password format", "abcd efgh ijkl mnop"},
		{"empty string", ""},
		{"special chars", "p@ssw0rd!#$%"},
		{"long password", "this-is-a-very-long-password-with-many-characters-1234567890"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Encrypt
			encrypted, err := EncryptPassword(tt.password)
			if err != nil {
				t.Fatalf("EncryptPassword failed: %v", err)
			}

			// Empty passwords should return empty
			if tt.password == "" {
				if encrypted != "" {
					t.Errorf("expected empty encrypted string for empty password, got %q", encrypted)
				}
				return
			}

			// Encrypted should be different from original
			if encrypted == tt.password {
				t.Errorf("encrypted password should be different from original")
			}

			// Decrypt
			decrypted, err := DecryptPassword(encrypted)
			if err != nil {
				t.Fatalf("DecryptPassword failed: %v", err)
			}

			// Decrypted should match original
			if decrypted != tt.password {
				t.Errorf("decrypted password doesn't match original: got %q, want %q", decrypted, tt.password)
			}
		})
	}
}

func TestDecryptPlaintextBackwardCompatibility(t *testing.T) {
	// Test that plaintext passwords are returned as-is for backward compatibility
	plaintext := "plain-text-password"
	
	decrypted, err := DecryptPassword(plaintext)
	if err != nil {
		t.Fatalf("DecryptPassword failed on plaintext: %v", err)
	}
	
	if decrypted != plaintext {
		t.Errorf("plaintext password should be returned as-is, got %q, want %q", decrypted, plaintext)
	}
}

func TestEncryptionDifferentEachTime(t *testing.T) {
	password := "test-password"
	
	encrypted1, err := EncryptPassword(password)
	if err != nil {
		t.Fatalf("EncryptPassword failed: %v", err)
	}
	
	encrypted2, err := EncryptPassword(password)
	if err != nil {
		t.Fatalf("EncryptPassword failed: %v", err)
	}
	
	// Due to random nonce, each encryption should be different
	if encrypted1 == encrypted2 {
		t.Errorf("expected different encrypted values for same password (due to random nonce)")
	}
	
	// But both should decrypt to the same value
	decrypted1, err := DecryptPassword(encrypted1)
	if err != nil {
		t.Fatalf("DecryptPassword failed: %v", err)
	}
	
	decrypted2, err := DecryptPassword(encrypted2)
	if err != nil {
		t.Fatalf("DecryptPassword failed: %v", err)
	}
	
	if decrypted1 != password || decrypted2 != password {
		t.Errorf("both encryptions should decrypt to original password")
	}
}
