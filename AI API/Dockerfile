# Use an official Python runtime as a parent image
FROM python:3.11-slim-bookworm

# Install ca-certificates for SSL/TLS connections
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY ./requirements.txt /app/requirements.txt

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . /app

# Create a shell script to start the application
RUN echo '#!/bin/bash\nuvicorn api:app --host 0.0.0.0 --port ${PORT:-8001}' > /app/start.sh && \
    chmod +x /app/start.sh

# Expose the port FastAPI will run on
EXPOSE 8080

# Run the shell script when the container starts
CMD ["bash", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8080}"] 