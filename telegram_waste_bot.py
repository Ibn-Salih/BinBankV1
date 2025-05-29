import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import sqlite3
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import os
import random
import string

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for conversation handler
CHOOSING_ROLE, ENTER_NAME, ENTER_PHONE, ENTER_LOCATION, ENTER_VERIFICATION_CODE, ENTER_WEIGHT, ENTER_RECYCLING_VERIFICATION, ENTER_RECYCLER_NAME = range(8)

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
    
    # Create recycling transactions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recycling_transactions (
            id INTEGER PRIMARY KEY,
            collector_id INTEGER,
            recycler_id INTEGER,
            weight_kg REAL,
            amount_paid REAL,
            verification_code TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (collector_id) REFERENCES users (telegram_id),
            FOREIGN KEY (recycler_id) REFERENCES users (telegram_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Database setup completed successfully!")

def generate_verification_code():
    return ''.join(random.choices(string.digits, k=4))

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
            "/complete - Complete a pickup (for Waste Collectors)\n"
            "/recycle - Initiate recycling (for Waste Collectors)"
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
            
            # Create role-specific command list
            commands = ["/status - Toggle your online status"]
            
            if context.user_data['role'] == 'Waste Creator':
                commands.append("/request - Create a pickup request")
            elif context.user_data['role'] == 'Waste Collector':
                commands.append("/complete - Complete a pickup")
                commands.append("/recycle - Initiate recycling")
            elif context.user_data['role'] == 'Recycling Company':
                commands.append("/weight - Record waste weight")
                commands.append("/verify_recycling - Verify recycling transaction")
            
            await update.message.reply_text(
                f"Registration complete! You are now registered as a {context.user_data['role']}.\n\n"
                "Available commands:\n" + "\n".join(commands)
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
            f"A collector has been assigned and will pick up your waste within 5 hours.\n"
            f"You will receive a verification code when the collector arrives."
        )
        
        # Try to notify collector
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
    logger.info("=== Complete Pickup Process Started ===")
    logger.info(f"Collector ID: {user_id}")
    
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    # Check if user is a waste collector
    cursor.execute('SELECT role FROM users WHERE telegram_id = ?', (user_id,))
    user_role = cursor.fetchone()
    
    if not user_role or user_role[0] != 'Waste Collector':
        logger.error(f"User {user_id} is not a waste collector")
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
        logger.error(f"No active pickups found for collector {user_id}")
        await update.message.reply_text("You have no active pickup requests.")
        conn.close()
        return
    
    # Generate verification code
    verification_code = generate_verification_code()
    logger.info(f"Generated verification code: {verification_code}")
    
    # Store pickup info and verification code in context
    context.user_data['current_pickup'] = pickups[0]
    context.user_data['verification_code'] = verification_code
    logger.info(f"Stored in context - Pickup info: {pickups[0]}, Verification code: {verification_code}")
    logger.info(f"Full context data after storage: {context.user_data}")
    
    # Notify creator with verification code
    try:
        await context.bot.send_message(
            chat_id=pickups[0][1],  # creator_id
            text=f"Your waste collector has arrived!\nPlease provide them with this verification code: {verification_code}"
        )
        logger.info(f"Sent verification code {verification_code} to creator {pickups[0][1]}")
    except Exception as e:
        logger.error(f"Could not send verification code to creator: {e}")
        await update.message.reply_text("Error: Could not notify waste creator. Please try again.")
        conn.close()
        return
    
    await update.message.reply_text(
        "Please ask the waste creator for the verification code and enter it here:"
    )
    logger.info("=== Complete Pickup Process Completed - Waiting for Verification ===")
    return ENTER_VERIFICATION_CODE

async def verify_pickup_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    provided_code = update.message.text.strip()
    pickup_info = context.user_data.get('current_pickup')
    stored_code = context.user_data.get('verification_code')
    
    logger.info("=== Pickup Verification Process Started ===")
    logger.info(f"User ID: {update.message.from_user.id}")
    logger.info(f"Provided code: '{provided_code}' (length: {len(provided_code)})")
    logger.info(f"Stored code: '{stored_code}' (length: {len(stored_code) if stored_code else 0})")
    logger.info(f"Current pickup info: {pickup_info}")
    logger.info(f"Full context user data: {context.user_data}")
    
    if not pickup_info or not stored_code:
        logger.error("=== Verification Failed ===")
        logger.error(f"Missing data - Pickup info: {pickup_info}, Stored code: {stored_code}")
        await update.message.reply_text("No active pickup found. Please use /complete again.")
        return ConversationHandler.END
    
    if provided_code == stored_code:
        logger.info("=== Verification Successful ===")
        conn = sqlite3.connect('waste_management.db')
        cursor = conn.cursor()
        
        # Update pickup status
        cursor.execute('''
            UPDATE pickup_requests
            SET status = 'completed'
            WHERE id = ?
        ''', (pickup_info[0],))
        logger.info(f"Updated pickup request {pickup_info[0]} status to 'completed'")
        
        # Notify both creator and collector
        completion_message = f"✅ Pickup Complete!\nRequest ID: {pickup_info[0]}\nStatus: Successfully completed"
        
        try:
            # Notify creator
            logger.info(f"Attempting to notify creator with ID: {pickup_info[1]}")
            await context.bot.send_message(
                chat_id=pickup_info[1],  # creator_id
                text=completion_message
            )
            logger.info("Successfully notified creator")
            
            # Notify collector
            logger.info(f"Attempting to notify collector with ID: {update.message.from_user.id}")
            await context.bot.send_message(
                chat_id=update.message.from_user.id,
                text=completion_message
            )
            logger.info("Successfully notified collector")
            
            await update.message.reply_text("Pickup request marked as completed!")
        except Exception as e:
            logger.error(f"Error sending notifications: {str(e)}")
            await update.message.reply_text("Pickup completed but there was an error sending notifications.")
        
        conn.commit()
        conn.close()
        logger.info("=== Pickup Verification Process Completed Successfully ===")
    else:
        logger.error("=== Verification Failed ===")
        logger.error(f"Code mismatch - Provided: '{provided_code}', Expected: '{stored_code}'")
        await update.message.reply_text("Invalid verification code. Please try again.")
    
    return ConversationHandler.END

async def record_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    # Check if user is a recycling company
    cursor.execute('SELECT role FROM users WHERE telegram_id = ?', (user_id,))
    user_role = cursor.fetchone()
    
    if not user_role or user_role[0] != 'Recycling Company':
        await update.message.reply_text("Only Recycling Companies can record weights.")
        conn.close()
        return
    
    await update.message.reply_text("Please enter the weight of the plastic in kilograms:")
    return ENTER_WEIGHT

async def process_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        weight = float(update.message.text.strip())
        if weight <= 0:
            await update.message.reply_text("Please enter a valid weight greater than 0.")
            return ENTER_WEIGHT
        
        user_id = update.message.from_user.id
        
        conn = sqlite3.connect('waste_management.db')
        cursor = conn.cursor()
        
        # Find the collector who initiated the recycling
        cursor.execute('''
            SELECT u.telegram_id, u.full_name
            FROM users u
            WHERE u.role = 'Waste Collector'
            AND u.telegram_id IN (
                SELECT collector_id 
                FROM recycling_transactions 
                WHERE recycler_id = ? 
                AND status = 'pending'
                ORDER BY created_at DESC 
                LIMIT 1
            )
        ''', (user_id,))
        
        collector = cursor.fetchone()
        
        if not collector:
            await update.message.reply_text("No pending recycling transaction found. Please wait for a waste collector to initiate recycling.")
            conn.close()
            return ConversationHandler.END
        
        # Calculate payment (1kg = $1)
        amount = weight * 1.0
        
        # Generate verification code
        verification_code = generate_verification_code()
        
        # Create recycling transaction
        cursor.execute('''
            INSERT INTO recycling_transactions 
            (collector_id, recycler_id, weight_kg, amount_paid, verification_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (collector[0], user_id, weight, amount, verification_code))
        
        transaction_id = cursor.lastrowid
        
        # Store transaction info and verification code in context
        context.user_data['current_transaction'] = (transaction_id, collector[0], verification_code)
        logger.info(f"Stored in context - Transaction info: {context.user_data['current_transaction']}")
        
        # Notify collector with verification code
        try:
            logger.info(f"Attempting to notify collector with ID: {collector[0]}")
            await context.bot.send_message(
                chat_id=collector[0],
                text=f"Your recycling company has recorded the weight!\n"
                     f"Please provide them with this verification code: {verification_code}"
            )
            logger.info("Successfully notified collector")
        except Exception as e:
            logger.error(f"Could not notify collector: {e}")
        
        await update.message.reply_text(
            f"Transaction recorded!\n"
            f"Please ask the waste collector for the verification code and use /verify_recycling to complete the transaction."
        )
        
        conn.commit()
        conn.close()
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return ENTER_WEIGHT

async def verify_recycling(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    # Check if user is a recycling company
    cursor.execute('SELECT role FROM users WHERE telegram_id = ?', (user_id,))
    user_role = cursor.fetchone()
    
    if not user_role or user_role[0] != 'Recycling Company':
        await update.message.reply_text("Only Recycling Companies can verify recycling transactions.")
        conn.close()
        return
    
    # Get pending transactions
    cursor.execute('''
        SELECT id, collector_id, verification_code
        FROM recycling_transactions
        WHERE recycler_id = ? AND status = 'pending'
        ORDER BY created_at DESC
        LIMIT 1
    ''', (user_id,))
    transaction = cursor.fetchone()
    
    if not transaction:
        await update.message.reply_text("You have no pending recycling transactions.")
        conn.close()
        return
    
    # Store transaction info in context
    context.user_data['current_transaction'] = transaction
    logger.info(f"Stored transaction info in context: {transaction}")
    
    await update.message.reply_text(
        "Please enter the 4-digit verification code provided by the waste collector:"
    )
    return ENTER_RECYCLING_VERIFICATION

async def recycle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    logger.info("=== Recycling Process Started ===")
    logger.info(f"Collector ID: {user_id}")
    
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    # Check if user is a waste collector
    cursor.execute('SELECT role FROM users WHERE telegram_id = ?', (user_id,))
    user_role = cursor.fetchone()
    
    if not user_role or user_role[0] != 'Waste Collector':
        logger.error(f"User {user_id} is not a waste collector")
        await update.message.reply_text("Only Waste Collectors can initiate recycling.")
        conn.close()
        return
    
    # Store collector info in context
    context.user_data['collector_id'] = user_id
    
    await update.message.reply_text("Please enter the recycling company's full name:")
    return ENTER_RECYCLER_NAME

async def process_recycler_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    recycler_name = update.message.text.strip()
    collector_id = context.user_data.get('collector_id')
    
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    # Find recycler by name
    cursor.execute('''
        SELECT telegram_id, full_name
        FROM users
        WHERE role = 'Recycling Company'
        AND full_name LIKE ?
    ''', (f'%{recycler_name}%',))
    
    recycler = cursor.fetchone()
    
    if not recycler:
        await update.message.reply_text("No recycling company found with that name. Please try again:")
        return ENTER_RECYCLER_NAME
    
    # Generate verification code
    verification_code = generate_verification_code()
    logger.info(f"Generated verification code: {verification_code}")
    
    # Store recycler info and verification code in context
    context.user_data['current_recycling'] = (recycler[0], verification_code)
    logger.info(f"Stored in context - Recycler info: {recycler[0]}, Verification code: {verification_code}")
    
    # Notify recycler with verification code
    try:
        logger.info(f"Attempting to notify recycler with ID: {recycler[0]}")
        await context.bot.send_message(
            chat_id=recycler[0],
            text=f"A waste collector has arrived with waste for recycling!\n"
                 f"Please provide them with this verification code: {verification_code}"
        )
        logger.info("Successfully notified recycler")
    except Exception as e:
        logger.error(f"Could not notify recycler: {e}")
        await update.message.reply_text("Error: Could not notify recycling company. Please try again.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "Please ask the recycling company for the verification code and enter it here:"
    )
    logger.info("=== Recycling Process Completed - Waiting for Verification ===")
    return ENTER_RECYCLING_VERIFICATION

async def verify_recycling_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    provided_code = update.message.text.strip()
    recycling_info = context.user_data.get('current_recycling')
    
    logger.info("=== Recycling Verification Process Started ===")
    logger.info(f"User ID: {update.message.from_user.id}")
    logger.info(f"Provided code: '{provided_code}' (length: {len(provided_code)})")
    logger.info(f"Recycling info: {recycling_info}")
    logger.info(f"Full context user data: {context.user_data}")
    
    if not recycling_info:
        logger.error("=== Verification Failed ===")
        logger.error("Missing recycling info in context")
        await update.message.reply_text("No active recycling found. Please use /recycle again.")
        return ConversationHandler.END
    
    stored_code = recycling_info[1]  # verification_code
    logger.info(f"Stored code: '{stored_code}' (length: {len(stored_code) if stored_code else 0})")
    
    if provided_code == stored_code:
        logger.info("=== Verification Successful ===")
        conn = sqlite3.connect('waste_management.db')
        cursor = conn.cursor()
        
        # Create recycling transaction
        cursor.execute('''
            INSERT INTO recycling_transactions 
            (collector_id, recycler_id, status)
            VALUES (?, ?, 'completed')
        ''', (update.message.from_user.id, recycling_info[0]))
        
        transaction_id = cursor.lastrowid
        logger.info(f"Created recycling transaction {transaction_id}")
        
        # Notify both collector and recycler
        completion_message = f"✅ Recycling Complete!\nTransaction ID: {transaction_id}\nStatus: Successfully completed"
        
        try:
            # Notify recycler
            logger.info(f"Attempting to notify recycler with ID: {recycling_info[0]}")
            await context.bot.send_message(
                chat_id=recycling_info[0],
                text=completion_message
            )
            logger.info("Successfully notified recycler")
            
            # Notify collector
            logger.info(f"Attempting to notify collector with ID: {update.message.from_user.id}")
            await context.bot.send_message(
                chat_id=update.message.from_user.id,
                text=completion_message
            )
            logger.info("Successfully notified collector")
            
            await update.message.reply_text("Recycling transaction marked as completed!")
        except Exception as e:
            logger.error(f"Error sending notifications: {str(e)}")
            await update.message.reply_text("Recycling completed but there was an error sending notifications.")
        
        conn.commit()
        conn.close()
        logger.info("=== Recycling Verification Process Completed Successfully ===")
    else:
        logger.error("=== Verification Failed ===")
        logger.error(f"Code mismatch - Provided: '{provided_code}', Expected: '{stored_code}'")
        await update.message.reply_text("Invalid verification code. Please try again.")
    
    return ConversationHandler.END

def main():
    # Setup database
    setup_database()
    
    # Request bot token
    while True:
        bot_token = input("Please enter your Telegram bot token: ").strip()
        if bot_token:
            break
        print("Error: Bot token cannot be empty. Please try again.")
    
    try:
        # Initialize bot
        print("Initializing bot...")
        application = Application.builder().token(bot_token).build()
        
        # Add conversation handler for registration
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('start', start),
                CommandHandler('complete', complete_pickup),
                CommandHandler('recycle', recycle)
            ],
            states={
                CHOOSING_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, role_chosen)],
                ENTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_entered)],
                ENTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_entered)],
                ENTER_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, location_entered)],
                ENTER_VERIFICATION_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_pickup_code)],
                ENTER_RECYCLING_VERIFICATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_recycling_code)],
                ENTER_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_weight)],
                ENTER_RECYCLER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_recycler_name)],
            },
            fallbacks=[],
        )
        
        application.add_handler(conv_handler)
        
        # Add other command handlers
        application.add_handler(CommandHandler("status", toggle_status))
        application.add_handler(CommandHandler("request", create_request))
        application.add_handler(CommandHandler("verify_recycling", verify_recycling))
        application.add_handler(CommandHandler("weight", record_weight))
        
        # Start the bot
        print("Starting bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        print(f"Error initializing bot: {e}")
        print("Please check your bot token and try again.")
        return

if __name__ == '__main__':
    main() 