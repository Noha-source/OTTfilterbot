# Use a lightweight Python version
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the bot code
COPY . .

# Expose port 8080 (Required for Render Web Services)
EXPOSE 8080

# Command to run the bot
CMD ["python", "main.py"]
