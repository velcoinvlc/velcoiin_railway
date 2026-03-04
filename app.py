import os
from flask import Flask, jsonify, request, render_template_string
import json
import hashlib
import time
import logging
import random
import string
from functools import wraps
from collections import defaultdict
from datetime import datetime
import threading
import base64
import requests

app = Flask(__name__)

# -----------------------
# GITHUB BACKUP CONFIG
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = "velcoinvlc/velcoin-backups"
GITHUB_BRANCH = "main"
BACKUP_FILES = ["state.json", "blockchain.json", "mempool.json", "nonces.json", "ledger.json"]

# -----------------------
# PATHS
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state.json")
LEDGER_FILE = os.path.join(BASE_DIR, "ledger.json")
BLOCKCHAIN_FILE = os.path.join(BASE_DIR, "blockchain.json")
MEMPOOL_FILE = os.path.join(BASE_DIR, "mempool.json")
POOL_FILE = os.path.join(BASE_DIR, "pool.json")
NONCE_FILE = os.path.join(BASE_DIR, "nonces.json")
LOG_FILE = os.path.join(BASE_DIR, "node.log")
PEERS_FILE = os.path.join(BASE_DIR, "peers.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# -----------------------
# GITHUB BACKUP FUNCTIONS
def github_api_request(method, path, data=None):
    """Hace peticiones a la API de GitHub"""
    if not GITHUB_TOKEN:
        return None
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=30)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data, timeout=30)
        else:
            return None
        
        return response
    except Exception as e:
        logging.error(f"GitHub API error: {e}")
        return None

def get_file_sha(filepath):
    """Obtiene el SHA de un archivo en GitHub"""
    response = github_api_request("GET", f"/contents/{filepath}?ref={GITHUB_BRANCH}")
    if response and response.status_code == 200:
        return response.json().get("sha")
    return None

def backup_file_to_github(filepath, github_path):
    """Sube un archivo individual a GitHub"""
    if not os.path.exists(filepath):
        return False
    
    try:
        with open(filepath, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        
        sha = get_file_sha(github_path)
        
        data = {
            "message": f"Backup {github_path} - {int(time.time())}",
            "content": content,
            "branch": GITHUB_BRANCH
        }
        if sha:
            data["sha"] = sha
        
        response = github_api_request("PUT", f"/contents/{github_path}", data)
        return response and response.status_code in [200, 201]
    except Exception as e:
        logging.error(f"Error backing up {filepath}: {e}")
        return False

def restore_file_from_github(github_path, local_path):
    """Descarga un archivo desde GitHub"""
    response = github_api_request("GET", f"/contents/{github_path}?ref={GITHUB_BRANCH}")
    if not response or response.status_code != 200:
        return False
    
    try:
        content = base64.b64decode(response.json()["content"])
        with open(local_path, "wb") as f:
            f.write(content)
        logging.info(f"✓ RESTORED {github_path} from GitHub ({len(content)} bytes)")
        return True
    except Exception as e:
        logging.error(f"✗ Error restoring {github_path}: {e}")
        return False

def restore_all_from_github():
    """Restaura TODOS los archivos desde GitHub, sobrescribiendo locales si existen en GitHub"""
    if not GITHUB_TOKEN:
        logging.warning("GITHUB_TOKEN not set, skipping restore")
        return False
    
    logging.info("=" * 50)
    logging.info("STARTING RESTORE FROM GITHUB")
    logging.info(f"Repository: {GITHUB_REPO}")
    logging.info(f"Branch: {GITHUB_BRANCH}")
    logging.info("=" * 50)
    
    restored_any = False
    
    for filename in BACKUP_FILES:
        local_path = os.path.join(BASE_DIR, filename)
        
        # SIEMPRE intentar restaurar si existe en GitHub
        # Primero verificar si existe en GitHub
        logging.info(f"Checking {filename} in GitHub...")
        response = github_api_request("GET", f"/contents/{filename}?ref={GITHUB_BRANCH}")
        
        if not response:
            logging.warning(f"✗ No response from GitHub for {filename}")
            continue
            
        if response.status_code == 404:
            logging.info(f"- {filename} not found in GitHub (will be created later)")
            continue
            
        if response.status_code != 200:
            logging.error(f"✗ GitHub error {response.status_code} for {filename}: {response.text[:200]}")
            continue
        
        # Existe en GitHub, intentar restaurar SIEMPRE
        logging.info(f"Found {filename} in GitHub, restoring...")
        
        # Eliminar archivo local si existe para forzar restauración limpia
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
                logging.info(f"  Removed existing local {filename}")
            except Exception as e:
                logging.warning(f"  Could not remove existing {filename}: {e}")
        
        # Restaurar desde GitHub
        success = restore_file_from_github(filename, local_path)
        if success:
            restored_any = True
            # Verificar que se restauró correctamente
            try:
                with open(local_path, 'r') as f:
                    content = json.load(f)
                    if isinstance(content, list):
                        logging.info(f"  Verified: {len(content)} items in {filename}")
                    elif isinstance(content, dict):
                        logging.info(f"  Verified: {len(content)} keys in {filename}")
            except Exception as e:
                logging.warning(f"  Could not verify {filename}: {e}")
        else:
            logging.error(f"✗ FAILED to restore {filename}")
    
    logging.info("=" * 50)
    if restored_any:
        logging.info("RESTORE COMPLETED SUCCESSFULLY")
    else:
        logging.info("NO FILES WERE RESTORED (may not exist in GitHub)")
    logging.info("=" * 50)
    
    return restored_any

def backup_all_to_github():
    """Hace backup de todos los archivos críticos"""
    if not GITHUB_TOKEN:
        logging.warning("GITHUB_TOKEN not set, skipping backup")
        return
    
    logging.info("Starting GitHub backup...")
    for filename in BACKUP_FILES:
        filepath = os.path.join(BASE_DIR, filename)
        if os.path.exists(filepath):
            success = backup_file_to_github(filepath, filename)
            status = "✓" if success else "✗"
            logging.info(f"{status} {filename}")
    logging.info("GitHub backup completed")

# -----------------------
# JSON IO (must be defined before use)
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Error loading {path}: {e}")
            return default
    return default

def save_json(path, data):
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.warning(f"Error saving {path}: {e}")

# -----------------------
# CONFIGURATION
DEFAULT_CONFIG = {
    "network_name": "velcoin-mainnet",
    "network_version": "1.0.0",
    "min_tx_fee": 0.001,
    "max_tx_size": 10000,
    "block_time_target": 60,
    "explorer_enabled": True,
    "cors_origins": ["*"],
    "node_contact": "+13156961731",
    "node_operator": "Dainier Velazquez"
}

def load_config():
    return load_json(CONFIG_FILE, DEFAULT_CONFIG)

def save_config(cfg):
    save_json(CONFIG_FILE, cfg)

CONFIG = load_config()

# -----------------------
# LOGGING
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(console_handler)

# -----------------------
# RATE LIMIT
RATE_LIMIT = defaultdict(list)
RATE_LIMIT_LOCK = threading.Lock()

def rate_limit(max_calls=100, window=60):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            with RATE_LIMIT_LOCK:
                ip = request.remote_addr
                now = time.time()
                RATE_LIMIT[ip] = [t for t in RATE_LIMIT[ip] if now - t < window]
                if len(RATE_LIMIT[ip]) >= max_calls:
                    return jsonify({"error": "rate limit exceeded", "retry_after": int(window)}), 429
                RATE_LIMIT[ip].append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator

# -----------------------
# CRYPTO
def sha256(msg):
    return hashlib.sha256(msg.encode()).hexdigest()

def double_sha256(msg):
    return sha256(sha256(msg))

def derive_address(public_key):
    return sha256(public_key)[:40]

def sign_tx(private_key, payload):
    return sha256(private_key + payload)

def verify_signature(public_key, payload, signature):
    expected = sha256(sha256(public_key) + payload)
    return expected == signature

# -----------------------
# STATE MANAGEMENT
def load_state():
    return load_json(STATE_FILE, {})

def save_state(x):
    save_json(STATE_FILE, x)
    # Backup SÍNCRONO para asegurar que se complete antes de continuar
    try:
        success = backup_file_to_github(STATE_FILE, "state.json")
        if success:
            logging.info("✓ state.json backed up to GitHub")
        else:
            logging.warning("✗ state.json backup failed")
    except Exception as e:
        logging.error(f"Error backing up state: {e}")

def get_address_history(address):
    """Get complete transaction history for an address"""
    history = []
    chain = load_blockchain()
    for block in chain:
        for tx in block.get('transactions', []):
            if tx.get('from') == address or tx.get('to') == address:
                history.append({
                    'block_index': block['index'],
                    'block_hash': block['block_hash'],
                    'timestamp': block['timestamp'],
                    **tx
                })
    mempool = load_mempool()
    for tx in mempool:
        if tx.get('from') == address or tx.get('to') == address:
            history.append({
                'status': 'pending',
                **tx
            })
    return sorted(history, key=lambda x: x.get('timestamp', 0), reverse=True)

# -----------------------
# NONCES
def load_nonces():
    return load_json(NONCE_FILE, {})

def save_nonces(x):
    save_json(NONCE_FILE, x)
    threading.Thread(target=backup_file_to_github, args=(NONCE_FILE, "nonces.json"), daemon=True).start()

def get_next_nonce(address):
    nonces = load_nonces()
    return nonces.get(address, 0) + 1

# -----------------------
# LEDGER
def load_ledger():
    return load_json(LEDGER_FILE, [])

def save_ledger(x):
    save_json(LEDGER_FILE, x)
    threading.Thread(target=backup_file_to_github, args=(LEDGER_FILE, "ledger.json"), daemon=True).start()

def ensure_ledger():
    if not os.path.exists(LEDGER_FILE):
        save_ledger([])
    return load_ledger()

def add_to_ledger(tx_hash, tx_data, block_index=None):
    ledger = load_ledger()
    entry = {
        'tx_hash': tx_hash,
        'timestamp': int(time.time()),
        'block_index': block_index,
        **tx_data
    }
    ledger.append(entry)
    save_ledger(ledger)
    return entry

# -----------------------
# MEMPOOL
def load_mempool():
    return load_json(MEMPOOL_FILE, [])

def save_mempool(x):
    save_json(MEMPOOL_FILE, x)
    threading.Thread(target=backup_file_to_github, args=(MEMPOOL_FILE, "mempool.json"), daemon=True).start()

def add_tx_to_mempool(tx):
    mempool = load_mempool()
    tx['received_at'] = int(time.time())
    mempool.append(tx)
    save_mempool(mempool)
    return tx

def remove_from_mempool(tx_hash):
    mempool = load_mempool()
    mempool = [tx for tx in mempool if tx.get('hash') != tx_hash]
    save_mempool(mempool)

def get_mempool_size():
    return len(load_mempool())

# -----------------------
# BLOCKCHAIN
def load_blockchain():
    return load_json(BLOCKCHAIN_FILE, [])

def save_blockchain(x):
    save_json(BLOCKCHAIN_FILE, x)
    threading.Thread(target=backup_file_to_github, args=(BLOCKCHAIN_FILE, "blockchain.json"), daemon=True).start()

DIFFICULTY = 4

def calculate_block_reward(block_index):
    """No block rewards in VelCoin - fixed supply"""
    return 0

def create_genesis_block():
    chain = load_blockchain()
    if chain:
        return chain[0]
    
    genesis = {
        "index": 0,
        "timestamp": int(time.time()),
        "transactions": [],
        "previous_hash": "0" * 64,
        "nonce": 0,
        "merkle_root": "0" * 64,
        "difficulty": DIFFICULTY
    }
    genesis["block_hash"] = calculate_block_hash(genesis)
    chain.append(genesis)
    save_blockchain(chain)
    logging.info(f"Genesis block created: {genesis['block_hash']}")
    return genesis

def calculate_block_hash(block):
    """Calculate SHA256 hash of block data"""
    block_data = {
        'index': block['index'],
        'timestamp': block['timestamp'],
        'transactions': block.get('transactions', []),
        'previous_hash': block['previous_hash'],
        'nonce': block['nonce'],
        'merkle_root': block.get('merkle_root', '')
    }
    return sha256(json.dumps(block_data, sort_keys=True))

def calculate_merkle_root(transactions):
    """Calculate merkle root of transactions"""
    if not transactions:
        return "0" * 64
    
    tx_hashes = [sha256(json.dumps(tx, sort_keys=True)) for tx in transactions]
    
    while len(tx_hashes) > 1:
        if len(tx_hashes) % 2 == 1:
            tx_hashes.append(tx_hashes[-1])
        
        new_level = []
        for i in range(0, len(tx_hashes), 2):
            combined = tx_hashes[i] + tx_hashes[i+1]
            new_level.append(sha256(combined))
        tx_hashes = new_level
    
    return tx_hashes[0]

def mine_block(transactions, miner_address=None):
    """Mine a new block with given transactions"""
    chain = load_blockchain()
    last_block = chain[-1]
    
    # Calculate merkle root
    merkle_root = calculate_merkle_root(transactions)
    
    block = {
        "index": last_block["index"] + 1,
        "timestamp": int(time.time()),
        "transactions": transactions,
        "previous_hash": last_block["block_hash"],
        "merkle_root": merkle_root,
        "nonce": 0,
        "difficulty": DIFFICULTY,
        "miner": miner_address
    }
    
    # Mining loop
    start_time = time.time()
    while True:
        block_hash = calculate_block_hash(block)
        if block_hash.startswith("0" * DIFFICULTY):
            block["block_hash"] = block_hash
            block["hashing_time"] = round(time.time() - start_time, 3)
            break
        block["nonce"] += 1
    
    # Validate and add block
    if validate_block(block, last_block):
        chain.append(block)
        save_blockchain(chain)
        
        # Clear mempool
        save_mempool([])
        
                # Update ledger and add hash to transactions
        for tx in transactions:
            tx_hash = sha256(json.dumps(tx, sort_keys=True))
            tx['hash'] = tx_hash
            add_to_ledger(tx_hash, tx, block['index'])
        
        logging.info(f"Block mined: {block_hash} | Txs: {len(transactions)} | Nonce: {block['nonce']} | Time: {block['hashing_time']}s")
        return block
    else:
        raise Exception("Block validation failed")

def validate_block(block, previous_block):
    """Validate a new block"""
    # Check index
    if block["index"] != previous_block["index"] + 1:
        return False
    
    # Check previous hash
    if block["previous_hash"] != previous_block["block_hash"]:
        return False
    
    # Check difficulty
    if not block["block_hash"].startswith("0" * DIFFICULTY):
        return False
    
    # Verify hash
    if calculate_block_hash(block) != block["block_hash"]:
        return False
    
    return True

def get_block_by_hash(block_hash):
    """Get block by its hash"""
    chain = load_blockchain()
    for block in chain:
        if block.get('block_hash') == block_hash:
            return block
    return None

def get_block_by_index(index):
    """Get block by its index"""
    chain = load_blockchain()
    if 0 <= index < len(chain):
        return chain[index]
    return None

def get_transaction(tx_hash):
    """Get transaction by hash from blockchain or mempool"""
    # Search in blockchain
    chain = load_blockchain()
    for block in chain:
        for tx in block.get('transactions', []):
            # Primero revisar si la transacción ya tiene hash guardado
            tx_stored_hash = tx.get('hash')
            if tx_stored_hash:
                if tx_stored_hash == tx_hash:
                    return {
                        'status': 'confirmed',
                        'confirmations': len(chain) - block['index'],
                        'block_index': block['index'],
                        'block_hash': block['block_hash'],
                        'timestamp': block['timestamp'],
                        **tx
                    }
            else:
                # Recalcular ignorando el campo 'hash' si existiera
                tx_copy = {k: v for k, v in tx.items() if k != 'hash'}
                if sha256(json.dumps(tx_copy, sort_keys=True)) == tx_hash:
                    return {
                        'status': 'confirmed',
                        'confirmations': len(chain) - block['index'],
                        'block_index': block['index'],
                        'block_hash': block['block_hash'],
                        'timestamp': block['timestamp'],
                        **tx
                    }
    
    # Search in mempool
    mempool = load_mempool()
    for tx in mempool:
        tx_stored_hash = tx.get('hash')
        if tx_stored_hash:
            if tx_stored_hash == tx_hash:
                return {
                    'status': 'pending',
                    'confirmations': 0,
                    **tx
                }
        else:
            tx_copy = {k: v for k, v in tx.items() if k != 'hash'}
            if sha256(json.dumps(tx_copy, sort_keys=True)) == tx_hash:
                return {
                    'status': 'pending',
                    'confirmations': 0,
                    **tx
                }
    
    return None
    
# -----------------------
# NETWORK STATS
def get_network_stats():
    """Get comprehensive network statistics"""
    chain = load_blockchain()
    state = load_state()
    mempool = load_mempool()
    
    total_supply = sum(state.values()) if state else 0
    holders = len([v for v in state.values() if v > 0]) if state else 0
    
    # Calculate hash rate estimate (simplified)
    total_hashes = sum(b.get('nonce', 0) for b in chain)
    avg_block_time = 60  # target
    
    return {
        'network': CONFIG['network_name'],
        'version': CONFIG['network_version'],
        'block_height': len(chain) - 1,
        'total_blocks': len(chain),
        'total_supply': total_supply,
        'holders': holders,
        'mempool_size': len(mempool),
        'difficulty': DIFFICULTY,
        'avg_block_time': avg_block_time,
        'genesis_timestamp': chain[0]['timestamp'] if chain else None,
        'last_block_timestamp': chain[-1]['timestamp'] if chain else None,
        'last_block_hash': chain[-1]['block_hash'] if chain else None
    }

# -----------------------
# WALLET FUNDADORA
FUND_WALLET_DATA = os.environ.get("VELCOIN_FUND_WALLET")
if not FUND_WALLET_DATA:
    logging.error("Wallet fundadora no encontrada en VELCOIN_FUND_WALLET")
    # Create default for testing (REMOVE IN PRODUCTION)
    FUND_WALLET_JSON = {
        "private_key": "0" * 64,
        "public_key": sha256("0" * 64),
        "address": derive_address(sha256("0" * 64))
    }
    FUND_WALLET = FUND_WALLET_JSON["address"]
    logging.warning("Using default founder wallet - FOR TESTING ONLY")
else:
    try:
        FUND_WALLET_JSON = json.loads(FUND_WALLET_DATA)
        FUND_WALLET = FUND_WALLET_JSON["address"]
        logging.info("Founder wallet loaded successfully")
    except Exception as e:
        logging.error(f"Error loading founder wallet: {e}")
        raise Exception("Invalid founder wallet configuration")

# -----------------------
# POOL MANAGEMENT
def ensure_pool():
    """Ensure pool tracking is current"""
    state = load_state()
    fund_balance = state.get(FUND_WALLET, 0)
    pool_data = {
        "velcoin": fund_balance,
        "total_supply": get_total_supply(),
        "founder_wallet": FUND_WALLET,
        "last_updated": int(time.time())
    }
    save_json(POOL_FILE, pool_data)
    return pool_data

def get_total_supply():
    """Calculate total supply from state"""
    state = load_state()
    return sum(state.values())

# -----------------------
# WALLET FUNCTIONS
def generate_wallet():
    """Generate a new wallet"""
    private_key = ''.join(random.choices(string.hexdigits, k=64)).lower()
    public_key = sha256(private_key)
    address = derive_address(public_key)
    return {
        "private_key": private_key,
        "public_key": public_key,
        "address": address,
        "created_at": int(time.time())
    }

def get_wallet_balance(address):
    """Get balance and history for a wallet"""
    state = load_state()
    balance = state.get(address, 0)
    history = get_address_history(address)
    return {
        'address': address,
        'balance': balance,
        'transaction_count': len(history),
        'transactions': history[:10]  # Last 10
    }

# -----------------------
# TRANSACTION VALIDATION
def validate_tx(tx, check_balance=True):
    """Validate a transaction comprehensively"""
    required = ["from", "to", "amount", "nonce", "public_key", "signature"]
    
    for field in required:
        if field not in tx:
            return False, f"Missing field: {field}"
    
    # Validate addresses (40 hex chars)
    if not isinstance(tx['from'], str) or len(tx['from']) != 40:
        return False, "Invalid sender address format"
    
    if not isinstance(tx['to'], str) or len(tx['to']) != 40:
        return False, "Invalid recipient address format"
    
    # Validate amount
    try:
        amount = float(tx['amount'])
        if amount <= 0:
            return False, "Amount must be positive"
        if amount > 1e12:  # Sanity check
            return False, "Amount too large"
    except:
        return False, "Invalid amount"
    
    # Validate public key matches address
    sender = tx["from"]
    pub = tx["public_key"]
    if derive_address(pub) != sender:
        return False, "Address/public key mismatch"
    
    # Verify signature
    payload = f'{tx["from"]}{tx["to"]}{tx["amount"]}{tx["nonce"]}'
    if not verify_signature(pub, payload, tx["signature"]):
        return False, "Invalid signature"
    
    # Check nonce
    nonces = load_nonces()
    last_nonce = nonces.get(sender, 0)
    if tx["nonce"] <= last_nonce:
        return False, f"Invalid nonce (expected {last_nonce + 1}, got {tx['nonce']})"
    
    # Check balance
    if check_balance:
        state = load_state()
        balance = state.get(sender, 0)
        if balance < amount:
            return False, f"Insufficient balance ({balance} < {amount})"
    
    return True, "Valid"

def create_transaction(sender_priv, sender_pub, sender_addr, recipient, amount, nonce=None):
    """Create and sign a transaction"""
    if nonce is None:
        nonce = get_next_nonce(sender_addr)
    
    tx = {
        'from': sender_addr,
        'to': recipient,
        'amount': float(amount),
        'nonce': nonce,
        'public_key': sender_pub,
        'timestamp': int(time.time())
    }
    
    payload = f'{tx["from"]}{tx["to"]}{tx["amount"]}{tx["nonce"]}'
    tx['signature'] = sign_tx(sender_priv, payload)
    tx['hash'] = sha256(json.dumps(tx, sort_keys=True))
    
    return tx

# -----------------------
# EXPLORER TEMPLATES
EXPLORER_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VelCoin Explorer | VLC Blockchain</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0d1a;
            color: #e5e7eb;
            line-height: 1.6;
        }
        .header {
            background: linear-gradient(135deg, #8B5CF6 0%, #7C3AED 100%);
            padding: 20px 0;
            box-shadow: 0 4px 20px rgba(139, 92, 246, 0.3);
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }
        .header-content {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 20px;
        }
        .logo {
            display: flex;
            align-items: center;
            gap: 15px;
            color: white;
            text-decoration: none;
        }
        .logo img {
            width: 50px;
            height: 50px;
            border-radius: 50%;
        }
        .logo h1 {
            font-size: 1.8em;
        }
        .nav {
            display: flex;
            gap: 25px;
        }
        .nav a {
            color: rgba(255,255,255,0.9);
            text-decoration: none;
            font-weight: 500;
            transition: color 0.3s;
        }
        .nav a:hover {
            color: white;
        }
        .search-box {
            width: 100%;
            max-width: 600px;
            margin: 30px auto;
            position: relative;
        }
        .search-box input {
            width: 100%;
            padding: 18px 25px;
            border: 2px solid rgba(139, 92, 246, 0.3);
            border-radius: 50px;
            background: rgba(255,255,255,0.05);
            color: white;
            font-size: 1.1em;
            outline: none;
            transition: all 0.3s;
        }
        .search-box input:focus {
            border-color: #8B5CF6;
            background: rgba(255,255,255,0.1);
        }
        .search-box input::placeholder {
            color: rgba(255,255,255,0.5);
        }
        .search-box button {
            position: absolute;
            right: 5px;
            top: 50%;
            transform: translateY(-50%);
            padding: 12px 30px;
            background: #8B5CF6;
            border: none;
            border-radius: 50px;
            color: white;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        .search-box button:hover {
            background: #7C3AED;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }
        .stat-card {
            background: rgba(139, 92, 246, 0.1);
            border: 1px solid rgba(139, 92, 246, 0.2);
            border-radius: 16px;
            padding: 25px;
            text-align: center;
        }
        .stat-value {
            font-size: 2.2em;
            font-weight: 700;
            color: #A78BFA;
            display: block;
        }
        .stat-label {
            color: #C4B5FD;
            font-size: 0.95em;
            margin-top: 5px;
        }
        .section {
            background: rgba(139, 92, 246, 0.05);
            border-radius: 20px;
            padding: 30px;
            margin: 25px 0;
            border: 1px solid rgba(139, 92, 246, 0.1);
        }
        .section h2 {
            color: #A78BFA;
            margin-bottom: 20px;
            font-size: 1.5em;
        }
        .block-list, .tx-list {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        .block-item, .tx-item {
            background: rgba(0,0,0,0.2);
            padding: 20px;
            border-radius: 12px;
            display: grid;
            grid-template-columns: auto 1fr auto;
            gap: 20px;
            align-items: center;
            transition: all 0.3s;
        }
        .block-item:hover, .tx-item:hover {
            background: rgba(139, 92, 246, 0.15);
            transform: translateX(5px);
        }
        .block-height, .tx-hash {
            font-family: 'Courier New', monospace;
            color: #8B5CF6;
            font-weight: 600;
        }
        .block-info, .tx-info {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }
        .block-info small, .tx-info small {
            color: #9CA3AF;
        }
        .block-time, .tx-amount {
            text-align: right;
            color: #C4B5FD;
        }
        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 500;
        }
        .badge-success {
            background: rgba(16, 185, 129, 0.2);
            color: #10B981;
        }
        .badge-pending {
            background: rgba(245, 158, 11, 0.2);
            color: #F59E0B;
        }
        .footer {
            text-align: center;
            padding: 40px;
            color: #6B7280;
            border-top: 1px solid rgba(139, 92, 246, 0.1);
            margin-top: 40px;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #8B5CF6;
        }
        @media (max-width: 768px) {
            .header-content { flex-direction: column; text-align: center; }
            .block-item, .tx-item { grid-template-columns: 1fr; }
            .block-time, .tx-amount { text-align: left; }
        }
    </style>
</head>
<body>
    <header class="header">
        <div class="container">
            <div class="header-content">
                <a href="/explorer" class="logo">
                    <img src="/logo" alt="VelCoin">
                    <div>
                        <h1>VelCoin Explorer</h1>
                        <small>velcoin-mainnet</small>
                    </div>
                </a>
                <nav class="nav">
                    <a href="/explorer">Home</a>
                    <a href="/explorer/blocks">Blocks</a>
                    <a href="/explorer/txs">Transactions</a>
                    <a href="/docs">API</a>
                </nav>
            </div>
        </div>
    </header>

    <main class="container">
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Search by block height, hash, transaction hash, or address...">
            <button onclick="search()">Search</button>
        </div>

        <div class="stats-grid" id="stats">
            <div class="stat-card">
                <span class="stat-value" id="blockHeight">-</span>
                <span class="stat-label">Block Height</span>
            </div>
            <div class="stat-card">
                <span class="stat-value" id="totalSupply">-</span>
                <span class="stat-label">Total Supply VLC</span>
            </div>
            <div class="stat-card">
                <span class="stat-value" id="holders">-</span>
                <span class="stat-label">Holders</span>
            </div>
            <div class="stat-card">
                <span class="stat-value" id="mempool">-</span>
                <span class="stat-label">Pending Txs</span>
            </div>
        </div>

        <div class="section">
            <h2>Latest Blocks</h2>
            <div class="block-list" id="latestBlocks">
                <div class="loading">Loading...</div>
            </div>
        </div>

        <div class="section">
            <h2>Latest Transactions</h2>
            <div class="tx-list" id="latestTxs">
                <div class="loading">Loading...</div>
            </div>
        </div>
    </main>

    <footer class="footer">
        <p>VelCoin (VLC) Blockchain Explorer</p>
        <p>2026 VelCoin. All rights reserved.</p>
    </footer>

    <script>
        async function loadStats() {
            try {
                const res = await fetch('/api/stats');
                const data = await res.json();
                document.getElementById('blockHeight').textContent = data.block_height.toLocaleString();
                document.getElementById('totalSupply').textContent = (data.total_supply / 1e6).toFixed(2) + 'M';
                document.getElementById('holders').textContent = data.holders.toLocaleString();
                document.getElementById('mempool').textContent = data.mempool_size;
            } catch (e) {
                console.error('Failed to load stats:', e);
            }
        }

        async function loadBlocks() {
            try {
                const res = await fetch('/api/blocks?limit=5');
                const blocks = await res.json();
                const container = document.getElementById('latestBlocks');
                container.innerHTML = blocks.map(b => `
                    <div class="block-item" onclick="location.href='/explorer/block/${b.index}'">
                        <div class="block-height">#${b.index}</div>
                        <div class="block-info">
                            <span>${b.block_hash.substring(0, 20)}...</span>
                            <small>${b.transactions.length} transactions</small>
                        </div>
                        <div class="block-time">${new Date(b.timestamp * 1000).toLocaleString()}</div>
                    </div>
                `).join('');
            } catch (e) {
                console.error('Failed to load blocks:', e);
            }
        }

        async function loadTxs() {
            try {
                const res = await fetch('/api/mempool');
                const txs = await res.json();
                const container = document.getElementById('latestTxs');
                if (txs.length === 0) {
                    container.innerHTML = '<div style="text-align:center;color:#6B7280;padding:20px;">No pending transactions</div>';
                    return;
                }
                container.innerHTML = txs.slice(0, 5).map(t => `
                    <div class="tx-item">
                        <span class="badge badge-pending">Pending</span>
                        <div class="tx-info">
                            <span class="tx-hash">${t.hash ? t.hash.substring(0, 20) : 'N/A'}...</span>
                            <small>From: ${t.from.substring(0, 15)}... To: ${t.to.substring(0, 15)}...</small>
                        </div>
                        <div class="tx-amount">${parseFloat(t.amount).toFixed(4)} VLC</div>
                    </div>
                `).join('');
            } catch (e) {
                console.error('Failed to load txs:', e);
            }
        }

        function search() {
            const query = document.getElementById('searchInput').value.trim();
            if (!query) return;
            
            if (/^\\d+$/.test(query)) {
                location.href = `/explorer/block/${query}`;
            } else if (query.length === 64) {
                location.href = `/explorer/tx/${query}`;
            } else if (query.length === 40) {
                location.href = `/explorer/address/${query}`;
            } else {
                alert('Invalid search query. Enter block number, transaction hash (64 chars), or address (40 chars).');
            }
        }

        document.getElementById('searchInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') search();
        });

        loadStats();
        loadBlocks();
        loadTxs();
        setInterval(loadStats, 30000);
    </script>
</body>
</html>
'''

# -----------------------
# API ROUTES
@app.route("/")
@rate_limit()
def index():
    """Root endpoint - network info"""
    return jsonify({
        "status": "online",
        "network": CONFIG['network_name'],
        "version": CONFIG['network_version'],
        "timestamp": int(time.time()),
        "explorer": f"{request.host_url}explorer",
        "api_docs": f"{request.host_url}docs",
        "endpoints": {
            "status": "/status",
            "blocks": "/blocks",
            "block": "/block/<index_or_hash>",
            "transaction": "/tx/<hash>",
            "balance": "/balance/<address>",
            "mempool": "/mempool",
            "stats": "/api/stats"
        }
    })

@app.route("/status")
@rate_limit()
def status():
    """Detailed network status"""
    stats = get_network_stats()
    return jsonify({
        "status": "online",
        "network": CONFIG['network_name'],
        "version": CONFIG['network_version'],
        "timestamp": int(time.time()),
        **stats
    })

@app.route("/api/stats")
@rate_limit()
def api_stats():
    """API stats endpoint for explorer"""
    return jsonify(get_network_stats())

@app.route("/pool")
@rate_limit()
def pool():
    """Pool information"""
    p = ensure_pool()
    return jsonify(p)

@app.route("/balance/<address>")
@rate_limit()
def balance(address):
    """Get balance for address"""
    if len(address) != 40:
        return jsonify({"error": "Invalid address format"}), 400
    
    wallet_info = get_wallet_balance(address)
    return jsonify(wallet_info)

@app.route("/api/balance/<address>")
@rate_limit()
def api_balance(address):
    """Simple balance API"""
    s = load_state()
    return jsonify({
        "address": address,
        "balance": s.get(address, 0)
    })

@app.route("/blocks")
@rate_limit()
def blocks():
    """Get all blocks (paginated recommended for production)"""
    chain = load_blockchain()
    limit = request.args.get('limit', type=int)
    offset = request.args.get('offset', 0, type=int)
    
    if limit:
        return jsonify(chain[offset:offset+limit])
    return jsonify(chain)

@app.route("/api/blocks")
@rate_limit()
def api_blocks():
    """API blocks endpoint"""
    chain = load_blockchain()
    limit = request.args.get('limit', 10, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    blocks = chain[offset:offset+limit]
    # Add transaction count
    for b in blocks:
        b['tx_count'] = len(b.get('transactions', []))
    
    return jsonify(blocks)

@app.route("/block/<identifier>")
@rate_limit()
def get_block(identifier):
    """Get block by index or hash"""
    # Try index first
    if identifier.isdigit():
        block = get_block_by_index(int(identifier))
    else:
        block = get_block_by_hash(identifier)
    
    if not block:
        return jsonify({"error": "Block not found"}), 404
    
    return jsonify(block)

@app.route("/tx/<tx_hash>")
@rate_limit()
def get_tx_endpoint(tx_hash):
    """Get transaction by hash"""
    tx = get_transaction(tx_hash)
    if not tx:
        return jsonify({"error": "Transaction not found"}), 404
    return jsonify(tx)

@app.route("/api/tx/<tx_hash>")
@rate_limit()
def api_tx(tx_hash):
    """API transaction endpoint"""
    return get_tx_endpoint(tx_hash)

@app.route("/mempool")
@rate_limit()
def mempool():
    """Get mempool contents"""
    return jsonify(load_mempool())

@app.route("/api/mempool")
@rate_limit()
def api_mempool():
    """API mempool endpoint"""
    mempool = load_mempool()
    # Add hashes
    for tx in mempool:
        tx['hash'] = sha256(json.dumps(tx, sort_keys=True))
    return jsonify(mempool)

@app.route("/address/<address>")
@rate_limit()
def address_info(address):
    """Get full address information"""
    if len(address) != 40:
        return jsonify({"error": "Invalid address format"}), 400
    
    return jsonify(get_wallet_balance(address))

@app.route("/api/address/<address>/history")
@rate_limit()
def api_address_history(address):
    """Get address transaction history"""
    history = get_address_history(address)
    return jsonify({
        "address": address,
        "transaction_count": len(history),
        "transactions": history
    })

@app.route("/create_wallet", methods=["POST"])
@rate_limit()
def create_wallet_api():
    """Create a new wallet"""
    return jsonify(generate_wallet())

@app.route("/send", methods=["POST"])
@rate_limit()
def send():
    """Submit a transaction"""
    tx = request.json
    if not tx:
        return jsonify({"error": "No transaction data"}), 400
    
    # Validate
    ok, msg = validate_tx(tx)
    if not ok:
        return jsonify({"error": msg}), 400
    
    # Process transaction
    s = load_state()
    sender = tx["from"]
    to = tx["to"]
    amount = float(tx["amount"])
    
    # Update balances
    s[sender] = s.get(sender, 0) - amount
    s[to] = s.get(to, 0) + amount
    save_state(s)
    
    # Update nonce
    nonces = load_nonces()
    nonces[sender] = tx["nonce"]
    save_nonces(nonces)
    
    # Add to mempool
    tx['hash'] = sha256(json.dumps(tx, sort_keys=True))
    tx['received_at'] = int(time.time())
    add_tx_to_mempool(tx)
    
    # Add to ledger
    add_to_ledger(tx['hash'], tx)
    
    logging.info(f"Transaction accepted: {tx['hash'][:16]}... | {sender[:12]}... -> {to[:12]}... | {amount} VLC")
    
    return jsonify({
        "accepted": True,
        "tx_hash": tx['hash'],
        "status": "pending",
        "confirmations": 0
    })

@app.route("/mine", methods=["POST"])
@rate_limit(10, 60)
def mine():
    """Mine a new block"""
    data = request.json or {}
    miner_address = data.get('miner_address', FUND_WALLET)
    
    mem = load_mempool()
    if not mem:
        return jsonify({"error": "No transactions in mempool"}), 400
    
    try:
        block = mine_block(mem, miner_address)
        return jsonify({
            "success": True,
            "block": block,
            "mined_by": miner_address
        })
    except Exception as e:
        logging.error(f"Mining failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/network/difficulty")
@rate_limit()
def get_difficulty():
    """Get current difficulty"""
    return jsonify({
        "difficulty": DIFFICULTY,
        "target": "0" * DIFFICULTY
    })

# -----------------------
# EXPLORER ROUTES
@app.route("/explorer")
@rate_limit()
def explorer():
    """Blockchain explorer homepage"""
    return render_template_string(EXPLORER_HTML)

@app.route("/explorer/blocks")
@rate_limit()
def explorer_blocks():
    """Explorer blocks page"""
    return render_template_string(EXPLORER_HTML)

@app.route("/explorer/txs")
@rate_limit()
def explorer_txs():
    """Explorer transactions page"""
    return render_template_string(EXPLORER_HTML)

@app.route("/explorer/block/<identifier>")
@rate_limit()
def explorer_block(identifier):
    """Explorer block detail page"""
    # Try index first
    if identifier.isdigit():
        block = get_block_by_index(int(identifier))
    else:
        block = get_block_by_hash(identifier)
    
    if not block:
        return "<h1>Block not found</h1>", 404
    
    tx_html_parts = []
    for i, tx in enumerate(block.get('transactions', [])):
        tx_hash = sha256(json.dumps(tx, sort_keys=True))
        tx_from = tx.get('from', 'N/A')[:20]
        tx_to = tx.get('to', 'N/A')[:20]
        tx_amount = tx.get('amount', 0)
        tx_html_parts.append(
            f'<div class="field" style="margin: 15px 0; padding: 20px;">'
            f'<div class="label">TX {i+1}</div>'
            f'<div class="value" style="margin: 8px 0;">'
            f'<a href="/explorer/tx/{tx_hash}" style="color: #A78BFA; text-decoration: none; font-size: 0.95em;">'
            f'{tx_hash[:40]}...'
            f'</a>'
            f'</div>'
            f'<div style="color: #9CA3AF; font-size: 0.9em; margin-top: 10px;">'
            f'From: <span style="color: #E5E7EB;">{tx_from}...</span> → '
            f'To: <span style="color: #E5E7EB;">{tx_to}...</span> | '
            f'<span style="color: #10B981; font-weight: 600;">{tx_amount} VLC</span>'
            f'</div>'
            f'</div>'
        )
    tx_html = ''.join(tx_html_parts)

    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Block #{block['index']} | VelCoin Explorer</title>
        <style>
            body {{ font-family: sans-serif; background: #0f0d1a; color: #e5e7eb; padding: 40px; }}
            .container {{ max-width: 900px; margin: 0 auto; }}
            h1 {{ color: #8B5CF6; }}
            .field {{ background: rgba(139,92,246,0.1); padding: 15px; margin: 10px 0; border-radius: 8px; }}
            .label {{ color: #A78BFA; font-size: 0.9em; }}
            .value {{ font-family: monospace; word-break: break-all; }}
            a {{ color: #8B5CF6; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Block #{block['index']}</h1>
            <div class="field"><div class="label">Block Hash</div><div class="value">{block['block_hash']}</div></div>
            <div class="field"><div class="label">Previous Hash</div><div class="value">{block['previous_hash']}</div></div>
            <div class="field"><div class="label">Timestamp</div><div class="value">{datetime.fromtimestamp(block['timestamp'])}</div></div>
            <div class="field"><div class="label">Nonce</div><div class="value">{block['nonce']}</div></div>
            <div class="field"><div class="label">Merkle Root</div><div class="value">{block.get('merkle_root', 'N/A')}</div></div>
            <div class="field"><div class="label">Transactions</div><div class="value">{len(block.get('transactions', []))}</div></div>
            <div class="field"><div class="label">Difficulty</div><div class="value">{block.get('difficulty', DIFFICULTY)}</div></div>
            <h2 style="margin-top: 30px; color: #A78BFA;">Transactions</h2>
            {tx_html}
            <p><a href="/explorer"> Back to Explorer</a></p>
        </div>
    </body>
    </html>
    '''
    return html

@app.route("/explorer/tx/<tx_hash>")
@rate_limit()
def explorer_tx(tx_hash):
    """Explorer transaction detail page"""
    tx = get_transaction(tx_hash)
    if not tx:
        return "<h1>Transaction not found</h1>", 404
    
    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Transaction {tx_hash[:16]}... | VelCoin Explorer</title>
        <style>
            body {{ font-family: sans-serif; background: #0f0d1a; color: #e5e7eb; padding: 40px; }}
            .container {{ max-width: 900px; margin: 0 auto; }}
            h1 {{ color: #8B5CF6; }}
            .field {{ background: rgba(139,92,246,0.1); padding: 15px; margin: 10px 0; border-radius: 8px; }}
            .label {{ color: #A78BFA; font-size: 0.9em; }}
            .value {{ font-family: monospace; word-break: break-all; }}
            .badge {{ display: inline-block; padding: 5px 15px; border-radius: 20px; font-size: 0.9em; }}
            .badge-success {{ background: rgba(16,185,129,0.2); color: #10B981; }}
            .badge-pending {{ background: rgba(245,158,11,0.2); color: #F59E0B; }}
            a {{ color: #8B5CF6; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Transaction Details</h1>
            <div class="field">
                <div class="label">Status</div>
                <div class="value"><span class="badge {'badge-success' if tx.get('status') == 'confirmed' else 'badge-pending'}">{tx.get('status', 'unknown').upper()}</span></div>
            </div>
            <div class="field"><div class="label">Transaction Hash</div><div class="value">{tx_hash}</div></div>
            <div class="field"><div class="label">From</div><div class="value">{tx.get('from', 'N/A')}</div></div>
            <div class="field"><div class="label">To</div><div class="value">{tx.get('to', 'N/A')}</div></div>
            <div class="field"><div class="label">Amount</div><div class="value">{tx.get('amount', 0)} VLC</div></div>
            <div class="field"><div class="label">Nonce</div><div class="value">{tx.get('nonce', 'N/A')}</div></div>
            {'<div class="field"><div class="label">Block</div><div class="value"><a href="/explorer/block/' + str(tx.get('block_index')) + '">#' + str(tx.get('block_index')) + '</a></div></div>' if tx.get('block_index') else ''}
            {'<div class="field"><div class="label">Confirmations</div><div class="value">' + str(tx.get('confirmations', 0)) + '</div></div>' if tx.get('confirmations') else ''}
            <div class="field"><div class="label">Timestamp</div><div class="value">{datetime.fromtimestamp(tx.get('timestamp', tx.get('received_at', 0)))}</div></div>
            <p><a href="/explorer"> Back to Explorer</a></p>
        </div>
    </body>
    </html>
    '''
    return html

@app.route("/explorer/address/<address>")
@rate_limit()
def explorer_address(address):
    """Explorer address detail page"""
    if len(address) != 40:
        return "<h1>Invalid address</h1>", 400
    
    info = get_wallet_balance(address)

    tx_html_parts = []
    if info['transactions']:
        for t in info['transactions']:
            direction = 'SENT' if t.get('from') == address else 'RECEIVED'
            amount = t.get('amount', 0)
            ts = datetime.fromtimestamp(t.get('timestamp', t.get('received_at', 0)))
            if t.get('block_index'):
                block_info = f'<div style="font-size: 0.85em;">Block #{t.get("block_index")}</div>'
            else:
                block_info = '<div style="font-size: 0.85em; color: #F59E0B;">Pending</div>'
            tx_html_parts.append(
                f'<div class="tx">'
                f'<div>{direction} {amount} VLC</div>'
                f'<div style="font-size: 0.9em; color: #9CA3AF;">{ts}</div>'
                f'{block_info}'
                f'</div>'
            )
        tx_html = ''.join(tx_html_parts)
    else:
        tx_html = '<div style="color: #6B7280;">No transactions found</div>'

    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Address {address[:16]}... | VelCoin Explorer</title>
        <style>
            body {{ font-family: sans-serif; background: #0f0d1a; color: #e5e7eb; padding: 40px; }}
            .container {{ max-width: 900px; margin: 0 auto; }}
            h1 {{ color: #8B5CF6; }}
            .balance {{ font-size: 3em; color: #A78BFA; margin: 20px 0; }}
            .field {{ background: rgba(139,92,246,0.1); padding: 15px; margin: 10px 0; border-radius: 8px; }}
            .label {{ color: #A78BFA; font-size: 0.9em; }}
            .tx {{ background: rgba(0,0,0,0.2); padding: 15px; margin: 10px 0; border-radius: 8px; }}
            a {{ color: #8B5CF6; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Address</h1>
            <div class="field"><div class="label">Address</div><div style="font-family: monospace; word-break: break-all;">{address}</div></div>
            <div class="balance">{info['balance']} VLC</div>
            <div class="field"><div class="label">Total Transactions</div><div>{info['transaction_count']}</div></div>
            <h2 style="margin-top: 30px; color: #A78BFA;">Recent Transactions</h2>
            {tx_html}
            <p><a href="/explorer"> Back to Explorer</a></p>
        </div>
    </body>
    </html>
    '''
    return html

@app.route("/logo")
@rate_limit()
def logo():
    """Serve logo placeholder - replace with actual logo file"""
    # Return a simple SVG logo
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">
        <defs>
            <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#8B5CF6"/>
                <stop offset="100%" style="stop-color:#7C3AED"/>
            </linearGradient>
        </defs>
        <circle cx="100" cy="100" r="95" fill="#1F1F2E" stroke="url(#g)" stroke-width="8"/>
        <text x="100" y="130" text-anchor="middle" fill="url(#g)" font-size="80" font-weight="bold" font-family="Arial">V</text>
    </svg>'''
    from flask import Response
    return Response(svg, mimetype='image/svg+xml')

# -----------------------
# API DOCUMENTATION
API_DOCS = '''
<!DOCTYPE html>
<html>
<head>
    <title>VelCoin API Documentation</title>
    <style>
        body { font-family: sans-serif; max-width: 1000px; margin: 0 auto; padding: 40px; background: #0f0d1a; color: #e5e7eb; }
        h1 { color: #8B5CF6; }
        h2 { color: #A78BFA; margin-top: 30px; }
        .endpoint { background: rgba(139,92,246,0.1); padding: 20px; margin: 15px 0; border-radius: 8px; }
        .method { display: inline-block; padding: 4px 12px; border-radius: 4px; font-size: 0.85em; font-weight: bold; margin-right: 10px; }
        .get { background: #10B981; color: white; }
        .post { background: #8B5CF6; color: white; }
        code { background: rgba(0,0,0,0.3); padding: 2px 8px; border-radius: 4px; font-family: monospace; }
        pre { background: rgba(0,0,0,0.3); padding: 20px; border-radius: 8px; overflow-x: auto; }
    </style>
</head>
<body>
    <h1>VelCoin API Documentation</h1>
    <p>Complete API reference for VelCoin (VLC) blockchain integration.</p>
    
    <h2>Network Endpoints</h2>
    <div class="endpoint">
        <span class="method get">GET</span><code>/</code>
        <p>Network information and available endpoints.</p>
    </div>
    <div class="endpoint">
        <span class="method get">GET</span><code>/status</code>
        <p>Detailed network status including block height, supply, and holders.</p>
    </div>
    <div class="endpoint">
        <span class="method get">GET</span><code>/api/stats</code>
        <p>Network statistics for explorers and monitoring.</p>
    </div>
    
    <h2>Blockchain Endpoints</h2>
    <div class="endpoint">
        <span class="method get">GET</span><code>/blocks</code>
        <p>Get all blocks. Use <code>?limit=10&offset=0</code> for pagination.</p>
    </div>
    <div class="endpoint">
        <span class="method get">GET</span><code>/block/&lt;index_or_hash&gt;</code>
        <p>Get specific block by index number or block hash.</p>
    </div>
    <div class="endpoint">
        <span class="method get">GET</span><code>/tx/&lt;hash&gt;</code>
        <p>Get transaction by hash (from blockchain or mempool).</p>
    </div>
    
    <h2>Account Endpoints</h2>
    <div class="endpoint">
        <span class="method get">GET</span><code>/balance/&lt;address&gt;</code>
        <p>Get balance and transaction history for address.</p>
    </div>
    <div class="endpoint">
        <span class="method get">GET</span><code>/address/&lt;address&gt;</code>
        <p>Full address information with recent transactions.</p>
    </div>
    <div class="endpoint">
        <span class="method get">GET</span><code>/api/address/&lt;address&gt;/history</code>
        <p>Complete transaction history for address.</p>
    </div>
    
    <h2>Transaction Endpoints</h2>
    <div class="endpoint">
        <span class="method get">GET</span><code>/mempool</code>
        <p>Get pending transactions in mempool.</p>
    </div>
    <div class="endpoint">
        <span class="method post">POST</span><code>/send</code>
        <p>Submit a signed transaction.</p>
        <pre>{
  "from": "sender_address",
  "to": "recipient_address",
  "amount": 100.0,
  "nonce": 1,
  "public_key": "public_key_hex",
  "signature": "signature_hex"
}</pre>
    </div>
    
    <h2>Wallet Endpoints</h2>
    <div class="endpoint">
        <span class="method post">POST</span><code>/create_wallet</code>
        <p>Generate a new wallet with private key, public key, and address.</p>
    </div>
    
    <h2>Mining Endpoints</h2>
    <div class="endpoint">
        <span class="method post">POST</span><code>/mine</code>
        <p>Mine a new block with current mempool transactions.</p>
        <pre>{
  "miner_address": "optional_miner_address"
}</pre>
    </div>
    
    <h2>Explorer</h2>
    <p>Visit <code>/explorer</code> for the web-based blockchain explorer.</p>
</body>
</html>
'''

@app.route("/docs")
@rate_limit()
def docs():
    """API documentation"""
    return render_template_string(API_DOCS)

# -----------------------
# ERROR HANDLERS
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found", "path": request.path}), 404

@app.errorhandler(500)
def server_error(e):
    logging.error(f"Server error: {e}")
    return jsonify({"error": "Internal server error"}), 500

# -----------------------
# HEALTH CHECK
@app.route("/health")
@rate_limit()
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": int(time.time()),
        "uptime": int(time.time())
    })

# -----------------------
# INIT
def initialize():
    """Initialize the blockchain"""
    logging.info("=" * 50)
    logging.info("VelCoin Node Starting")
    logging.info(f"Network: {CONFIG['network_name']}")
    logging.info(f"Version: {CONFIG['network_version']}")
    logging.info("=" * 50)
    
    # PRIMERO: Intentar restaurar desde GitHub (ANTES de cualquier otra operación)
    restore_all_from_github()
    
    # AHORA cargar los datos (ya restaurados o nuevos)
    chain = load_blockchain()
    state = load_state()
    
    logging.info(f"Loaded blockchain: {len(chain)} blocks")
    logging.info(f"Loaded state: {len(state)} addresses")
    if state:
        total_supply = sum(state.values())
        logging.info(f"Total supply: {total_supply} VLC")
    
    # Create genesis block ONLY if no blockchain exists
    if not chain:
        genesis = create_genesis_block()
        logging.info(f"Genesis block created: {genesis['block_hash'][:16]}...")
    else:
        logging.info(f"Using existing chain, last block: {chain[-1]['block_hash'][:16]}...")
    
    # Ensure ledger exists
    ensure_ledger()
    
    # Ensure pool tracking
    ensure_pool()
    
    # Initialize nonces if empty
    if not load_nonces():
        save_nonces({})
    
    logging.info("Node initialization complete")

# Run initialization
initialize()

# Gunicorn importará directamente la variable `app`
# Este bloque solo se ejecuta si corres: python app.py

if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True
    )
