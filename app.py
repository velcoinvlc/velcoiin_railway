import os
from flask import Flask, jsonify, request
import json, hashlib, time, logging, random, string
from functools import wraps
from collections import defaultdict

app = Flask(__name__)

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

# -----------------------
# LOGGING
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# -----------------------
# RATE LIMIT
RATE_LIMIT = defaultdict(list)
def rate_limit(max_calls=20, window=60):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            ip = request.remote_addr
            now = time.time()
            RATE_LIMIT[ip] = [t for t in RATE_LIMIT[ip] if now - t < window]
            if len(RATE_LIMIT[ip]) >= max_calls:
                return jsonify({"error":"rate limit"}),429
            RATE_LIMIT[ip].append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator

# -----------------------
# CRYPTO
def sha256(msg):
    return hashlib.sha256(msg.encode()).hexdigest()

def derive_address(public_key):
    return sha256(public_key)[:40]

def sign_tx(private_key, payload):
    return sha256(private_key + payload)

def verify_signature(public_key, payload, signature):
    expected = sha256(sha256(public_key) + payload)
    return expected == signature

# -----------------------
# JSON IO
def load_json(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except:
            return default
    return default

def save_json(path, data):
    json.dump(data, open(path,"w"), indent=2)

# -----------------------
# STATE
def load_state(): return load_json(STATE_FILE, {})
def save_state(x): save_json(STATE_FILE, x)

# -----------------------
# NONCES
def load_nonces(): return load_json(NONCE_FILE, {})
def save_nonces(x): save_json(NONCE_FILE, x)

# -----------------------
# LEDGER
def load_ledger(): return load_json(LEDGER_FILE, [])
def save_ledger(x): save_json(LEDGER_FILE, x)
def ensure_ledger():
    if not os.path.exists(LEDGER_FILE): save_ledger([])
    return load_ledger()

# -----------------------
# MEMPOOL
def load_mempool(): return load_json(MEMPOOL_FILE, [])
def save_mempool(x): save_json(MEMPOOL_FILE, x)
def add_tx_to_mempool(tx):
    mempool = load_mempool()
    mempool.append(tx)
    save_mempool(mempool)

# -----------------------
# BLOCKCHAIN
def load_blockchain(): return load_json(BLOCKCHAIN_FILE, [])
def save_blockchain(x): save_json(BLOCKCHAIN_FILE, x)
DIFFICULTY = 4

def create_genesis_block():
    chain = load_blockchain()
    if chain: return
    g = {"index":0,"timestamp":int(time.time()),"transactions":[],"previous_hash":"0"*64,"nonce":0}
    g["block_hash"]=sha256(json.dumps(g,sort_keys=True))
    chain.append(g)
    save_blockchain(chain)

def mine_block(transactions):
    chain = load_blockchain()
    last = chain[-1]
    index = last["index"] + 1
    previous_hash = last["block_hash"]
    nonce = 0
    while True:
        block = {"index": index, "timestamp": int(time.time()), "transactions": transactions, "previous_hash": previous_hash, "nonce": nonce}
        block_hash = sha256(json.dumps(block, sort_keys=True))
        if block_hash.startswith("0"*DIFFICULTY):
            block["block_hash"] = block_hash
            chain.append(block)
            save_blockchain(chain)
            logging.info(f"Block mined: {block_hash} | txs: {len(transactions)}")
            return block
        nonce += 1

# -----------------------
# WALLET FUNDADORA
FUND_WALLET_DATA = os.environ.get("VELCOIN_FUND_WALLET")
if not FUND_WALLET_DATA:
    logging.error("Wallet fundadora no encontrada en VELCOIN_FUND_WALLET")
    raise Exception("Wallet fundadora requerida")
try:
    FUND_WALLET_JSON = json.loads(FUND_WALLET_DATA)
    FUND_WALLET = FUND_WALLET_JSON["address"]
except Exception as e:
    logging.error(f"Error leyendo wallet fundadora: {e}")
    raise Exception("Wallet fundadora inválida")

# -----------------------
# POOL
def ensure_pool():
    s = load_state()
    fund_balance = s.get(FUND_WALLET, 0)
    p = {"velcoin": fund_balance, "history": []}
    save_json(POOL_FILE, p)
    return p

def get_total_supply():
    s = load_state()
    return sum(s.values())

# -----------------------
# WALLET FUNCTIONS
def generate_wallet():
    private_key = ''.join(random.choices(string.hexdigits, k=64)).lower()
    public_key = sha256(private_key)
    address = derive_address(public_key)
    return {"private_key": private_key, "public_key": public_key, "address": address}

# -----------------------
# TX VALIDATION
def validate_tx(tx):
    required = ["from","to","amount","nonce","public_key","signature"]
    for r in required:
        if r not in tx:
            return False, f"missing field {r}"

    sender = tx["from"]
    pub = tx["public_key"]
    if derive_address(pub) != sender:
        return False,"address/pubkey mismatch"

    payload = f'{tx["from"]}{tx["to"]}{tx["amount"]}{tx["nonce"]}'
    if not verify_signature(pub, payload, tx["signature"]):
        return False,"bad signature"

    nonces = load_nonces()
    last = nonces.get(sender,0)
    if tx["nonce"] <= last:
        return False,"bad nonce"

    state = load_state()
    if state.get(sender,0) < float(tx["amount"]):
        return False,"insufficient balance"

    return True,"ok"

# -----------------------
# API
@app.route("/")
@rate_limit()
def index():
    return jsonify({"status":"online","network":"velcoin-mainnet"})

@app.route("/status")
@rate_limit()
def status():
    s=load_state()
    return jsonify({"status":"online",
                    "holders":len([v for v in s.values() if v>0]),
                    "supply":get_total_supply()})

@app.route("/pool")
@rate_limit()
def pool():
    p = ensure_pool()
    return jsonify(p)

@app.route("/balance/<address>")
@rate_limit()
def balance(address):
    s = load_state()
    return jsonify({"balance": s.get(address,0)})

@app.route("/create_wallet", methods=["POST"])
@rate_limit()
def create_wallet_api():
    return jsonify(generate_wallet())

@app.route("/send", methods=["POST"])
@rate_limit()
def send():
    tx = request.json
    ok,msg = validate_tx(tx)
    if not ok:
        return jsonify({"error":msg}),400

    s = load_state()
    sender = tx["from"]
    to = tx["to"]
    amount = float(tx["amount"])

    s[sender] -= amount
    s[to] = s.get(to,0)+amount
    save_state(s)

    nonces = load_nonces()
    nonces[sender] = tx["nonce"]
    save_nonces(nonces)

    add_tx_to_mempool(tx)
    return jsonify({"accepted":True})

@app.route("/mine", methods=["POST"])
@rate_limit(5,60)
def mine():
    mem = load_mempool()
    if not mem:
        return jsonify({"error":"no tx"}),400
    block = mine_block(mem)
    save_mempool([])
    return jsonify(block)

@app.route("/blocks")
@rate_limit()
def blocks():
    return jsonify(load_blockchain())

# -----------------------
# INIT
create_genesis_block()
ensure_ledger()
ensure_pool()
save_nonces(load_nonces())

if __name__ == "__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port)
