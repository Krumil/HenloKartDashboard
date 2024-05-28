import os
import json
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

web3 = Web3(Web3.WebsocketProvider(os.getenv("BASE_URL")))
if web3.is_connected():
    print("Connected to Base network successfully.")
else:
    print("Failed to connect to the Base network.")
    exit(1)  # Exit if there is no connection to avoid further errors

# Load the contract ABI
abi_path = "abi.json"
with open(abi_path, "r") as f:
    abi = json.load(f)

# Contract address
contract_address = Web3.to_checksum_address(
    "0x5f6687b70f7a6029dd37480592da84d465d8cbb7"
)

# Instantiate the contract
contract = web3.eth.contract(address=contract_address, abi=abi)
