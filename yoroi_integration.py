import sys
import logging as py_logging
from pycardano import *
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
py_logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=py_logging.INFO
)
logger = py_logging.getLogger(__name__)

class YoroiWallet:
    def __init__(self):
        self.network = Network.TESTNET if os.getenv('CARDANO_NETWORK') == 'testnet' else Network.MAINNET
        self.context = BlockFrostChainContext(
            project_id=os.getenv('BLOCKFROST_PROJECT_ID'),
            network=self.network
        )
        self.sender_address = os.getenv('CARDANO_SENDER_ADDRESS')
        
        if not self.sender_address:
            raise Exception("CARDANO_SENDER_ADDRESS not found in environment variables")

    async def send_payment(self, recipient_address: str, amount: int) -> bool:
        """
        Send ADA using Yoroi wallet.
        This will create a transaction that needs to be signed by the user in their Yoroi wallet.
        """
        try:
            # Create the transaction
            tx = TransactionBuilder(self.context)
            
            # Add input from sender
            tx.add_input_address(self.sender_address)
            
            # Add output to recipient
            tx.add_output(
                TransactionOutput(
                    address=Address.from_primitive(recipient_address),
                    amount=amount
                )
            )
            
            # Build the transaction
            tx_body = tx.build()
            
            # Create the transaction hash
            tx_hash = tx_body.hash()
            
            # Log transaction details
            logger.info(f"Created transaction: {tx_hash}")
            logger.info(f"Sending {amount} lovelace to {recipient_address}")
            
            # In a real implementation, we would:
            # 1. Use Yoroi's API to request transaction signing
            # 2. Wait for user approval in their Yoroi wallet
            # 3. Submit the signed transaction
            
            # For now, we'll just log that the transaction was created
            logger.info("Transaction created successfully. User needs to approve in Yoroi wallet.")
            return True
            
        except Exception as e:
            logger.error(f"Error creating transaction: {e}")
            return False

    def get_balance(self) -> int:
        """
        Get the balance of the sender's address
        """
        try:
            utxos = self.context.utxos(self.sender_address)
            total = 0
            for utxo in utxos:
                # Get the amount from the UTXO output
                amount = utxo.output.amount
                # If amount is a Value object, get the coin value
                if isinstance(amount, Value):
                    total += amount.coin
                else:
                    total += amount
            return total
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return 0

# Example usage:
if __name__ == "__main__":
    wallet = YoroiWallet()
    print(f"Wallet address: {wallet.sender_address}")
    balance = wallet.get_balance()
    print(f"Current balance: {balance} lovelace ({balance/1000000} ADA)") 