# Use an official lightweight Python image
# Specifying the platform ensures compatibility with Render's linux/amd64 environment
FROM --platform=linux/amd64 python:3.11-slim

# Set environment variables to optimize Python for containers
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies if needed (e.g., for sqlite or networking)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only the requirements file first to leverage Docker caching
COPY requirements.txt .

# Install Python dependencies
# The --no-cache-dir flag keeps the image size small
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your bot's code into the container
COPY . .

# Expose the port your health check server uses (usually 8080)
EXPOSE 8080

# Command to run the bot
CMD ["python", "bot.py"]
