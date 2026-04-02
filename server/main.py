# main.py - KrishiMithra FastAPI Server for Render Deployment
import os
from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
from PIL import Image
import io
import uvicorn
from typing import Optional

# Initialize FastAPI app
app = FastAPI(
    title="Public Transport Enquiry API",
    description="AI-powered public transport expert providing information about routes, crowd, and nearest transport options",
    version="1.0.0"
)

# Configure CORS for all origins (required for Flutter app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your Flutter app domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get API key from environment variable
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is required")

# Configure Google Gemini
genai.configure(api_key=GEMINI_API_KEY)
# Use the vision-capable model
model = genai.GenerativeModel('gemini-2.0-flash')

# Public Transport Enquiry system prompt
PUBLIC_TRANSPORT_SYSTEM_PROMPT = """You are a Public Transport Expert Chatbot designed to assist users with comprehensive public transportation information.

IMPORTANT GUIDELINES:
- You ONLY answer questions related to public transport, including buses, trains, metros, cabs, rickshaws, and auto-rickshaws.
- Provide information about: routes and schedules, crowd or congestion levels, ticket prices, nearest transport stops, travel time estimates, and available transportation options.
- If asked about anything outside public transportation, politely redirect: "I'm a public transport expert. Please ask me about bus routes, trains, nearest transport stops, crowds, or any transportation-related queries."
- Always provide practical, accurate information that helps users plan their journeys.
- Consider local transport systems and real-time conditions when relevant.
- Be helpful, courteous, and supportive to travelers.
- Use simple, clear language that all users can easily understand.
- For image analysis, focus on identifying transport-related scenes, vehicles, stops, or route indicators.
- Provide information that helps users find the quickest, most convenient, and cost-effective transport options.

Remember: You are here to help users navigate public transportation efficiently and reach their destinations seamlessly."""

# Pydantic models
class TextPrompt(BaseModel):
    prompt: str

class APIResponse(BaseModel):
    success: bool
    response: str
    error: Optional[str] = None

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Public Transport Enquiry API is running successfully!",
        "status": "healthy",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "text_chat": "/generate (POST)",
            "image_analysis": "/analyze-image (POST)",
            "documentation": "/docs"
        }
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "model": "gemini-2.0-flash",
        "service": "Public Transport Enquiry API"
    }

# Text-based transport enquiry endpoint
@app.post("/generate", response_model=APIResponse)
async def generate_transport_info(body: TextPrompt):
    """
    Generate public transport information from text prompt
    """
    try:
        if not body.prompt.strip():
            return APIResponse(
                success=False,
                response="",
                error="Please provide a transport-related question"
            )
        
        # Combine system prompt with user question
        full_prompt = f"{PUBLIC_TRANSPORT_SYSTEM_PROMPT}\n\nUser Query: {body.prompt.strip()}"
        
        # Generate response using Gemini
        response = model.generate_content(full_prompt)
        
        if not response.text:
            return APIResponse(
                success=False,
                response="",
                error="No response generated. Please try again."
            )
        
        return APIResponse(
            success=True,
            response=response.text,
            error=None
        )
        
    except Exception as e:
        print(f"Error in generate_transport_info: {str(e)}")
        return APIResponse(
            success=False,
            response="",
            error="Sorry, I'm having trouble processing your request. Please try again later."
        )

# Image analysis endpoint
@app.post("/analyze-image", response_model=APIResponse)
async def analyze_transport_image(
    file: UploadFile = File(...),
    prompt: str = Form("Analyze this transport-related image and provide transport information")
):
    """
    Analyze transport-related images and provide information
    """
    try:
        print(f"=== IMAGE ANALYSIS REQUEST ===")
        print(f"File name: {file.filename}")
        print(f"Content type: {file.content_type}")
        print(f"Prompt: {prompt}")
        
        # Validate file type
        if not file.content_type.startswith('image/'):
            print(f"Invalid file type: {file.content_type}")
            return APIResponse(
                success=False,
                response="",
                error="Please upload a valid image file"
            )
        
        # Read and process the image
        image_data = await file.read()
        print(f"Image data size: {len(image_data)} bytes")
        
        image = Image.open(io.BytesIO(image_data))
        print(f"Image processed: {image.size}, mode: {image.mode}")
        
        # Combine system prompt with user prompt for image analysis
        full_prompt = f"{PUBLIC_TRANSPORT_SYSTEM_PROMPT}\n\nUser Query: {prompt}\n\nPlease analyze the attached image and provide specific transport information based on what you observe."
        
        print("Sending to Gemini with image...")
        # Generate response with image analysis
        response = model.generate_content([full_prompt, image])
        
        print(f"Gemini response received: {len(response.text) if response.text else 0} characters")
        
        if not response.text:
            print("No response text from Gemini")
            return APIResponse(
                success=False,
                response="",
                error="Could not analyze the image. Please try again."
            )
        
        print("Returning successful response")
        return APIResponse(
            success=True,
            response=response.text,
            error=None
        )
        
    except Exception as e:
        print(f"Error in analyze_transport_image: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return APIResponse(
            success=False,
            response="",
            error=f"Sorry, I couldn't process your image. Error: {str(e)}"
        )

# Ping endpoint for monitoring
@app.get("/ping")
async def ping():
    return {"ping": "pong", "timestamp": "ok"}

# Run the application
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
