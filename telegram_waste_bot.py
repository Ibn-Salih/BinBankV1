import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import sqlite3
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import os

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for conversation handler
CHOOSING_ROLE, ENTER_NAME, ENTER_PHONE, ENTER_LOCATION = range(4)

# Database setup
def setup_database():
    # Remove existing database if it exists
    if os.path.exists('waste_management.db'):
        os.remove('waste_management.db')
    
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            location_text TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            role TEXT NOT NULL,
            is_online INTEGER DEFAULT 1
        )
    ''')
    
    # Create pickup requests table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pickup_requests (
            id INTEGER PRIMARY KEY,
            creator_id INTEGER,
            collector_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES users (telegram_id),
            FOREIGN KEY (collector_id) REFERENCES users (telegram_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Database setup completed successfully!")

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    # Check if user exists
    cursor.execute('SELECT role FROM users WHERE telegram_id = ?', (user_id,))
    existing_user = cursor.fetchone()
    conn.close()
    
    if existing_user:
        await update.message.reply_text(
            f"Welcome back! You are registered as a {existing_user[0]}.\n"
            "Available commands:\n"
            "/status - Toggle your online status\n"
            "/request - Create a pickup request (for Waste Creators)\n"
            "/complete - Complete a pickup (for Waste Collectors)"
        )
        return ConversationHandler.END
    
    reply_keyboard = [
        ['Waste Creator'],
        ['Waste Collector'],
        ['Recycling Company']
    ]
    
    await update.message.reply_text(
        "Welcome to the Waste Management Bot! 🌱\n"
        "Please choose your role:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    )
    
    return CHOOSING_ROLE

async def role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['role'] = update.message.text
    
    await update.message.reply_text(
        "Please enter your full name:",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ENTER_NAME

async def name_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['full_name'] = update.message.text
    
    await update.message.reply_text("Please enter your phone number:")
    return ENTER_PHONE

async def phone_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    
    await update.message.reply_text(
        "Please send your location (city, country):"
    )
    return ENTER_LOCATION

async def location_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location_text = update.message.text
    geolocator = Nominatim(user_agent="waste_management_bot")
    
    try:
        location = geolocator.geocode(location_text)
        if location:
            conn = sqlite3.connect('waste_management.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO users (telegram_id, full_name, phone_number, location_text, latitude, longitude, role)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                update.message.from_user.id,
                context.user_data['full_name'],
                context.user_data['phone'],
                location_text,
                location.latitude,
                location.longitude,
                context.user_data['role']
            ))
            
            conn.commit()
            conn.close()
            
            await update.message.reply_text(
                f"Registration complete! You are now registered as a {context.user_data['role']}.\n"
                "Available commands:\n"
                "/status - Toggle your online status\n"
                "/request - Create a pickup request (for Waste Creators)\n"
                "/complete - Complete a pickup (for Waste Collectors)"
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                "Could not find your location. Please try again with a valid city and country:"
            )
            return ENTER_LOCATION
    except Exception as e:
        await update.message.reply_text(
            "Error processing location. Please try again with a valid city and country:"
        )
        return ENTER_LOCATION

async def toggle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT is_online FROM users WHERE telegram_id = ?', (user_id,))
    current_status = cursor.fetchone()
    
    if current_status:
        new_status = 0 if current_status[0] else 1
        cursor.execute('UPDATE users SET is_online = ? WHERE telegram_id = ?', (new_status, user_id))
        conn.commit()
        status_text = "online" if new_status else "offline"
        await update.message.reply_text(f"Your status has been set to {status_text}")
    else:
        await update.message.reply_text("You need to register first. Use /start to register.")
    
    conn.close()

async def create_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    # Check if user is a waste creator
    cursor.execute('SELECT role FROM users WHERE telegram_id = ?', (user_id,))
    user_role = cursor.fetchone()
    
    if not user_role or user_role[0] != 'Waste Creator':
        await update.message.reply_text("Only Waste Creators can create pickup requests.")
        conn.close()
        return
    
    # Create pickup request
    cursor.execute('INSERT INTO pickup_requests (creator_id) VALUES (?)', (user_id,))
    request_id = cursor.lastrowid
    
    # Find available collector
    cursor.execute('''
        SELECT telegram_id, latitude, longitude
        FROM users
        WHERE role = 'Waste Collector'
        AND is_online = 1
    ''')
    collectors = cursor.fetchall()
    
    # Get creator's location
    cursor.execute('SELECT latitude, longitude FROM users WHERE telegram_id = ?', (user_id,))
    creator_location = cursor.fetchone()
    
    if collectors and creator_location:
        # Find nearest collector
        nearest_collector = min(
            collectors,
            key=lambda x: geodesic(
                (creator_location[0], creator_location[1]),
                (x[1], x[2])
            ).kilometers if all([x[1], x[2]]) else float('inf')
        )
        
        # Assign collector
        cursor.execute('''
            UPDATE pickup_requests
            SET collector_id = ?, status = 'assigned'
            WHERE id = ?
        ''', (nearest_collector[0], request_id))
        
        # Notify creator
        await update.message.reply_text(
            f"Pickup request created (ID: {request_id})!\n"
            "A collector has been assigned and will pick up your waste within 5 hours."
        )
        
        # Try to notify collector (they need to have started the bot)
        try:
            await context.bot.send_message(
                chat_id=nearest_collector[0],
                text=f"New pickup request (ID: {request_id}) has been assigned to you.\n"
                     "Please complete the pickup within 5 hours."
            )
        except Exception as e:
            logger.error(f"Could not notify collector: {e}")
    else:
        cursor.execute('''
            UPDATE pickup_requests
            SET status = 'pending'
            WHERE id = ?
        ''', (request_id,))
        await update.message.reply_text(
            "No waste collectors are currently available.\n"
            "Your request has been saved and you will be notified when a collector becomes available."
        )
    
    conn.commit()
    conn.close()

async def complete_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    # Check if user is a waste collector
    cursor.execute('SELECT role FROM users WHERE telegram_id = ?', (user_id,))
    user_role = cursor.fetchone()
    
    if not user_role or user_role[0] != 'Waste Collector':
        await update.message.reply_text("Only Waste Collectors can complete pickups.")
        conn.close()
        return
    
    # Get active pickups for this collector
    cursor.execute('''
        SELECT id, creator_id
        FROM pickup_requests
        WHERE collector_id = ? AND status = 'assigned'
    ''', (user_id,))
    pickups = cursor.fetchall()
    
    if not pickups:
        await update.message.reply_text("You have no active pickup requests.")
        conn.close()
        return
    
    # Complete the oldest pickup
    pickup = pickups[0]
    cursor.execute('''
        UPDATE pickup_requests
        SET status = 'completed', completed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (pickup[0],))
    
    # Notify creator
    try:
        await context.bot.send_message(
            chat_id=pickup[1],
            text=f"Your pickup request (ID: {pickup[0]}) has been completed!"
        )
    except Exception as e:
        logger.error(f"Could not notify creator: {e}")
    
    await update.message.reply_text(f"Pickup request (ID: {pickup[0]}) marked as completed!")
    
    conn.commit()
    conn.close()

def main():
    # Setup database
    setup_database()
    
    # Initialize bot
    application = Application.builder().token("7809765952:AAF9jN7-r81CMqo2w4rpSqHZFkQGc2gAoTE").build()
    
    # Add conversation handler for registration
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, role_chosen)],
            ENTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_entered)],
            ENTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_entered)],
            ENTER_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, location_entered)],
        },
        fallbacks=[],
    )
    
    application.add_handler(conv_handler)
    
    # Add other command handlers
    application.add_handler(CommandHandler("status", toggle_status))
    application.add_handler(CommandHandler("request", create_request))
    application.add_handler(CommandHandler("complete", complete_pickup))
    
    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 