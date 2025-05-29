import sqlite3
import datetime
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from tabulate import tabulate
import time

class WasteManagementSystem:
    def __init__(self):
        self.conn = sqlite3.connect('waste_management.db')
        self.cursor = self.conn.cursor()
        self.setup_database()
        self.geolocator = Nominatim(user_agent="waste_management_test")

    def setup_database(self):
        # Create users table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                phone_number TEXT NOT NULL,
                location_text TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                role TEXT NOT NULL,
                is_online INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create pickup requests table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS pickup_requests (
                id INTEGER PRIMARY KEY,
                creator_id INTEGER,
                collector_id INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (creator_id) REFERENCES users (id),
                FOREIGN KEY (collector_id) REFERENCES users (id)
            )
        ''')
        self.conn.commit()

    def register_user(self, full_name, phone_number, location, role):
        try:
            # Try to geocode the location
            location_data = self.geolocator.geocode(location)
            lat = location_data.latitude if location_data else None
            lon = location_data.longitude if location_data else None
            
            self.cursor.execute('''
                INSERT INTO users (full_name, phone_number, location_text, latitude, longitude, role)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (full_name, phone_number, location, lat, lon, role))
            self.conn.commit()
            return self.cursor.lastrowid
        except Exception as e:
            print(f"Error registering user: {e}")
            return None

    def set_user_status(self, user_id, is_online):
        self.cursor.execute('UPDATE users SET is_online = ? WHERE id = ?', (1 if is_online else 0, user_id))
        self.conn.commit()

    def create_pickup_request(self, creator_id):
        # First verify the user is a waste creator
        self.cursor.execute('SELECT role FROM users WHERE id = ?', (creator_id,))
        role = self.cursor.fetchone()
        if not role or role[0] != 'Waste Creator':
            return None, "Only waste creators can create pickup requests"

        # Create the pickup request
        self.cursor.execute('''
            INSERT INTO pickup_requests (creator_id, status)
            VALUES (?, 'pending')
        ''', (creator_id,))
        self.conn.commit()
        return self.cursor.lastrowid, "Pickup request created successfully"

    def find_available_collector(self, creator_id):
        # Get creator's location
        self.cursor.execute('''
            SELECT latitude, longitude
            FROM users
            WHERE id = ?
        ''', (creator_id,))
        creator_location = self.cursor.fetchone()

        if not creator_location or not all(creator_location):
            return None, "Creator location not found or invalid"

        # Find online collectors
        self.cursor.execute('''
            SELECT id, latitude, longitude
            FROM users
            WHERE role = 'Waste Collector'
            AND is_online = 1
        ''')
        collectors = self.cursor.fetchall()

        closest_collector = None
        min_distance = float('inf')

        for collector in collectors:
            if not all([collector[1], collector[2]]):  # Skip if location is invalid
                continue
            
            distance = geodesic(
                (creator_location[0], creator_location[1]),
                (collector[1], collector[2])
            ).kilometers

            if distance < min_distance:
                min_distance = distance
                closest_collector = collector[0]

        return closest_collector, min_distance if closest_collector else None

    def assign_collector_to_request(self, request_id, collector_id):
        self.cursor.execute('''
            UPDATE pickup_requests
            SET collector_id = ?, status = 'assigned'
            WHERE id = ?
        ''', (collector_id, request_id))
        self.conn.commit()

    def complete_pickup(self, request_id):
        self.cursor.execute('''
            UPDATE pickup_requests
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (request_id,))
        self.conn.commit()

    def get_user_details(self, user_id):
        self.cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        return self.cursor.fetchone()

    def list_users(self):
        self.cursor.execute('SELECT id, full_name, role, is_online FROM users')
        users = self.cursor.fetchall()
        headers = ['ID', 'Name', 'Role', 'Online Status']
        print("\nRegistered Users:")
        print(tabulate(users, headers=headers, tablefmt='grid'))

    def list_pickup_requests(self):
        self.cursor.execute('''
            SELECT 
                pr.id,
                u1.full_name as creator_name,
                u2.full_name as collector_name,
                pr.status,
                pr.created_at
            FROM pickup_requests pr
            JOIN users u1 ON pr.creator_id = u1.id
            LEFT JOIN users u2 ON pr.collector_id = u2.id
        ''')
        requests = self.cursor.fetchall()
        headers = ['ID', 'Creator', 'Collector', 'Status', 'Created At']
        print("\nPickup Requests:")
        print(tabulate(requests, headers=headers, tablefmt='grid'))

    def close(self):
        self.conn.close()

def main_menu():
    system = WasteManagementSystem()
    
    while True:
        print("\n=== Waste Management System ===")
        print("1. Register New User")
        print("2. Toggle User Online Status")
        print("3. Create Pickup Request")
        print("4. List Users")
        print("5. List Pickup Requests")
        print("6. Complete Pickup")
        print("7. Exit")
        
        choice = input("\nEnter your choice (1-7): ")
        
        if choice == '1':
            full_name = input("Enter full name: ")
            phone_number = input("Enter phone number: ")
            location = input("Enter location (city, country): ")
            print("\nAvailable roles:")
            print("1. Waste Creator")
            print("2. Waste Collector")
            print("3. Recycling Company")
            role_choice = input("Choose role (1-3): ")
            
            roles = {
                '1': 'Waste Creator',
                '2': 'Waste Collector',
                '3': 'Recycling Company'
            }
            
            if role_choice in roles:
                user_id = system.register_user(full_name, phone_number, location, roles[role_choice])
                if user_id:
                    print(f"\nUser registered successfully! ID: {user_id}")
            else:
                print("Invalid role choice!")

        elif choice == '2':
            system.list_users()
            user_id = input("Enter user ID to toggle status: ")
            try:
                current_status = system.get_user_details(int(user_id))[7]
                system.set_user_status(int(user_id), not current_status)
                print("Status updated successfully!")
            except:
                print("Invalid user ID!")

        elif choice == '3':
            system.list_users()
            creator_id = input("Enter waste creator ID: ")
            try:
                request_id, message = system.create_pickup_request(int(creator_id))
                if request_id:
                    print(f"Pickup request created! ID: {request_id}")
                    collector_id, distance = system.find_available_collector(int(creator_id))
                    if collector_id:
                        system.assign_collector_to_request(request_id, collector_id)
                        print(f"Found collector (ID: {collector_id}) {distance:.2f}km away!")
                    else:
                        print("No available collectors found!")
                else:
                    print(message)
            except:
                print("Invalid input!")

        elif choice == '4':
            system.list_users()

        elif choice == '5':
            system.list_pickup_requests()

        elif choice == '6':
            system.list_pickup_requests()
            request_id = input("Enter request ID to mark as completed: ")
            try:
                system.complete_pickup(int(request_id))
                print("Pickup marked as completed!")
            except:
                print("Invalid request ID!")

        elif choice == '7':
            system.close()
            print("Goodbye!")
            break

        else:
            print("Invalid choice! Please try again.")

if __name__ == "__main__":
    main_menu() 