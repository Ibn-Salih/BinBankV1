import sys
import logging as py_logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
import sqlite3
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import os
import random
import string
from pycardano import *
import json
from dotenv import load_dotenv
from yoroi_integration import YoroiWallet

# Load environment variables
load_dotenv()

# Configure logging
py_logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=py_logging.INFO
)
logger = py_logging.getLogger(__name__)

# Cardano configuration from environment variables
NETWORK = Network.TESTNET if os.getenv('CARDANO_NETWORK') == 'testnet' else Network.MAINNET
context = BlockFrostChainContext(
    project_id=os.getenv('BLOCKFROST_PROJECT_ID'),
    network=NETWORK
)

# Cardano configuration dictionary
cardano_config = {
    'network': os.getenv('CARDANO_NETWORK'),
    'sender_address': os.getenv('CARDANO_SENDER_ADDRESS'),
    'sender_private_key': os.getenv('CARDANO_SENDER_PRIVATE_KEY'),
    'reward_amount': int(os.getenv('CARDANO_REWARD_AMOUNT', '2000000'))
}

# Validate required environment variables
required_vars = [
    'BLOCKFROST_PROJECT_ID',
    'CARDANO_NETWORK',
    'CARDANO_SENDER_ADDRESS',
    'CARDANO_SENDER_PRIVATE_KEY'
]

missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    raise Exception(f"Missing required environment variables: {', '.join(missing_vars)}")

# States for conversation handler
CHOOSING_ROLE, ENTER_NAME, ENTER_PHONE, ENTER_LOCATION, ENTER_VERIFICATION_CODE, ENTER_WEIGHT, ENTER_RECYCLING_VERIFICATION, ENTER_RECYCLER_NAME, ENTER_WASTE_DESCRIPTION, ENTER_WALLET = range(10)

# Initialize Yoroi wallet
yoroi_wallet = YoroiWallet()

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
            is_online INTEGER DEFAULT 1,
            wallet_address TEXT
        )
    ''')
    
    # Create pickup requests table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pickup_requests (
            id INTEGER PRIMARY KEY,
            creator_id INTEGER,
            collector_id INTEGER,
            waste_type TEXT DEFAULT 'Plastic',
            waste_description TEXT,
            status TEXT DEFAULT 'pending',
            payment_status TEXT DEFAULT 'pending',
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
    
    await update.message.reply_text(
        "Please provide a brief description of the plastic waste (optional):",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ENTER_WASTE_DESCRIPTION

async def process_waste_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    waste_description = update.message.text
    user_id = update.message.from_user.id
    
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    # Create pickup request with waste type and description
    cursor.execute('''
        INSERT INTO pickup_requests 
        (creator_id, waste_type, waste_description) 
        VALUES (?, ?, ?)
    ''', (user_id, 'Plastic', waste_description))
    
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
            f"Waste Type: Plastic\n"
            f"Description: {waste_description}\n"
            f"A collector has been assigned and will pick up your waste within 5 hours.\n"
            f"You will receive a verification code when the collector arrives."
        )
        
        # Try to notify collector
        try:
            await context.bot.send_message(
                chat_id=nearest_collector[0],
                text=f"New pickup request (ID: {request_id}) has been assigned to you.\n"
                     f"Waste Type: Plastic\n"
                     f"Description: {waste_description}\n"
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
    return ConversationHandler.END

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
        
        try:
            # Update pickup status
            cursor.execute('''
                UPDATE pickup_requests
                SET status = 'completed'
                WHERE id = ?
            ''', (pickup_info[0],))
            logger.info(f"Updated pickup request {pickup_info[0]} status to 'completed'")
            
            # Get creator and collector IDs
            cursor.execute('''
                SELECT creator_id, collector_id
                FROM pickup_requests
                WHERE id = ?
            ''', (pickup_info[0],))
            users = cursor.fetchone()
            
            if not users:
                raise Exception("Could not find users for this pickup request")
            
            creator_id, collector_id = users
            
            # Send completion message to both users
            completion_message = f"✅ Pickup Complete!\nRequest ID: {pickup_info[0]}\nStatus: Successfully completed"
            
            # Notify creator
            await context.bot.send_message(
                chat_id=creator_id,
                text=completion_message
            )
            
            # Notify collector
            await context.bot.send_message(
                chat_id=collector_id,
                text=completion_message
            )
            
            # Ask for wallet addresses for both creator and collector
            await ask_for_wallet(update, context, creator_id, 'creator')
            await ask_for_wallet(update, context, collector_id, 'collector')
            
            await update.message.reply_text("Pickup request marked as completed!")
            
        except Exception as e:
            logger.error(f"Error in verification process: {e}")
            await update.message.reply_text("Error processing completion. Please try again.")
        finally:
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
    logger.info("=== Weight Recording Process Started ===")
    logger.info(f"Recycler ID: {user_id}")
    
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    # Check if user is a recycling company
    cursor.execute('SELECT role FROM users WHERE telegram_id = ?', (user_id,))
    user_role = cursor.fetchone()
    
    if not user_role or user_role[0] != 'Recycling Company':
        logger.error(f"User {user_id} is not a recycling company")
        await update.message.reply_text("Only Recycling Companies can record weights.")
        conn.close()
        return
    
    await update.message.reply_text("Please enter the weight of the waste in kilograms:")
    return ENTER_WEIGHT

async def process_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        weight = float(update.message.text.strip())
        if weight <= 0:
            await update.message.reply_text("Please enter a valid weight greater than 0.")
            return ENTER_WEIGHT
        
        user_id = update.message.from_user.id
        logger.info(f"Processing weight {weight} kg for recycler {user_id}")
        
        conn = sqlite3.connect('waste_management.db')
        cursor = conn.cursor()
        
        try:
            # First, check if there's a pending recycling request
            cursor.execute('''
                SELECT id, collector_id 
                FROM recycling_transactions 
                WHERE recycler_id = ? 
                AND status = 'pending'
                ORDER BY created_at DESC 
                LIMIT 1
            ''', (user_id,))
            
            pending_transaction = cursor.fetchone()
            logger.info(f"Found pending transaction: {pending_transaction}")
            
            if not pending_transaction:
                logger.error(f"No pending recycling transaction found for recycler {user_id}")
                await update.message.reply_text("No pending recycling transaction found. Please wait for a waste collector to initiate recycling.")
                return ConversationHandler.END
            
            transaction_id = pending_transaction[0]
            collector_id = pending_transaction[1]
            
            # Get collector details
            cursor.execute('''
                SELECT telegram_id, full_name
                FROM users
                WHERE telegram_id = ?
            ''', (collector_id,))
            
            collector = cursor.fetchone()
            logger.info(f"Found collector: {collector}")
            
            if not collector:
                logger.error(f"Collector {collector_id} not found in users table")
                await update.message.reply_text("Error: Collector information not found. Please try again.")
                return ConversationHandler.END
            
            # Calculate payment (1kg = $1)
            amount = weight * 1.0
            logger.info(f"Calculated payment: ${amount:.2f}")
            
            # Generate verification code
            verification_code = generate_verification_code()
            logger.info(f"Generated verification code: {verification_code}")
            
            # Update existing transaction
            cursor.execute('''
                UPDATE recycling_transactions 
                SET weight_kg = ?,
                    amount_paid = ?,
                    verification_code = ?
                WHERE id = ?
            ''', (weight, amount, verification_code, transaction_id))
            
            logger.info(f"Updated recycling transaction {transaction_id}")
            
            # Store transaction info and verification code in context
            context.user_data['current_transaction'] = (transaction_id, collector[0], verification_code)
            logger.info(f"Stored in context - Transaction info: {context.user_data['current_transaction']}")
            
            # Notify collector with verification code and payment details
            try:
                logger.info(f"Attempting to notify collector with ID: {collector[0]}")
                collector_message = (
                    f"Your recycling company has recorded the weight!\n\n"
                    f"Transaction Details:\n"
                    f"• Weight: {weight} kg\n"
                    f"• Payment Rate: $1.00 per kg\n"
                    f"• Total Payment: ${amount:.2f}\n\n"
                    f"Please provide them with this verification code: {verification_code}"
                )
                await context.bot.send_message(
                    chat_id=collector[0],
                    text=collector_message
                )
                logger.info("Successfully notified collector")
            except Exception as e:
                logger.error(f"Could not notify collector: {e}")
                raise
            
            # Notify recycler
            recycler_message = (
                f"Transaction recorded!\n\n"
                f"Transaction Details:\n"
                f"• Weight: {weight} kg\n"
                f"• Payment Rate: $1.00 per kg\n"
                f"• Total Payment: ${amount:.2f}\n\n"
                f"Please ask the waste collector for the verification code and use /verify_recycling to complete the transaction."
            )
            await update.message.reply_text(recycler_message)
            logger.info("Successfully notified recycler")
            
            conn.commit()
            logger.info("Transaction committed to database")
            
            # Ask for verification code
            await update.message.reply_text(
                "Please enter the verification code provided by the waste collector:"
            )
            return ENTER_RECYCLING_VERIFICATION
            
        except Exception as e:
            logger.error(f"Error processing weight: {e}")
            conn.rollback()
            await update.message.reply_text("An error occurred while processing the weight. Please try again.")
            return ConversationHandler.END
        finally:
            conn.close()
            logger.info("Database connection closed")
        
    except ValueError:
        logger.error("Invalid weight value entered")
        await update.message.reply_text("Please enter a valid number.")
        return ENTER_WEIGHT

async def verify_recycling(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    logger.info("=== Recycling Verification Process Started ===")
    logger.info(f"Recycler ID: {user_id}")
    
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    # Check if user is a recycling company
    cursor.execute('SELECT role FROM users WHERE telegram_id = ?', (user_id,))
    user_role = cursor.fetchone()
    
    if not user_role or user_role[0] != 'Recycling Company':
        logger.error(f"User {user_id} is not a recycling company")
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
    
    try:
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
        
        # Create initial recycling transaction
        cursor.execute('''
            INSERT INTO recycling_transactions 
            (collector_id, recycler_id, status)
            VALUES (?, ?, 'pending')
        ''', (collector_id, recycler[0]))
        
        transaction_id = cursor.lastrowid
        logger.info(f"Created initial recycling transaction {transaction_id}")
        
        # Store recycler info in context
        context.user_data['current_recycling'] = (recycler[0],)
        logger.info(f"Stored in context - Recycler info: {recycler[0]}")
        
        # Notify recycler
        try:
            logger.info(f"Attempting to notify recycler with ID: {recycler[0]}")
            await context.bot.send_message(
                chat_id=recycler[0],
                text=f"A waste collector has arrived with waste for recycling!\n"
                     f"Please use /weight to record the weight of the waste."
            )
            logger.info("Successfully notified recycler")
        except Exception as e:
            logger.error(f"Could not notify recycler: {e}")
            await update.message.reply_text("Error: Could not notify recycling company. Please try again.")
            return ConversationHandler.END
        
        await update.message.reply_text(
            "Please wait for the recycling company to record the weight and provide you with a verification code."
        )
        logger.info("=== Recycling Process Completed - Waiting for Weight Recording ===")
        
        conn.commit()
        logger.info("Transaction committed to database")
        
    except Exception as e:
        logger.error(f"Error in process_recycler_name: {e}")
        conn.rollback()
        await update.message.reply_text("An error occurred. Please try again.")
        return ConversationHandler.END
    finally:
        conn.close()
        logger.info("Database connection closed")
    
    return ConversationHandler.END

async def verify_recycling_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    provided_code = update.message.text.strip()
    transaction_info = context.user_data.get('current_transaction')
    
    logger.info("=== Recycling Verification Process Started ===")
    logger.info(f"User ID: {update.message.from_user.id}")
    logger.info(f"Provided code: '{provided_code}' (length: {len(provided_code)})")
    logger.info(f"Transaction info: {transaction_info}")
    logger.info(f"Full context user data: {context.user_data}")
    
    if not transaction_info:
        logger.error("=== Verification Failed ===")
        logger.error("Missing transaction info in context")
        await update.message.reply_text("No active recycling found. Please use /recycle again.")
        return ConversationHandler.END
    
    stored_code = transaction_info[2]  # verification_code
    logger.info(f"Stored code: '{stored_code}' (length: {len(stored_code) if stored_code else 0})")
    
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    try:
        if provided_code == stored_code:
            logger.info("=== Verification Successful ===")
            
            # Update recycling transaction status
            cursor.execute('''
                UPDATE recycling_transactions
                SET status = 'completed'
                WHERE id = ?
            ''', (transaction_info[0],))
            
            transaction_id = transaction_info[0]
            logger.info(f"Updated recycling transaction {transaction_id} status to 'completed'")
            
            # Get transaction details for the completion message
            cursor.execute('''
                SELECT weight_kg, amount_paid
                FROM recycling_transactions
                WHERE id = ?
            ''', (transaction_id,))
            transaction_details = cursor.fetchone()
            
            # Notify both collector and recycler
            completion_message = (
                f"✅ Recycling Complete!\n"
                f"Transaction ID: {transaction_id}\n"
                f"Weight: {transaction_details[0]} kg\n"
                f"Payment: ${transaction_details[1]:.2f}\n"
                f"Status: Successfully completed"
            )
            
            # Notify recycler
            logger.info(f"Attempting to notify recycler with ID: {update.message.from_user.id}")
            await context.bot.send_message(
                chat_id=update.message.from_user.id,
                text=completion_message
            )
            logger.info("Successfully notified recycler")
            
            # Notify collector
            logger.info(f"Attempting to notify collector with ID: {transaction_info[1]}")
            await context.bot.send_message(
                chat_id=transaction_info[1],
                text=completion_message
            )
            logger.info("Successfully notified collector")
            
            await update.message.reply_text("Recycling transaction marked as completed!")
            logger.info("=== Recycling Verification Process Completed Successfully ===")
        else:
            logger.error("=== Verification Failed ===")
            logger.error(f"Code mismatch - Provided: '{provided_code}', Expected: '{stored_code}'")
            await update.message.reply_text("Invalid verification code. Please try again.")
    except Exception as e:
        logger.error(f"Error during verification: {str(e)}")
        await update.message.reply_text("An error occurred during verification. Please try again.")
    finally:
        conn.commit()
        conn.close()
    
    return ConversationHandler.END

async def wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        # Parse the callback data
        parts = query.data.split('_')
        if len(parts) != 3:
            logger.error(f"Invalid callback data format: {query.data}")
            await query.message.reply_text("Error processing wallet request. Please try again.")
            return ConversationHandler.END
            
        _, user_id, role = parts
        user_id = int(user_id)
        
        # Store the user info in context
        context.user_data['wallet_user_id'] = user_id
        context.user_data['wallet_role'] = role
        
        # Send a new message asking for the wallet address
        await context.bot.send_message(
            chat_id=user_id,
            text="Please enter your Cardano wallet address to receive your 2 ADA reward:"
        )
        
        # Set the conversation state to ENTER_WALLET
        return ENTER_WALLET
        
    except Exception as e:
        logger.error(f"Error in wallet callback: {e}")
        await query.message.reply_text("Error processing wallet request. Please try again.")
        return ConversationHandler.END

async def ask_for_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, role: str):
    try:
        keyboard = [
            [
                InlineKeyboardButton("Create Cardano Wallet", url="https://daedaluswallet.io/"),
                InlineKeyboardButton("I have a wallet", callback_data=f"has_wallet_{user_id}_{role}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = await context.bot.send_message(
            chat_id=user_id,
            text=f"To receive your 2 ADA reward for contributing to plastic waste management, "
                 f"please provide your Cardano wallet address.\n\n"
                 f"If you don't have a wallet yet, you can create one using Daedalus wallet.",
            reply_markup=reply_markup
        )
        logger.info(f"Sent wallet prompt to user {user_id} with role {role}")
        return ENTER_WALLET
    except Exception as e:
        logger.error(f"Error asking for wallet: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text="Error processing wallet request. Please try again."
        )
        return ConversationHandler.END

async def process_wallet_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallet_address = update.message.text.strip()
    
    # Get the user ID from context or use the message sender's ID
    user_id = context.user_data.get('wallet_user_id', update.message.from_user.id)
    
    # Validate Cardano address format
    try:
        PaymentAddress.from_primitive(wallet_address)
    except Exception as e:
        await update.message.reply_text(
            "Invalid Cardano wallet address. Please provide a valid address:"
        )
        return ENTER_WALLET
    
    conn = sqlite3.connect('waste_management.db')
    cursor = conn.cursor()
    
    try:
        # Update user's wallet address
        cursor.execute('''
            UPDATE users
            SET wallet_address = ?
            WHERE telegram_id = ?
        ''', (wallet_address, user_id))
        
        conn.commit()
        
        # Send 2 ADA reward
        success = await send_cardano_payment(wallet_address, cardano_config['reward_amount'])
        
        if success:
            await update.message.reply_text(
                "🎉 Congratulations! 🎉\n\n"
                "You've successfully contributed to saving our community from improperly disposed plastic waste!\n\n"
                "Your 2 ADA reward has been sent to your wallet.\n"
                "Thank you for being part of the solution to make our environment cleaner and safer.\n\n"
                "Together, we can make a difference! 🌱♻️"
            )
        else:
            await update.message.reply_text(
                "There was an error processing your reward. Please try again later."
            )
    except Exception as e:
        logger.error(f"Error processing wallet address: {e}")
        await update.message.reply_text(
            "There was an error processing your wallet address. Please try again."
        )
    finally:
        conn.close()
    
    return ConversationHandler.END

async def send_cardano_payment(recipient_address: str, amount: int) -> bool:
    """
    Send ADA using Yoroi wallet integration
    """
    try:
        return await yoroi_wallet.send_payment(recipient_address, amount)
    except Exception as e:
        logger.error(f"Error sending Cardano payment: {e}")
        return False

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
                CommandHandler('recycle', recycle),
                CommandHandler('weight', record_weight),
                CommandHandler('verify_recycling', verify_recycling),
                CommandHandler('request', create_request)
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
                ENTER_WASTE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_waste_description)],
                ENTER_WALLET: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, process_wallet_address),
                    CallbackQueryHandler(wallet_callback, pattern="^has_wallet_")
                ],
            },
            fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)],
            name="waste_management_conversation",
            persistent=False
        )
        
        application.add_handler(conv_handler)
        
        # Add other command handlers
        application.add_handler(CommandHandler("status", toggle_status))
        
        # Start the bot
        print("Starting bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        print(f"Error initializing bot: {e}")
        print("Please check your bot token and try again.")
        return

if __name__ == '__main__':
    main() 