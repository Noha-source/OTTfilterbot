#!/bin/bash

# Define the script name
SCRIPT_NAME="bot.py"
VENV_DIR="venv"

echo "🚀 Starting OTT Bot Setup..."

# 1. Check if Python 3 is installed
if ! command -v python3 &> /dev/null
then
    echo "❌ Python 3 is not installed. Please install it first."
    exit 1
fi

# 2. Create Virtual Environment (if it doesn't exist)
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv $VENV_DIR
fi

# 3. Activate Virtual Environment
source $VENV_DIR/bin/activate

# 4. Install Dependencies
if [ -f "requirements.txt" ]; then
    echo "⬇️ Installing dependencies from requirements.txt..."
    pip install -r requirements.txt
else
    echo "⚠️ requirements.txt not found! Installing manual defaults..."
    pip install python-telegram-bot requests APScheduler
fi

# 5. Run the Bot with Auto-Restart
echo "✅ Setup complete. Starting the bot..."
echo "Press [CTRL+C] to stop."

while true
do
    python3 $SCRIPT_NAME
    echo "⚠️ Bot crashed or stopped. Restarting in 5 seconds..."
    sleep 5
done
