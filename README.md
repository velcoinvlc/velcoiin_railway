# VelCoin (VLC) - Native Blockchain

[![Network Status](https://img.shields.io/badge/network-online-success)](https://velcoin-vlc-l3uk.onrender.com/status)
[![Version](https://img.shields.io/badge/version-1.0.0-blueviolet)](https://velcoin-vlc.onrender.com/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

VelCoin (VLC) is a native blockchain-based digital currency with a fixed supply of 1,000,000,000 VLC. Built with Python and Flask, featuring Proof-of-Work consensus, SHA-256 cryptography, and a complete blockchain explorer.

## Official Links

- **Website:** https://velcoin-vlc.onrender.com
- **Explorer:** https://velcoin-vlc-l3uk.onrender.com/explorer
- **API Docs:** https://velcoin-vlc-l3uk.onrender.com/docs
- **Mainnet Status:** https://velcoin-vlc-l3uk.onrender.com/status

## Network Specifications

| Parameter | Value |
|-----------|-------|
| **Network Name** | velcoin-mainnet |
| **Total Supply** | 1,000,000,000 VLC (fixed) |
| **Consensus** | Proof-of-Work (SHA-256) |
| **Block Time** | ~60 seconds (target) |
| **Difficulty** | 4 leading zeros |
| **Address Format** | 40-character hexadecimal |
| **Genesis Block** | February 2026 |
| **Founder Address** | 421fe2ca5041d7fcc82f0abb96a7f03080c2e17c |

## Security Warning

**NEVER commit private keys to the repository.** The founder wallet private key must be set as an environment variable only.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set founder wallet (REQUIRED - environment variable only)
export VELCOIN_FUND_WALLET='{"private_key":"TU_CLAVE_PRIVADA_AQUI","public_key":"TU_CLAVE_PUBLICA_AQUI","address":"421fe2ca5041d7fcc82f0abb96a7f03080c2e17c"}'

# Run node
python app.py
