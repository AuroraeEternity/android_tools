#!/bin/bash

# Function to cleanup background processes on exit
cleanup() {
    echo "Stopping services..."
    kill $BACKEND_PID $FRONTEND_PID
    exit
}

trap cleanup SIGINT

echo "Starting Android Test Tool..."

# Start Backend
echo "[Backend] Starting Flask server on port 5000..."
cd backend
# Check if requirements are installed (basic check)
if ! python3 -c "import flask" 2>/dev/null; then
    echo "[Backend] Installing requirements..."
    pip install -r requirements.txt
fi
python3 app.py &
BACKEND_PID=$!
cd ..

# Start Frontend
echo "[Frontend] Starting Vite server..."
cd frontend
if [ ! -d "node_modules" ]; then
    echo "[Frontend] Installing dependencies..."
    npm install
fi
npm run dev &
FRONTEND_PID=$!
cd ..

echo "Services started. Press Ctrl+C to stop."
echo "Backend: http://127.0.0.1:5000"
echo "Frontend: http://localhost:5173"

wait

