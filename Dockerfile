# 1. Start with the same base image
FROM python:3.11-slim

# 2. Set the working directory inside the container
WORKDIR /app

# 3. Copy only the requirements first (for better caching)
COPY requirements.txt .

# 4. Run the slow install ONCE during build
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of your code
COPY . .

# 6. The final command to start Rincewind
CMD ["python", "processor.py"]