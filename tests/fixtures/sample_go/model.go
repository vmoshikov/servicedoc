package main

import "time"

// User представляет пользователя системы.
// Хранится в таблице users.
type User struct {
	ID        uint      `gorm:"primaryKey" json:"id"`
	Username  string    `gorm:"uniqueIndex;not null" json:"username"`
	Email     string    `gorm:"uniqueIndex;not null" json:"email"`
	Role      string    `gorm:"default:user" json:"role"`
	CreatedAt time.Time `json:"created_at"`
	DeletedAt *time.Time `gorm:"index" json:"deleted_at,omitempty"`
}

// Post представляет публикацию пользователя.
type Post struct {
	ID     uint   `gorm:"primaryKey" json:"id"`
	UserID uint   `gorm:"not null;foreignKey:UserID" json:"user_id"`
	Title  string `gorm:"not null" json:"title"`
	Body   string `json:"body"`
}
