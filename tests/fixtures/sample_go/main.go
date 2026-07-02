package main

import "fmt"

// GetUser возвращает пользователя по идентификатору.
// Возвращает ошибку если пользователь не найден.
func GetUser(id uint) (*User, error) {
	// stub
	return nil, fmt.Errorf("not implemented")
}

// CreateUser создаёт нового пользователя в базе данных.
func CreateUser(username, email, role string) (*User, error) {
	return &User{Username: username, Email: email, Role: role}, nil
}

// DeleteUser выполняет мягкое удаление пользователя (soft delete).
func DeleteUser(id uint) error {
	return nil
}

func main() {
	fmt.Println("sample-service started")
}
