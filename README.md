# Waste Management System

A simple command-line application for managing waste collection between waste creators, collectors, and recycling companies.

## Features

- User registration with roles (Waste Creator, Waste Collector, Recycling Company)
- Location-based collector matching
- Pickup request management
- Online/offline status tracking
- Distance calculation between creators and collectors

## Setup

1. Install Python 3.7 or higher
2. Install required packages:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
python waste_management.py
```

## Usage

1. **Register Users**:
   - Choose option 1 from the main menu
   - Enter name, phone number, and location (city, country)
   - Select a role (Waste Creator, Waste Collector, or Recycling Company)

2. **Toggle Online Status**:
   - Choose option 2
   - Select a user ID to toggle their online/offline status

3. **Create Pickup Request**:
   - Choose option 3
   - Enter the Waste Creator's ID
   - System will automatically find the nearest available collector

4. **View Users and Requests**:
   - Choose option 4 to view all registered users
   - Choose option 5 to view all pickup requests

5. **Complete Pickups**:
   - Choose option 6
   - Enter the request ID to mark it as completed

## Database

The system uses SQLite for data storage, creating a local file `waste_management.db` in the same directory.

## Notes

- Locations are geocoded using OpenStreetMap's Nominatim service
- Distances are calculated using the geodesic distance between coordinates
- All data is stored locally in the SQLite database 