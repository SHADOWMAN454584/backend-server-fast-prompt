# Public Transport Enquiry Chatbot - Server

A FastAPI-based public transport enquiry chatbot powered by Google Gemini AI.

## Features

- **Route Information**: Get details about bus, train, metro, and other public transport routes
- **Crowd Information**: Know about congestion levels and crowd status on different routes
- **Nearest Transport Stops**: Find the nearest bus stops, train stations, cab/rickshaw stands
- **Travel Planning**: Get comprehensive public transport information to help plan journeys
- **Image Analysis**: Upload transport-related images for detailed analysis and information

## Technology Stack

- **Framework**: FastAPI
- **AI Model**: Google Gemini 1.5 Flash
- **Deployment**: Render
- **Language**: Python 3.9+

## Environment Variables

- `GEMINI_API_KEY`: Your Google Gemini API key (required)
- `PORT`: Server port (default: 8000)

## API Endpoints

For detailed API endpoints documentation, see [API_ENDPOINTS.md](../API_ENDPOINTS.md)

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set environment variables:
   ```bash
   export GEMINI_API_KEY="your_api_key_here"
   ```

3. Run the server:
   ```bash
   python main.py
   ```

The API will be available at `http://localhost:8000`

