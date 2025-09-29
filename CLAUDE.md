# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Application Overview

This is a Korean train reservation bot that automates ticket booking for KTX (Korail) and SRT services via Telegram. The bot supports both single immediate booking and multi-course monitoring modes with automatic reservation upon ticket availability.

## Running the Application

### Local Development
```bash
python main2.py
```

### Docker Deployment
```bash
docker build -t travel-assistant-bot .
docker run --env-file .env travel-assistant-bot
```

### Server Environment
The application runs on Render.com and automatically detects server environments via `RENDER` environment variable, enabling headless Chrome mode.

## Security and Credential Management

### Credential Configuration Methods
The application supports three credential loading methods (priority order):
1. **Encrypted environment variables** (production): `USE_ENCRYPTED_ENV=true` + encrypted vars with `_ENC` suffix
2. **Encrypted local file** (development): `credentials.enc` file
3. **Plain environment variables** (fallback): Standard env vars

### Required Environment Variables
```
TELEGRAM_BOT_TOKEN    # Telegram bot token
KORAIL_USER          # Korail login ID
KORAIL_PASS          # Korail password
KORAIL_PASS_BANK     # Card password (6 digits)
Card_Num1_korail     # Card number part 1
Card_Num2_korail     # Card number part 2
Card_Num3_korail     # Card number part 3
Card_Num4_korail     # Card number part 4
Card_Num5_korail     # Card PIN front 2 digits
CARD_MONTH           # Card expiry month
Id_Num1_korail       # ID number front 6 digits
SRT_ID               # SRT login ID
SRT_PWD              # SRT password
```

### Encryption Tools
```bash
# Generate encrypted environment variables
python encrypt_credentials.py --env

# Generate encrypted file
python encrypt_credentials.py --file

# Validate current credentials
python secure_config.py
```

## Core Architecture

### Main Components

**main2.py** - Telegram bot interface with conversation handlers for train search, date/time selection, and reservation flow.

**pipeline.py** - Core reservation system with three main classes:
- `TargetRegistry`: Manages reservation targets with group-based locking to prevent duplicate bookings
- `ScannerWorker`: Continuously scans for available trains with rate limiting (95 requests/minute total)
- `ReservationExecutor`: Handles actual train reservations and payment automation

**TrainReservation class** (main2.py) - Interfaces with Korean train APIs:
- Korail API via `letskorail` library
- SRT API via `SRT` library
- Handles login, search, and booking operations

### Multi-Course Monitoring System

The system supports monitoring multiple train routes simultaneously:
- `TargetItem` objects contain `group_id`, `priority`, and `scan_only` fields
- Group-based locking prevents race conditions when multiple tickets become available
- Priority-based selection chooses best available option
- Rate limiting distributed across all active targets

### Payment Automation

**korail_payment.py** - Selenium-based payment automation:
- Supports both local (GUI) and server (headless) Chrome modes
- Environment detection via `RENDER`, `HEROKU`, or `DOCKER` variables
- Automated form filling for Korean payment systems

## Key Libraries and Dependencies

### Train Booking APIs
- `letskorail-master/`: Korean rail (KTX) booking library
- `SRT-2.6.7/`: SRT high-speed rail booking library
- `korail2`: Alternative Korail library

### External Dependencies
- `python-telegram-bot==20.7`: Telegram bot framework
- `selenium==4.15.2`: Web automation for payment
- `cryptography==43.0.3`: Credential encryption
- `webdriver-manager==4.0.1`: Chrome driver management

## Service Discovery and Debugging

### Checking Credential Status
```bash
python secure_config.py
```
Shows masked credential status and validates required environment variables.

### Log Files
- `korail_payment.log`: Payment automation logs
- Console logs: Application startup, API calls, and reservation status

### Rate Limiting
- Global limit: 95 requests/minute across all targets
- Per-target backoff on failures
- Smart scheduling based on priority and success rates

## Development Notes

### Chrome Driver Setup
- Automatically downloads ChromeDriver via webdriver-manager
- Server environment uses headless mode with specific options for containerized environments
- Local development can run with GUI for debugging payment flows

### Async Architecture
- Main application runs asyncio event loop
- Concurrent scanning and reservation handling
- Thread-safe target registry with asyncio locks

### Multi-Language Support
The codebase contains Korean language strings and is designed for Korean train booking systems. Payment flows and station names are in Korean.

## Production Deployment

### Render.com Configuration
- Dockerfile builds Python 3.11 with Chrome installation
- Environment variables configured via Render dashboard
- Auto-scaling disabled for consistent monitoring
- Keep-alive workflow in `.github/workflows/keep-alive.yml` prevents service sleep

### Critical Files Not in Repository
- `.env`: Local credentials (gitignored)
- `credentials.enc`: Encrypted credential file (gitignored)
- `reservation_status.json`: Runtime state (gitignored)

When working with this codebase, ensure credential security by never committing sensitive environment variables and always using the secure credential loading system.